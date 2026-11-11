"""UB-158 / G4: a TLD4.PTP whose four constant offsets form a 2x2 square is one gather.

Usage: python3 tests-nx2/check-tld4-ptp-square-gather.py [--source-only] [SOURCE_DIR]
SOURCE_DIR contains src/ (and cpmfile.json); defaults to the prepared headless cache.

Default (Linux/dedie): the production ImageOperands class, Emit/Decorate and
EmitImageGather/EmitImageGatherDref are extracted verbatim from
src/shader_recompiler/backend/spirv/emit_spirv_image.cpp, with EmitContext's
Const/SConst helpers, and compiled (ASan/UBSan) against Sirit and SPIRV-Headers at
the cpmfile.json pins. Small IR/EmitContext stubs drive them; the harness wraps each
gather in a compute shader and writes real SPIR-V. Then:
  1. VALUE: the emitted gather operand (ConstOffset/ConstOffsets) and any
     OpVectorShuffle are read back from the SPIR-V and evaluated with the Vulkan gather
     model (x=(i0,j1) y=(i1,j1) z=(i1,j0) w=(i0,j0); per-texel wrap). That result must
     equal the ConstOffsets semantics of the guest offsets (every order, negative
     corners, repeat/mirror/clamp/border, texture sizes 1x1..5x2).
  2. HARDWARE: each module is compiled by the PINNED RADV (Mesa Mihawk, deps.json
     ps5-mesa, built for the host with the amdgpu noop drm-shim, AMDGPU_GPU_ID=navi21,
     GFX10.3 like the PS5 winsys) with RADV_DEBUG=shaders. The image_gather4* count in
     ACO's "After lowering to hw instructions" stream must be 1 for each admissible
     square (plain, mixed order with a negative corner, dref, 2D array, integer) and one
     per distinct offset for the fallbacks, which keep ConstOffsets (non-square 4,
     sparse 4, duplicate 3: RADV's CSE merges the two identical split gathers).
  Main fails step 2: it emits ConstOffsets, which RADV's nir_lower_tex
  (lower_tg4_offsets) splits into four image_gather4. A SPIR-V OpImageGather count
  cannot tell them apart (both forms have one).
--source-only: no compiler, no RADV. Reads the PTP branch of the production
ImageOperands and models what it emits for each case. Main fails because, for an
admissible square, its only immediate-PTP output is ConstOffsets. That is four
hardware gathers on the pinned RADV (G4 proof: nir_lower_tex.c:1174-1225). On the
branch, the production component table is checked against the gather model. This
mode is a model, NOT authoritative.

Environment (compiled mode):
  G4_RADV_OFFLINE  directory of a prebuilt offline RADV (libvulkan_radeon.so,
                   libamdgpu_noop_drm_shim.so, lib/ of libdrm); built under
                   build/nx2-tests/ from PS5_MESA_FORK when absent.
  PS5_MESA_FORK    pinned Mesa checkout (default: ../mihawk-mesa-review next to this
                   checkout, as tools/build-radv-dependencies.sh uses).
"""
from pathlib import Path
import hashlib
import itertools
import json
import math
import os
import platform
import random
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

args = [a for a in sys.argv[1:] if not a.startswith('--')]
source_only = '--source-only' in sys.argv[1:]
root = Path(__file__).resolve().parents[1]
source = Path(args[0]).resolve() if args else Path(
    (root / '.local/headless-cache').read_text().strip()) / 'source'
src = source / 'src'
image_cpp = (src / 'shader_recompiler/backend/spirv/emit_spirv_image.cpp').read_text()

# ---------------------------------------------------------------- the gather model
# Vulkan "Texel Gathering": i0 = floor(u*W - 0.5) + offset.x, i1 = i0 + 1 (same for j),
# each texel coordinate wrapped on its own; result x=(i0,j1) y=(i1,j1) z=(i1,j0) w=(i0,j0).
# ConstOffsets: component k is the (i0,j0) texel of a gather at offset k (SPIR-V; Mesa
# lower_tg4_offsets keeps .w of each split gather).


def wrap(i, n, mode):
    if mode == 'repeat':
        return i % n
    if mode == 'clamp_edge':
        return min(max(i, 0), n - 1)
    if mode == 'border':
        return i if 0 <= i < n else None
    t = i % (2 * n)  # mirror
    return t if t < n else 2 * n - 1 - t


def gather(img, size, u, v, off, mode):
    w, h = size
    i0 = math.floor(u * w - 0.5) + off[0]
    j0 = math.floor(v * h - 0.5) + off[1]

    def texel(i, j):
        a, b = wrap(i, w, mode), wrap(j, h, mode)
        return 'BORDER' if a is None or b is None else img[b][a]
    return (texel(i0, j0 + 1), texel(i0 + 1, j0 + 1), texel(i0 + 1, j0), texel(i0, j0))


def reference(img, size, u, v, offsets, mode):
    return tuple(gather(img, size, u, v, o, mode)[3] for o in offsets)


def emitted_value(form, img, size, u, v, mode):
    """form: ('ConstOffsets', [4 offsets]) or ('ConstOffset', corner, swizzle or None)."""
    if form[0] == 'ConstOffsets':
        return reference(img, size, u, v, form[1], mode)
    g = gather(img, size, u, v, form[1], mode)
    return tuple(g[k] for k in form[2]) if form[2] is not None else g


def check_values(name, offsets, form):
    rnd = random.Random(158)
    for size in ((1, 1), (2, 3), (4, 4), (5, 2)):
        img = [[(x, y) for x in range(size[0])] for y in range(size[1])]
        for mode in ('repeat', 'mirror', 'clamp_edge', 'border'):
            for _ in range(48):
                u, v = rnd.uniform(-2.0, 3.0), rnd.uniform(-2.0, 3.0)
                want = reference(img, size, u, v, offsets, mode)
                got = emitted_value(form, img, size, u, v, mode)
                assert got == want, (f'{name}: emitted {form} reads {got}, guest offsets '
                                     f'{offsets} read {want} ({size}, {mode}, u={u}, v={v})')


# ---------------------------------------------------------------- cases
# kind: 2d / 2d_array; flags: dref, integer, sparse. PTP registers carry (x0,y0,x1,y1),
# (x2,y2,x3,y3) like MakeOffsetPTP's two CompositeConstructU32x4.
SQUARES = [
    ('square_plain', '2d', '', [(0, 0), (1, 0), (0, 1), (1, 1)]),
    ('square_mixed_negative', '2d', '', [(-1, -1), (-2, -2), (-2, -1), (-1, -2)]),
    ('square_upstream_order', '2d', '', [(0, 1), (-1, 0), (0, 0), (-1, 1)]),
    ('square_dref', '2d', 'dref', [(1, 0), (0, 0), (1, 1), (0, 1)]),
    ('square_array', '2d_array', '', [(0, 0), (1, 0), (0, 1), (1, 1)]),
    ('square_integer', '2d', 'integer', [(3, -4), (4, -4), (3, -3), (4, -3)]),
]
FALLBACKS = [
    ('fallback_nonsquare', '2d', '', [(0, 0), (2, 0), (0, 3), (-4, 1)]),
    ('fallback_duplicate', '2d', '', [(0, 0), (1, 0), (0, 1), (0, 1)]),
    ('fallback_sparse', '2d', 'sparse', [(0, 0), (1, 0), (0, 1), (1, 1)]),
]
CASES = SQUARES + FALLBACKS
# Fallbacks keep ConstOffsets: one gather per DISTINCT offset (RADV's NIR CSE merges the
# duplicate's two identical split gathers, so that case is 3, not 4).
EXPECTED_HW = {name: 1 for name, *_ in SQUARES} | {name: len(set(o)) for name, _, _, o in FALLBACKS}
assert [EXPECTED_HW[n] for n, *_ in FALLBACKS] == [4, 3, 4]

# The model itself must catch a wrong swizzle (x and y swapped), or it proves nothing.
try:
    check_values('self-test', [(0, 0), (1, 0), (0, 1), (1, 1)], ('ConstOffset', (0, 0), [3, 2, 1, 0]))
    raise SystemExit('gather model accepted a wrong swizzle')
except AssertionError:
    pass

# ---------------------------------------------------------------- production text


def block(text, start, end='\n}\n'):
    i = text.index(start)
    return text[i:text.index(end, i) + len(end)]


operands_class = block(image_cpp, 'class ImageOperands {', '\n};\n')
ptp_ctor = operands_class[operands_class.index('ImageOperands(EmitContext& ctx'):]
ptp_ctor = ptp_ctor[ptp_ctor.index('offset2'):]
ptp_ctor = ptp_ctor[:ptp_ctor.index('\n    }\n')]
gather_fn = block(image_cpp, 'Id EmitImageGather(')
gather_dref_fn = block(image_cpp, 'Id EmitImageGatherDref(')
emit_tmpl = block(image_cpp, 'template <typename MethodPtrType, typename... Args>\nId Emit(')
decorate_fn = block(image_cpp, 'Id Decorate(EmitContext& ctx, IR::Inst* inst, Id sample)')


def source_model():
    """What the production PTP branch emits for each case (model of the C++)."""
    immediate_tail = ptp_ctor.split('throw LogicError("Invalid PTP arguments");', 1)[1]
    adds = re.findall(r'Add\(spv::ImageOperandsMask::(\w+)', immediate_tail)
    table = re.search(r'GATHER_SQUARE_COMPONENT\{([^}]*)\}', operands_class)
    forms = {}
    for name, kind, flags, offsets in CASES:
        if 'ConstOffset' not in adds:
            # Main: an immediate PTP has one output, the four-offset array.
            assert adds == ['ConstOffsets'], adds
            forms[name] = ('ConstOffsets', offsets)
            continue
        assert table, 'branch emits ConstOffset for PTP but has no component table'
        component = [int(c) for c in table.group(1).split(',')]
        assert 'GetSparseFromOp' in operands_class and 'TextureType::Color2D' in operands_class \
            and 'TextureType::ColorArray2D' in operands_class, 'fallback guards missing'
        cx, cy = min(o[0] for o in offsets), min(o[1] for o in offsets)
        cells = [(o[0] - cx) + 2 * (o[1] - cy) for o in offsets]
        square = (all(0 <= o[0] - cx <= 1 and 0 <= o[1] - cy <= 1 for o in offsets)
                  and len(set(cells)) == 4)
        if square and 'sparse' not in flags and kind in ('2d', '2d_array'):
            forms[name] = ('ConstOffset', (cx, cy), [component[c] for c in cells])
        else:
            forms[name] = ('ConstOffsets', offsets)
    return forms


def hw_gathers(form):
    # Pinned RADV: lower_tg4_offsets turns ConstOffsets into one tg4 per offset (CSE then
    # merges identical ones); ACO selects one image_gather4* per tg4 (G4 proof,
    # nir_lower_tex.c:1174-1225).
    return len(set(form[1])) if form[0] == 'ConstOffsets' else 1


def check_forms(forms, origin):
    for name, kind, flags, offsets in CASES:
        check_values(name, offsets, forms[name])
    counts = {name: hw_gathers(forms[name]) for name, *_ in CASES}
    wrong = {n: (counts[n], EXPECTED_HW[n]) for n in counts if counts[n] != EXPECTED_HW[n]}
    assert not wrong, (f'{origin}: image_gather4 count (got, want) per case: {wrong}. '
                       'An admissible 2x2 PTP square must be ONE hardware gather on the pinned RADV')
    return counts


if source_only:
    forms = source_model()
    check_forms(forms, 'source model')
    print('PASS (source model): every square emits ConstOffset at its corner + a shuffle whose '
          'values match ConstOffsets; fallbacks keep ConstOffsets')
    print('source-only: C++ NOT compiled, pinned RADV NOT run')
    sys.exit(0)

assert platform.system() == 'Linux', 'compiled check is Linux/dedie only'
build = root / 'build/nx2-tests'
build.mkdir(parents=True, exist_ok=True)


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def fetch(url, dest, digest, algo):
    if not dest.exists() or getattr(hashlib, algo)(dest.read_bytes()).hexdigest() != digest:
        data = urllib.request.urlopen(url, timeout=120).read()
        assert getattr(hashlib, algo)(data).hexdigest() == digest, f'{url}: {algo} mismatch'
        dest.write_bytes(data)
    return dest


def unpack(archive, dest):
    if not dest.exists():
        tmp = Path(tempfile.mkdtemp(dir=dest.parent))
        with tarfile.open(archive) as t:
            t.extractall(tmp, filter='data')
        (only,) = tmp.iterdir()
        only.rename(dest)
        tmp.rmdir()
    return dest


def cpm_package(name):
    """Sirit / SPIRV-Headers at the tree's cpmfile.json pins (Eden's CPM cache if present)."""
    pkg = json.loads((source / 'cpmfile.json').read_text())[name]
    cached = sorted((source / '.cache/cpm' / name).glob('*/include')) if (source / '.cache/cpm').exists() else []
    if cached:
        return cached[0].parent
    deps = build / 'g4-deps'
    deps.mkdir(exist_ok=True)
    url = f"https://github.com/{pkg['repo']}/archive/refs/tags/{pkg['version']}.tar.gz"
    archive = fetch(url, deps / f"{name}-{pkg['version']}.tar.gz", pkg['hash'], 'sha512')
    return unpack(archive, deps / f"{name}-{pkg['version']}")


sirit = cpm_package('sirit')
headers = cpm_package('spirv-headers')
context_h = (src / 'shader_recompiler/backend/spirv/spirv_emit_context.h').read_text()
const_helpers = context_h[context_h.index('    Id Const(u32 value) {'):context_h.index('    const Profile& profile;')]

harness = r'''
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <initializer_list>
#include <optional>
#include <span>
#include <stdexcept>
#include <string>
#include <vector>
#include <sirit/sirit.h>
using u32 = std::uint32_t; using s32 = std::int32_t; using f32 = float; using u64 = std::uint64_t;
// boost::container::static_vector<Id, 4> as ImageOperands uses it.
namespace boost::container {
template <typename T, std::size_t N> struct static_vector {
    std::array<T, N> v{}; std::size_t n{};
    static_vector() = default;
    static_vector(std::initializer_list<T> l) { for (const T& x : l) push_back(x); }
    void push_back(const T& x) { if (n == N) std::abort(); v[n++] = x; }
    const T* data() const { return v.data(); } std::size_t size() const { return n; }
    bool empty() const { return n == 0; }
};
}
#define LOG_WARNING(...) std::fprintf(stderr, "LOG_WARNING\n")
struct LogicError : std::logic_error { using std::logic_error::logic_error; };
namespace Shader {
enum class TextureType : u32 { Color1D, ColorArray1D, Color2D, ColorArray2D, Color3D, ColorCube,
                               ColorArrayCube, Buffer, Color2DRect };
template <typename T> struct Field { T v{}; T Value() const { return v; } operator T() const { return v; } };
namespace IR {
enum class Opcode { CompositeConstructU32x2, CompositeConstructU32x3, CompositeConstructU32x4,
                    GetSparseFromOp, Other };
struct TextureInstInfo {
    u32 descriptor_index{}; Field<TextureType> type{}; u32 is_depth{}; u32 relaxed_precision{};
    u32 gather_component{}; u32 is_integer{};
};
struct Inst;
struct Value {
    Inst* inst{}; std::optional<u32> imm{};
    bool IsEmpty() const { return !inst && !imm; }
    bool IsImmediate() const { return imm.has_value(); }
    u32 U32() const { if (!imm) std::abort(); return *imm; }
    Inst* InstRecursive() const { if (!inst) std::abort(); return inst; }
};
struct Inst {
    Opcode op{Opcode::Other}; std::vector<Value> args; TextureInstInfo info{};
    Inst* sparse{}; Sirit::Id definition{}; bool defined{}; bool invalid{};
    bool AreAllArgsImmediates() const {
        return std::all_of(args.begin(), args.end(), [](const Value& a) { return a.IsImmediate(); });
    }
    Opcode GetOpcode() const { return op; }
    Value Arg(std::size_t i) const { return args.at(i); }
    template <typename T> T Flags() const { return info; }
    Inst* GetAssociatedPseudoOperation(Opcode o) { return o == Opcode::GetSparseFromOp ? sparse : nullptr; }
    void SetDefinition(Sirit::Id id) { definition = id; defined = true; }
    void Invalidate() { invalid = true; }
};
} // namespace IR
namespace Backend::SPIRV {
using Sirit::Id;
struct Profile { bool need_gather_subpixel_offset{}; };
struct TextureDefinition { Id id; Id sampled_type; bool is_integer; };
class EmitContext : public Sirit::Module {
public:
    EmitContext() : Sirit::Module(0x00010300) {
        U1 = TypeBool();
        U32[1] = TypeInt(32, false); S32[1] = TypeInt(32, true); F32[1] = TypeFloat(32);
        for (u32 n = 2; n <= 4; ++n) {
            U32[n] = TypeVector(U32[1], n); S32[n] = TypeVector(S32[1], n); F32[n] = TypeVector(F32[1], n);
        }
    }
    Id Def(const IR::Value&) { std::abort(); }
    std::array<Id, 5> U32{}, S32{}, F32{};
    Id U1{};
    Profile profile{};
    std::vector<TextureDefinition> textures;
@@CONST_HELPERS@@
};
bool IsTextureInteger(EmitContext& ctx, const IR::TextureInstInfo& info) {
    return ctx.textures.at(info.descriptor_index).is_integer;
}
Id Texture(EmitContext& ctx, IR::TextureInstInfo info, const IR::Value&) {
    const TextureDefinition& def{ctx.textures.at(info.descriptor_index)};
    return ctx.OpLoad(def.sampled_type, def.id);
}
Id TextureImage(EmitContext&, IR::TextureInstInfo, const IR::Value&) { std::abort(); }
Id ImageGatherSubpixelOffset(EmitContext&, const IR::TextureInstInfo&, Id, Id) { std::abort(); }

// ---- production code, extracted verbatim from emit_spirv_image.cpp ----
@@PRODUCTION@@
// ---- end of production code ----

struct Case { const char* name; bool array; bool dref; bool integer; bool sparse; std::array<s32, 8> ptp; };

std::vector<u32> Build(const Case& c) {
    EmitContext ctx;
    ctx.AddCapability(spv::Capability::Shader);
    ctx.AddCapability(spv::Capability::ImageGatherExtended);
    if (c.sparse) ctx.AddCapability(spv::Capability::SparseResidency);
    const Id void_type{ctx.TypeVoid()};
    const Id sampled{c.integer ? ctx.U32[1] : ctx.F32[1]};
    const Id image_type{ctx.TypeImage(sampled, spv::Dim::Dim2D, c.dref ? 1 : 0, c.array, false, 1,
                                      spv::ImageFormat::Unknown)};
    const Id sampled_image{ctx.TypeSampledImage(image_type)};
    const Id texture{ctx.AddGlobalVariable(ctx.TypePointer(spv::StorageClass::UniformConstant, sampled_image),
                                           spv::StorageClass::UniformConstant)};
    ctx.Decorate(texture, spv::Decoration::DescriptorSet, 0U);
    ctx.Decorate(texture, spv::Decoration::Binding, 0U);
    ctx.textures.push_back({texture, sampled_image, c.integer});
    const Id runtime_array{ctx.TypeRuntimeArray(ctx.F32[4])};
    ctx.Decorate(runtime_array, spv::Decoration::ArrayStride, 16U);
    const Id block{ctx.TypeStruct(runtime_array)};
    ctx.Decorate(block, spv::Decoration::Block);
    ctx.MemberDecorate(block, 0, spv::Decoration::Offset, 0U);
    const Id ssbo{ctx.AddGlobalVariable(ctx.TypePointer(spv::StorageClass::StorageBuffer, block),
                                        spv::StorageClass::StorageBuffer)};
    ctx.Decorate(ssbo, spv::Decoration::DescriptorSet, 0U);
    ctx.Decorate(ssbo, spv::Decoration::Binding, 1U);
    const Id gid{ctx.AddGlobalVariable(ctx.TypePointer(spv::StorageClass::Input, ctx.U32[3]),
                                       spv::StorageClass::Input)};
    ctx.Decorate(gid, spv::Decoration::BuiltIn, spv::BuiltIn::GlobalInvocationId);

    const Id main{ctx.OpFunction(void_type, spv::FunctionControlMask::MaskNone, ctx.TypeFunction(void_type))};
    ctx.AddLabel();
    const Id id3{ctx.OpLoad(ctx.U32[3], gid)};
    const Id x{ctx.OpCompositeExtract(ctx.U32[1], id3, 0U)};
    const Id scale{ctx.Constant(ctx.F32[1], 1.0f / 1024.0f)};
    const Id u{ctx.OpFMul(ctx.F32[1], ctx.OpConvertUToF(ctx.F32[1], x), scale)};
    const Id v{ctx.OpFMul(ctx.F32[1], ctx.OpConvertUToF(ctx.F32[1], ctx.OpCompositeExtract(ctx.U32[1], id3, 1U)), scale)};
    const Id coords{c.array ? ctx.OpCompositeConstruct(ctx.F32[3], u, v, ctx.Constant(ctx.F32[1], 2.0f))
                            : ctx.OpCompositeConstruct(ctx.F32[2], u, v)};

    IR::Inst ptp0{IR::Opcode::CompositeConstructU32x4}, ptp1{IR::Opcode::CompositeConstructU32x4};
    for (int i = 0; i < 4; ++i) {
        ptp0.args.push_back(IR::Value{nullptr, static_cast<u32>(c.ptp[i])});
        ptp1.args.push_back(IR::Value{nullptr, static_cast<u32>(c.ptp[4 + i])});
    }
    IR::Inst sparse_op{IR::Opcode::GetSparseFromOp};
    IR::Inst gather_inst;
    gather_inst.info.descriptor_index = 0;
    gather_inst.info.type.v = c.array ? TextureType::ColorArray2D : TextureType::Color2D;
    gather_inst.info.is_depth = c.dref;
    gather_inst.info.gather_component = 1;
    if (c.sparse) gather_inst.sparse = &sparse_op;
    const IR::Value index{nullptr, 0U};
    Id color{c.dref ? EmitImageGatherDref(ctx, &gather_inst, index, coords, IR::Value{&ptp0}, IR::Value{&ptp1},
                                          ctx.Constant(ctx.F32[1], 0.5f))
                    : EmitImageGather(ctx, &gather_inst, index, coords, IR::Value{&ptp0}, IR::Value{&ptp1})};
    if (c.sparse) {
        if (!sparse_op.invalid || !sparse_op.defined) std::abort();
        const Id zero{ctx.Constant(ctx.F32[1], 0.0f)};
        color = ctx.OpSelect(ctx.F32[4], ctx.OpCompositeConstruct(ctx.TypeVector(ctx.U1, 4), sparse_op.definition,
                                                                  sparse_op.definition, sparse_op.definition,
                                                                  sparse_op.definition),
                             color, ctx.ConstantComposite(ctx.F32[4], zero, zero, zero, zero));
    }
    const Id element{ctx.OpAccessChain(ctx.TypePointer(spv::StorageClass::StorageBuffer, ctx.F32[4]), ssbo,
                                       ctx.Const(0U), x)};
    ctx.OpStore(element, color);
    ctx.OpReturn();
    ctx.OpFunctionEnd();
    ctx.AddEntryPoint(spv::ExecutionModel::GLCompute, main, "main", gid);
    ctx.AddExecutionMode(main, spv::ExecutionMode::LocalSize, 64U, 1U, 1U);
    return ctx.Assemble();
}
} // namespace Backend::SPIRV
} // namespace Shader

int main(int argc, char** argv) {
    using namespace Shader::Backend::SPIRV;
    const Case cases[] = {
@@CASES@@
    };
    for (const Case& c : cases) {
        const std::vector<u32> words{Build(c)};
        std::ofstream(std::string(argv[1]) + "/" + c.name + ".spv", std::ios::binary)
            .write(reinterpret_cast<const char*>(words.data()), words.size() * 4);
    }
    (void)argc;
    return 0;
}
'''
case_rows = []
for name, kind, flags, offsets in CASES:
    flat = ', '.join(str(c) for o in offsets for c in o)
    case_rows.append(f'        {{"{name}", {str(kind == "2d_array").lower()}, {str("dref" in flags).lower()}, '
                     f'{str("integer" in flags).lower()}, {str("sparse" in flags).lower()}, {{{flat}}}}},')
production = '\n'.join((operands_class, decorate_fn, emit_tmpl, gather_fn, gather_dref_fn))
harness = (harness.replace('@@CONST_HELPERS@@', const_helpers).replace('@@PRODUCTION@@', production)
           .replace('@@CASES@@', '\n'.join(case_rows)))

work = Path(tempfile.mkdtemp(prefix='tld4-ptp-square-', dir=build))
cxx = shutil.which('clang++-18') or shutil.which('g++')
exe = work / 'emit'
(work / 'harness.cpp').write_text(harness)
# Sirit (v1.0.5 and v1.0.7) reserves 6 + n words for OpImageSparse[Dref]Gather but writes
# 8 + n with image operands: the last operand lands past the stream's end and the next
# Reserve zeroes it (ConstOffsets becomes %0). Pre-existing, outside this layer (sparse
# keeps main's path). Fix only this harness's copy, so the sparse fallback is valid SPIR-V
# that the pinned RADV can count; _GLIBCXX_ASSERTIONS traps any other overrun.
sirit = shutil.copytree(sirit, work / 'sirit')
image_ops = (sirit / 'src/instructions/image.cpp').read_text()
for op in ('OpImageSparseGather', 'OpImageSparseDrefGather'):
    body = image_ops[image_ops.index(f'Id Module::{op}('):]
    body = body[:body.index('\n}\n')]
    assert body.count('code->Reserve(6 + operands.size());') == 1, f'Sirit {op} changed: review the workaround'
    image_ops = image_ops.replace(body, body.replace('Reserve(6 + operands', 'Reserve(8 + operands'))
(sirit / 'src/instructions/image.cpp').write_text(image_ops)
sirit_sources = [str(sirit / 'src/sirit.cpp'), str(sirit / 'src/stream.cpp')] + sorted(
    str(p) for p in (sirit / 'src/instructions').glob('*.cpp'))
run([cxx, '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
     '-D_GLIBCXX_ASSERTIONS',
     '-I', str(sirit / 'include'), '-I', str(sirit / 'src'), '-I', str(headers / 'include'),
     str(work / 'harness.cpp'), *sirit_sources, '-o', str(exe)])
spv = work / 'spv'
spv.mkdir()
run([str(exe), str(spv)])
print(f'emit harness ({Path(cxx).name}, ASan/UBSan): {len(CASES)} SPIR-V modules from the production emitter')

# ---------------------------------------------------------------- 1. values from the SPIR-V


def parse_spirv(path):
    text = subprocess.run(['spirv-dis', '--raw-id', str(path)], check=True, capture_output=True,
                          text=True).stdout
    defs, uses = {}, []
    for line in text.splitlines():
        m = re.match(r'\s*(%\d+) = (Op\w+)\s*(.*)', line)
        if m:
            defs[m.group(1)] = (m.group(2), m.group(3).split())
            uses.append((m.group(1), m.group(2), m.group(3).split()))
    return text, defs, uses


def const_value(defs, i):
    op, ops = defs[i]
    if op == 'OpConstant':
        return int(ops[1])
    assert op == 'OpConstantComposite', (i, op)
    return tuple(const_value(defs, x) for x in ops[1:])


forms = {}
for name, kind, flags, offsets in CASES:
    path = spv / f'{name}.spv'
    if shutil.which('spirv-val'):
        run(['spirv-val', '--target-env', 'vulkan1.2', str(path)])
    text, defs, uses = parse_spirv(path)
    gathers = [(r, op, ops) for r, op, ops in uses if re.fullmatch(r'OpImage(Sparse)?(Dref)?Gather', op)]
    assert len(gathers) == 1, (name, 'SPIR-V gathers', len(gathers))
    result, op, ops = gathers[0]
    if 'ConstOffsets' in ops:
        form = ('ConstOffsets', list(const_value(defs, ops[ops.index('ConstOffsets') + 1])))
    else:
        corner = const_value(defs, ops[ops.index('ConstOffset') + 1])
        value = result
        if 'Sparse' in op:
            value = next(r for r, o, x in uses if o == 'OpCompositeExtract' and x[1] == result)
        shuffles = [x for r, o, x in uses if o == 'OpVectorShuffle' and x[1] == value]
        form = ('ConstOffset', corner, [int(k) for k in shuffles[0][3:]] if shuffles else None)
    forms[name] = form
    check_values(name, offsets, form)
print('VALUE: emitted gather operands + shuffles equal the guest ConstOffsets texels for every case')

# ---------------------------------------------------------------- 2. pinned RADV ISA

COMPILE_PIPELINE = r'''
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <vulkan/vulkan.h>
#define CHECK(x) do { VkResult r_ = (x); if (r_ != VK_SUCCESS) { fprintf(stderr, "%s -> %d\n", #x, r_); exit(1); } } while (0)
int main(int argc, char **argv) {
   void *lib = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
   if (!lib) { fprintf(stderr, "%s\n", dlerror()); return 1; }
   PFN_vkGetInstanceProcAddr gipa = (PFN_vkGetInstanceProcAddr)dlsym(lib, "vk_icdGetInstanceProcAddr");
   PFN_vkCreateInstance createInstance = (PFN_vkCreateInstance)gipa(NULL, "vkCreateInstance");
   VkApplicationInfo app = { VK_STRUCTURE_TYPE_APPLICATION_INFO, .apiVersion = VK_API_VERSION_1_3 };
   VkInstanceCreateInfo ici = { VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo = &app };
   VkInstance inst; CHECK(createInstance(&ici, NULL, &inst));
   PFN_vkEnumeratePhysicalDevices enumerate = (PFN_vkEnumeratePhysicalDevices)gipa(inst, "vkEnumeratePhysicalDevices");
   PFN_vkGetPhysicalDeviceProperties props_fn = (PFN_vkGetPhysicalDeviceProperties)gipa(inst, "vkGetPhysicalDeviceProperties");
   PFN_vkCreateDevice createDevice = (PFN_vkCreateDevice)gipa(inst, "vkCreateDevice");
   PFN_vkGetDeviceProcAddr gdpa = (PFN_vkGetDeviceProcAddr)gipa(inst, "vkGetDeviceProcAddr");
   uint32_t n = 1; VkPhysicalDevice pd; CHECK(enumerate(inst, &n, &pd));
   VkPhysicalDeviceProperties props; props_fn(pd, &props);
   fprintf(stderr, "DEVICE: %s\n", props.deviceName);
   float prio = 1.0f;
   VkDeviceQueueCreateInfo qci = { VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO, .queueCount = 1, .pQueuePriorities = &prio };
   VkDeviceCreateInfo dci = { VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO, .queueCreateInfoCount = 1, .pQueueCreateInfos = &qci };
   VkDevice dev; CHECK(createDevice(pd, &dci, NULL, &dev));
   PFN_vkCreateDescriptorSetLayout cdsl = (PFN_vkCreateDescriptorSetLayout)gdpa(dev, "vkCreateDescriptorSetLayout");
   PFN_vkCreatePipelineLayout cpl = (PFN_vkCreatePipelineLayout)gdpa(dev, "vkCreatePipelineLayout");
   PFN_vkCreateShaderModule csm = (PFN_vkCreateShaderModule)gdpa(dev, "vkCreateShaderModule");
   PFN_vkCreateComputePipelines ccp = (PFN_vkCreateComputePipelines)gdpa(dev, "vkCreateComputePipelines");
   VkDescriptorSetLayoutBinding b[2] = {
      { 0, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 1, VK_SHADER_STAGE_COMPUTE_BIT, NULL },
      { 1, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, NULL } };
   VkDescriptorSetLayoutCreateInfo dslci = { VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO, .bindingCount = 2, .pBindings = b };
   VkDescriptorSetLayout dsl; CHECK(cdsl(dev, &dslci, NULL, &dsl));
   VkPipelineLayoutCreateInfo plci = { VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, .setLayoutCount = 1, .pSetLayouts = &dsl };
   VkPipelineLayout pl; CHECK(cpl(dev, &plci, NULL, &pl));
   FILE *f = fopen(argv[2], "rb"); if (!f) return 1;
   fseek(f, 0, SEEK_END); long size = ftell(f); fseek(f, 0, SEEK_SET);
   void *code = malloc(size); if (fread(code, 1, size, f) != (size_t)size) return 1; fclose(f);
   VkShaderModuleCreateInfo smci = { VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = size, .pCode = code };
   VkShaderModule sm; CHECK(csm(dev, &smci, NULL, &sm));
   VkComputePipelineCreateInfo cpci = { VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO,
      .stage = { VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_COMPUTE_BIT, .module = sm, .pName = "main" },
      .layout = pl };
   VkPipeline p; CHECK(ccp(dev, VK_NULL_HANDLE, 1, &cpci, NULL, &p));
   free(code);
   return 0;
}
'''

GS_COMPUTE_STUBS = r'''/* Host build only: the PS5 GS-as-compute entry points (radv_gs_compute.c needs the ps5
 * winsys and mesa-clc). Compute pipelines never need them. */
#include <stdlib.h>
int radv_gs_compute_wanted(void);
int radv_gs_compute_wanted(void) { return 0; }
#define STUB(n) void n(void); void n(void) { abort(); }
STUB(radv_gs_compute_compile) STUB(radv_gs_compute_deferred_vs_create) STUB(radv_gs_compute_deferred_vs_destroy)
STUB(radv_gs_compute_deferred_vs_get) STUB(radv_gs_compute_get_meta_pipeline) STUB(radv_gs_compute_lower_sysvals)
STUB(radv_gs_compute_lower_tcs) STUB(radv_gs_compute_lower_tes) STUB(radv_gs_compute_lower_vs)
STUB(radv_gs_compute_split) STUB(radv_gs_compute_split_gs)
'''


def offline_radv():
    """Host RADV from the pinned Mesa: amdgpu winsys + noop drm-shim; compiler sources as pinned."""
    pin = next(i['commit'] for i in json.loads((root / 'tools/deps.json').read_text())['items']
               if i['name'] == 'ps5-mesa')
    if os.environ.get('G4_RADV_OFFLINE'):
        out = Path(os.environ['G4_RADV_OFFLINE'])
        assert (out / 'REVISION').read_text().strip() == pin, 'G4_RADV_OFFLINE is not the pinned Mesa'
        return out
    out = build / f'radv-offline-{pin[:12]}'
    if (out / 'REVISION').exists():
        return out
    mesa_fork = Path(os.environ.get('PS5_MESA_FORK', root.parent / 'mihawk-mesa-review'))
    # The checkout may be a bind-mount owned by another user (typical on dedie).
    git_env = dict(os.environ, GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='safe.directory',
                   GIT_CONFIG_VALUE_0=str(mesa_fork))
    head = subprocess.run(['git', '-C', str(mesa_fork), 'rev-parse', 'HEAD'], check=True,
                          capture_output=True, text=True, env=git_env).stdout.strip()
    assert head == pin, f'{mesa_fork} is at {head}, deps.json pins ps5-mesa {pin}'
    work_dir = Path(tempfile.mkdtemp(prefix='radv-offline-', dir=build))
    mesa = work_dir / 'mesa'
    mesa.mkdir()
    archive = subprocess.run(['git', '-C', str(mesa_fork), 'archive', pin], check=True,
                             capture_output=True, env=git_env).stdout
    run(['tar', '-x', '-C', str(mesa)], input=archive)
    vulkan = mesa / 'src/amd/vulkan'
    (vulkan / 'host_gs_compute_stubs.c').write_text(GS_COMPUTE_STUBS)
    meson_build = (vulkan / 'meson.build').read_text()
    anchor = 'radv_link_with = []\n'
    assert meson_build.count(anchor) == 1
    (vulkan / 'meson.build').write_text(meson_build.replace(
        anchor, anchor + "if not with_radv_ps5\n  libradv_files += files('host_gs_compute_stubs.c')\nendif\n"))
    wrap = (mesa / 'subprojects/libdrm.wrap').read_text()
    url = re.search(r'source_url = (\S+)', wrap).group(1)
    digest = re.search(r'source_hash = (\S+)', wrap).group(1)
    drm = unpack(fetch(url, work_dir / Path(url).name, digest, 'sha256'), work_dir / 'libdrm')
    prefix = out / 'drm'
    run(['meson', 'setup', str(work_dir / 'drm-build'), str(drm), f'--prefix={prefix}', '--libdir=lib',
         '-Damdgpu=enabled', '-Dradeon=disabled', '-Dintel=disabled', '-Dnouveau=disabled',
         '-Dvmwgfx=disabled', '-Domap=disabled', '-Dexynos=disabled', '-Dfreedreno=disabled',
         '-Dtegra=disabled', '-Dvc4=disabled', '-Detnaviv=disabled', '-Dcairo-tests=disabled',
         '-Dman-pages=disabled', '-Dvalgrind=disabled', '-Dtests=false', '-Dudev=false'],
        stdout=subprocess.DEVNULL)
    run(['ninja', '-C', str(work_dir / 'drm-build'), 'install'], stdout=subprocess.DEVNULL)
    env = dict(os.environ, PKG_CONFIG_PATH=str(prefix / 'lib/pkgconfig'))
    run(['meson', 'setup', str(work_dir / 'build'), str(mesa), '-Dbuildtype=debugoptimized', '-Db_ndebug=true',
         '-Dvulkan-drivers=amd', '-Dgallium-drivers=', '-Dplatforms=', '-Dtools=drm-shim',
         '-Dllvm=disabled', '-Damd-use-llvm=false', '-Dvideo-codecs=', '-Dglx=disabled', '-Degl=disabled',
         '-Dgbm=disabled', '-Dopengl=false', '-Dgles1=disabled', '-Dgles2=disabled', '-Dvalgrind=disabled',
         '-Dlibunwind=disabled', '-Dzstd=disabled', '-Dxmlconfig=disabled', '-Dbuild-tests=false',
         '-Dvulkan-layers=', '-Dshader-cache=disabled'], env=env, stdout=subprocess.DEVNULL)
    run(['ninja', '-C', str(work_dir / 'build'), f'-j{os.environ.get("RADV_BUILD_JOBS", "6")}',
         'src/amd/vulkan/libvulkan_radeon.so', 'src/amd/drm-shim/libamdgpu_noop_drm_shim.so'],
        env=env, stdout=subprocess.DEVNULL)
    shutil.copy2(work_dir / 'build/src/amd/vulkan/libvulkan_radeon.so', out)
    shutil.copy2(work_dir / 'build/src/amd/drm-shim/libamdgpu_noop_drm_shim.so', out)
    shutil.copytree(mesa / 'include', out / 'include')
    (out / 'REVISION').write_text(pin + '\n')
    shutil.rmtree(work_dir)
    return out


radv = offline_radv()
tool = work / 'compile_pipeline'
(work / 'compile_pipeline.c').write_text(COMPILE_PIPELINE)
cc = shutil.which('gcc')  # shared ASan runtime, preloaded ahead of the drm-shim
run([cc, '-std=c11', '-O1', '-g', '-fsanitize=address,undefined', '-I', str(radv / 'include'),
     str(work / 'compile_pipeline.c'), '-ldl', '-o', str(tool)])
asan_rt = subprocess.run([cc, '-print-file-name=libasan.so'], check=True, capture_output=True,
                         text=True).stdout.strip()
assert os.path.isabs(asan_rt), asan_rt
env = dict(os.environ, AMDGPU_GPU_ID='navi21', RADV_DEBUG='shaders,nocache',
           LD_LIBRARY_PATH=str(radv / 'drm/lib'),
           LD_PRELOAD=f'{asan_rt}:{radv / "libamdgpu_noop_drm_shim.so"}',
           ASAN_OPTIONS='detect_leaks=0')
counts = {}
dumps = work / 'isa'
dumps.mkdir()
for name, *_ in CASES:
    out = subprocess.run([str(tool), str(radv / 'libvulkan_radeon.so'), str(spv / f'{name}.spv')],
                         env=env, capture_output=True, text=True)
    (dumps / f'{name}.txt').write_text(out.stdout + out.stderr)
    assert out.returncode == 0, (name, out.stderr[-2000:])
    assert 'DEVICE:' in out.stderr and 'NAVI21' in out.stderr, (name, 'not the navi21 (GFX10.3) device')
    hw = (out.stdout + out.stderr).split('After lowering to hw instructions:')
    assert len(hw) == 2, (name, 'no ACO hw instruction dump')
    gathers = re.findall(r'= (image_gather4\w*)', hw[1])
    counts[name] = len(gathers)
    print(f'  {name:<24} {forms[name][0]:<12} hw: {len(gathers)} {" ".join(gathers)}')
wrong = {n: (counts[n], EXPECTED_HW[n]) for n in counts if counts[n] != EXPECTED_HW[n]}
assert not wrong, (f'pinned RADV (navi21) image_gather4 count (got, want): {wrong}; ISA in {dumps}. '
                   'An admissible 2x2 PTP square must be ONE hardware gather')
# The SPIR-V shape alone is not the criterion (both shapes are one OpImageGather), but the
# fallbacks must still be main's ConstOffsets path, and the squares the single gather.
for name, *_ in CASES:
    assert (forms[name][0] == 'ConstOffset') == (EXPECTED_HW[name] == 1 and name.startswith('square')), (
        name, 'squares emit ConstOffset + shuffle; fallbacks keep ConstOffsets', forms[name])
print(f'PASS: pinned RADV {radv.name} (navi21/GFX10.3): squares 1 image_gather4, fallbacks one per distinct offset; ISA in {dumps}')
shutil.rmtree(spv)
