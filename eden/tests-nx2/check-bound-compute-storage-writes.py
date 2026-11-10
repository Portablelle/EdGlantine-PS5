"""UB-135: conservative compute storage write marks; bindings keep their full read size.

Linux/dedie: python3 eden/tests-nx2/check-bound-compute-storage-writes.py [SOURCE_DIR]
Add --source-only for wiring checks and a faithful dispatch/segment decision model, no compiler.
The compiled fixture extracts the production extent analysis, address tracking, resolver and mark
calculation; minimal IR nodes replace the emitter. UBSan covers the reviewed Scale overflow.
Negative control: run this SAME script against prepared main af9e7e3 WITHOUT 99zzzzb (115 layers).
It fails by behavior: a 256-byte store still marks the whole 8 MiB binding, including source-only.
"""
from pathlib import Path
import os
import platform
import re
import subprocess
import sys

args = [a for a in sys.argv[1:] if not a.startswith('--')]
source_only = '--source-only' in sys.argv[1:]
root = Path(__file__).resolve().parents[1]
source = Path(args[0]).resolve() if args else Path(
    (root / '.local/headless-cache').read_text().strip()) / 'source'
src = source / 'src'
cache = (src / 'video_core/buffer_cache/buffer_cache.h').read_text()
analysis = (src / 'shader_recompiler/ir_opt/global_memory_to_storage_buffer_pass.cpp').read_text()


def function(text, signature):
    start = text.index(signature)
    end = text.index('{', start) + 1
    depth = 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


bind = function(cache, 'void BufferCache<P>::BindComputeStorageBuffer(')
host = function(cache, 'void BufferCache<P>::BindHostComputeStorageBuffers(')
multi = function(cache, 'bool BufferCache<P>::BindMultiRangeStorage(')
bounded = 'compute_storage_write_marks[index]' in host


def resolve(end, local, group, block=(64, 1, 1), grid=(1, 1, 1), guard=None):
    def evaluate(c, ls, gs):
        total = c
        for i in range(3):
            if not block[i]:
                return None
            total += ls[i] * (block[i] - 1)
            if gs[i]:
                if grid is None or not grid[i]:
                    return None
                total += gs[i] * (grid[i] - 1)
            if total > 1 << 62:
                return None
        return total
    if guard:
        value = evaluate(*guard)
        if value is None or value >= 65536:
            return None
    return evaluate(end, local, group)


def mark(extent, *, written=True, native=True, enabled=True, pad=0, size=8 << 20):
    # Main's host path is exactly MarkWrittenBuffer(..., size, true). The new path uses the
    # separately computed mark, preserving StorageBufferBinding and its cached read size.
    if not written:
        return 0
    if not bounded or not native or not enabled or extent is None:
        return size
    return pad + min(size - pad, extent)


small = resolve(4, (4, 0, 0), (0, 0, 0))
assert mark(small) == 256, f'small known store marked {mark(small)} bytes, expected 256'
assert mark(small, pad=13) == 269
assert mark(small, size=128) == 128
assert mark(small, written=False) == 0
assert mark(small, native=False) == 8 << 20
assert mark(small, enabled=False) == 8 << 20
assert mark(None) == 8 << 20
assert mark(resolve(4, (4, 0, 0), (256, 0, 0), grid=None)) == 8 << 20
assert mark(resolve(4, (4, 0, 0), (0, 0, 0), grid=None)) == 256
assert resolve(4, (0, 0, 0), (0, 0, 0), guard=(0, (1024, 0, 0), (0, 0, 0))) == 4
assert resolve(4, (0, 0, 0), (0, 0, 0), guard=(1024, (1024, 0, 0), (0, 0, 0))) is None
# Model spreading the prefix across non-contiguous segments, keeping their full binding sizes.
remaining = 269
marks = []
for size in (128, 256, 512):
    n = min(size, remaining)
    marks.append(n)
    remaining -= n
assert marks == [128, 141, 0]

# Faithful scalar-constant part of IdBound's reviewed exact/inexact decision path.
# The C++ fixture below exercises these same cases in the extracted production analysis.
def sum_bound(lhs, rhs):
    c, exact = lhs
    d, other_exact = rhs
    if (not exact and d < 0) or (not other_exact and c < 0):
        return None
    return c + d, exact and other_exact


def max_bound(lhs, rhs):
    if lhs[0] < 0 or rhs[0] < 0:
        return None
    return max(lhs[0], rhs[0]), False


def scale_bound(value, factor, exact_factor=True):
    c, exact = value
    if factor >= 1 << 32 or (not exact_factor and c < 0):
        return None
    if abs(c) and factor > (1 << 40) // abs(c):
        return None
    return c * factor, exact and exact_factor


for unsafe in (sum_bound((255, False), (-255, True)),
               max_bound((-8192, True), (0, True)),
               scale_bound((-1, True), 255, False),
               scale_bound((-(1 << 33), True), 1 << 31),
               scale_bound((5 * 0x7fffffff, True), 1 << 31)):
    assert unsafe is None and mark(unsafe) == 8 << 20
# The pass clears every extent if any global store remains or any store is unprovable.
def aggregate_model(stores, untracked=False, native=True):
    extents = []
    if native and not untracked:
        for store in stores:
            if store is None:
                return []
            extents.append(store)
    return extents


assert aggregate_model([small]) == [256]
for extents in (aggregate_model([small], untracked=True),
                aggregate_model([small, None]), aggregate_model([small], native=False)):
    assert not extents and mark(None) == 8 << 20

# Wiring assertions supplement the behavior checks; main has already failed above.
for token in ('kepler_compute->IsNativeMode()', 'GetIndirectComputeAddress()',
              'EDEN_NX2_BOUND_COMPUTE_WRITES', "value[0] != '0'", 'binding.size - pad',
              'compute_storage_write_marks[ssbo_index] = ~u32{0}'):
    assert token in bind, token
assert 'MarkWrittenBuffer(binding.buffer_id, binding.device_addr, mark, true)' in host
assert 'if (is_written && mark != 0)' in host
assert 'compute_segments, write_mark_limit' in host
assert 'write_mark_limit -= mark' in multi
assert 'if (grouped) {\n            write_mark_limit = ~u64{0};' in multi
assert 'MarkWrittenBuffer(segment.buffer_id, segment.device_addr, mark)' in multi
assert 'runtime.PushMultiRangeSource(buffer, offset, segment.size)' in multi
for backend, short in [('vulkan', 'vk'), ('opengl', 'gl')]:
    pipeline = (src / f'video_core/renderer_{backend}/{short}_compute_pipeline.cpp').read_text()
    assert 'desc.is_written, desc.write_extent)' in pipeline
for token in ('!info.untracked_writes', 'IsGlobalMemoryWrite(inst) && !bound',
              'if (!extent.bounded) {\n                extents.clear();',
              'env.HasNativeRegisterCopies()', 'start < 0', '!rhs->exact',
              '(!lhs.exact && rhs.c < 0)', 'lhs.c < 0 || rhs.c < 0',
              '(!exact_factor && value.c < 0)', 'CONST_LIMIT) / magnitude'):
    assert token in analysis, token
# Verify this layer has not silently changed the cached binding computation.
assert 'StorageBufferSize(mapped_size, following_word, native_pointer)' in cache
assert 'size = MappedStoragePrefix(gpu_addr, size)' in cache
assert 'cached.map_serial == map_serial && cached.generation == generation' in cache
if source_only:
    print('UB-135 source wiring and dispatch/segment behavior model: PASS (C++ not run)')
    sys.exit(0)
assert platform.system() == 'Linux', 'compiled fixture is Linux/dedie-only'

# Extract production analysis and address tracking, using minimal non-optimizing IR nodes.
track = function(analysis, 'std::optional<LowAddrInfo> TrackLowAddress(')
word = function(analysis, 'std::optional<StorageBufferAddr> CbufWord(')
store_size = function(analysis, 'u32 StoreSize(')
start = analysis.index('struct IdBound {')
end = analysis.index('\n};', analysis.index('class StoreExtentAnalysis', start)) + 3
extent_analysis = analysis[start:end]
ops = sorted({'WriteGlobal32'} | set(re.findall(
    r'IR::Opcode::(\w+)', track + word + store_size + extent_analysis)))
fixture = r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <compare>
#include <cstdint>
#include <cstdlib>
#include <memory>
#include <map>
#include <optional>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include "shader_recompiler/storage_write_extent.h"
using u32 = uint32_t; using u64 = uint64_t; using s32 = int32_t; using s64 = int64_t;
using GPUVAddr = u64;
using Shader::StorageWriteExtent;
using Shader::MergeStorageWriteExtent;
namespace IR {
enum class Type { U32, U64 };
'''
fixture += 'enum class Opcode {' + ','.join(ops) + '};\n'
fixture += r'''
struct Inst;
struct Value {
    Inst* inst = nullptr; u64 value = 0;
    Value() = default;
    Value(u32 v) : value(v) {}
    Value(Inst* p) : inst(p) {}
    bool IsImmediate() const { return !inst; }
    Inst* InstRecursive() const { return inst; }
    auto Type() const -> IR::Type { return IR::Type::U32; }
    u32 U32() const { return static_cast<u32>(value); }
    u64 U64() const { return value; }
};
using U32 = Value; using U64 = Value;
struct Inst {
    Opcode opcode; std::vector<Value> args;
    Opcode GetOpcode() const { return opcode; }
    Value Arg(size_t i) const { return args.at(i); }
    size_t NumArgs() const { return args.size(); }
};
}
struct StorageBufferAddr { u32 index, offset; auto operator<=>(const StorageBufferAddr&) const = default; };
struct LowAddrInfo { IR::U32 value; s32 imm_offset; };
'''
fixture += track + '\n' + word + '\n' + store_size + '\n' + extent_analysis
aggregate_start = analysis.index('    // Inspect guest addresses before rebasing.')
aggregate_end = analysis.index('    for (const StorageBufferAddr& storage_buffer : info.set)',
                               aggregate_start)
aggregate = analysis[aggregate_start:aggregate_end]
fixture += r'''
struct StorageInst { StorageBufferAddr storage_buffer; IR::Inst* inst; };
struct Env { bool native; bool HasNativeRegisterCopies() const { return native; } };
struct Program { std::array<u32, 3> workgroup_size{64, 1, 1}; };
struct Info { bool untracked_writes; std::vector<StorageInst> to_replace; };
bool IsGlobalMemoryWrite(const IR::Inst& inst) {
    return inst.GetOpcode() == IR::Opcode::WriteGlobal32;
}
std::map<StorageBufferAddr, StorageWriteExtent> aggregate(Info info, bool native=true) {
    Env env{native}; Program program;
'''
fixture += aggregate + '\nreturn extents;\n}\n'
# Extract the actual dispatch mark calculation, including the environment override.
calc = bind[bind.index('    u64 mark = binding.size;'):bind.index('    static const bool watching')]
calc = calc[:calc.index('    channel_state->compute_storage_write_marks[ssbo_index]')]
fixture += r'''
struct Dim { u32 v; u32 Value() const { return v; } };
struct Qmd { Dim block_dim_x{64}, block_dim_y{1}, block_dim_z{1},
                  grid_dim_x{1}, grid_dim_y{1}, grid_dim_z{1}; };
struct Engine {
    bool native = true, indirect = false;
    bool IsNativeMode() const { return native; }
    bool GetIndirectComputeAddress() const { return indirect; }
};
struct Memory { u64 pointer = 0x10000; template<class T> T Read(u64) { return pointer; } };
struct Binding { u64 gpu_addr = 0x10000; u32 size = 8 << 20; };
u64 dispatch(const StorageWriteExtent& write_extent, bool native=true, bool indirect=false,
             u32 pad=0, bool is_written=true) {
    Engine engine{native, indirect}; auto* kepler_compute = &engine;
    Memory memory; auto* gpu_memory = &memory; memory.pointer += pad;
    Qmd launch_desc; Binding binding; u64 ssbo_addr = 0;
'''
fixture += calc + '\nreturn is_written ? mark : 0;\n}\n'
fixture += r'''
std::vector<std::unique_ptr<IR::Inst>> nodes;
IR::Value op(IR::Opcode code, std::initializer_list<IR::Value> args) {
    nodes.push_back(std::make_unique<IR::Inst>(IR::Inst{code, args}));
    return IR::Value{nodes.back().get()};
}
IR::Value imm(u32 x) { return IR::Value{x}; }
StorageWriteExtent extent(IR::Value offset) {
    using enum IR::Opcode;
    const auto pointer = op(GetCbufU32, {imm(0), imm(0x170)});
    const auto low = op(IAdd32, {pointer, offset});
    const auto vector = op(CompositeConstructU32x2, {low, imm(0)});
    const auto address = op(PackUint2x32, {vector});
    const auto store = op(WriteGlobal32, {address, imm(0)});
    StoreExtentAnalysis analysis{{0, 0x170}, {64, 1, 1}};
    StorageWriteExtent result{.bounded=true};
    analysis.AddStore(*store.InstRecursive(), result);
    return result;
}
int main(int argc, char**) {
    using enum IR::Opcode;
    const auto tid = op(CompositeExtractU32x3, {op(LocalInvocationId, {}), imm(0)});
    const auto gid = op(CompositeExtractU32x3, {op(WorkgroupId, {}), imm(0)});
    const auto small = extent(op(ShiftLeftLogical32, {tid, imm(2)}));
    const bool enabled = argc == 1;
    assert(small.bounded);
    assert(dispatch(small) == (enabled ? 256 : 8 << 20));
    assert(dispatch(small, true, false, 13) == (enabled ? 269 : 8 << 20));
    assert(dispatch(small, false) == 8 << 20);
    assert(dispatch(small, true, true) == (enabled ? 256 : 8 << 20));
    assert(dispatch(small, true, false, 0, false) == 0);
    assert(dispatch({}) == 8 << 20);
    assert(dispatch(extent(op(ShiftLeftLogical32, {gid, imm(8)})), true, true) == 8 << 20);
    auto expect_full = [](IR::Value offset) { assert(dispatch(extent(offset)) == 8 << 20); };
    // Negative constants, inexact bounds, and both reviewed Scale overflow signs.
    const auto negative = op(ISub32, {tid, imm(8192)});
    expect_full(negative);
    expect_full(op(SelectU32, {imm(1), negative, imm(0)}));
    const auto mask = op(BitwiseAnd32, {tid, imm(255)});
    expect_full(op(ISub32, {mask, imm(255)}));
    for (auto offset : {op(SelectU32, {imm(1), negative, imm(0)}),
                        op(ISub32, {mask, imm(255)})}) {
        expect_full(op(IMul32, {op(BitFieldUExtract, {offset, imm(0), imm(16)}), imm(4)}));
    }
    expect_full(op(ISub32, {imm(65536), mask}));
    expect_full(op(IAdd32, {op(IMul32, {imm(0xffffffff), mask}), imm(65536)}));
    for (bool neg : {false, true}) {
        auto value = tid;
        for (int i=0; i < (neg ? 4 : 5); ++i)
            value = op(IAdd32, {value, imm(neg ? 0x80000000U : 0x7fffffffU)});
        expect_full(op(ShiftLeftLogical32, {value, imm(31)}));
    }
    expect_full(op(IAdd32, {op(ShiftLeftLogical32,
        {op(ISub32, {tid, imm(0x40000000)}), imm(2)}), imm(0x2000)}));
    // All extents disappear if any store remains global or any rewritten store is unprovable.
    const auto good = op(WriteGlobal32, {op(PackUint2x32, {op(CompositeConstructU32x2,
        {op(IAdd32, {op(GetCbufU32, {imm(0), imm(0x170)}), tid}), imm(0)})}), imm(0)});
    const auto unknown = op(WriteGlobal32, {imm(0), imm(0)});
    assert(aggregate({false, {{{0, 0x170}, good.InstRecursive()}}}).size() == 1);
    assert(aggregate({true, {{{0, 0x170}, good.InstRecursive()}}}).empty());
    assert(aggregate({false, {{{0, 0x170}, good.InstRecursive()},
                               {{0, 0x180}, unknown.InstRecursive()}}}).empty());
    assert(aggregate({false, {{{0, 0x170}, good.InstRecursive()}}}, false).empty());
    // Runtime selection among pointers and unknown values never produce an extent.
    expect_full(op(SelectU32, {imm(1), op(GetCbufU32, {imm(0), imm(0x150)}),
                                                   op(GetCbufU32, {imm(0), imm(0x160)})}));
    const auto cycle = op(Phi, {});
    cycle.InstRecursive()->args = {tid, cycle};
    expect_full(cycle);
    auto a = small; MergeStorageWriteExtent(a, {}); assert(!a.bounded);
}
'''
build = root / 'build/nx2-tests'
build.mkdir(parents=True, exist_ok=True)
cpp = build / 'bound-compute-storage-writes.cpp'
exe = build / 'bound-compute-storage-writes'
cpp.write_text(fixture)
if '--emit-fixture' in sys.argv[1:]:
    print(cpp)
    sys.exit(0)
subprocess.run([os.environ.get('CXX', 'clang++-18'), '-std=c++20', '-O1', '-g',
                '-fsanitize=address,undefined', '-I' + str(src), str(cpp), '-o', str(exe)], check=True)
for enabled in (True, False):
    env = dict(os.environ, EDEN_NX2_BOUND_COMPUTE_WRITES='1' if enabled else '0')
    subprocess.run([str(exe)] + ([] if enabled else ['full']), env=env, check=True)
print('UB-135 extracted extent analysis and dispatch write marks: PASS')
