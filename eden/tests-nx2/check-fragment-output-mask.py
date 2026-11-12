"""UB-084 / G5: render target components the fragment shader does not output are not written.

Usage: python3 tests-nx2/check-fragment-output-mask.py [--source-only] [SOURCE_DIR]
SOURCE_DIR contains src/; defaults to the prepared headless cache.

The guest leaves the components of a bound target that its fragment shader does not output
untouched. Vulkan writes undefined values there and AMD writes whatever its export registers
hold (Ocarina of Time: a depth-only draw with RT0 bound left a NaN / red-blue band above the
horizon). The Vulkan write mask must be guest color_mask AND the shader's output components, in
the static pipeline state and in the EDS3 dynamic mask, which must be recorded again when the
bound pipeline outputs other components.

Default (Linux/dedie): extracted verbatim and compiled (ASan/UBSan) with small stubs:
  - the SetFragColor case of VisitUsages (collect_shader_info_pass.cpp);
  - the fragment-output part of the GraphicsPipeline constructor, ColorOutputMask() accessors
    (when present) and the per-attachment write mask of MakePipeline (vk_graphics_pipeline.*);
  - RasterizerVulkan::UpdateBlending up to its colour-mask recording (vk_rasterizer.cpp).
A command script builds pipelines from SetFragColor writes and runs static masks and dynamic
sequences (dirty state, pipeline changes, DrawTexture's null pipeline).
--source-only: the same script runs on a model whose AND, packing, accessor and re-record
conditions are read from the production text.
Both modes: the bare-image-view BlitColor (DrawTexture/DLSS path) followed by a draw of the
previous pipeline is replayed from the production BlitColor, Scheduler::InvalidateState and
Scheduler::UpdateGraphicsPipeline; that pipeline must be bound again with its dynamic mask.

Main fails by behaviour: the mask is the guest mask alone (RGB-only, R-only and depth-only
shaders still write the other components), a pipeline change does not re-record the mask, and
the bare BlitColor leaves the scheduler believing the previous pipeline is still bound.
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
collect = (src / 'shader_recompiler/ir_opt/collect_shader_info_pass.cpp').read_text()
pipeline_cpp = (src / 'video_core/renderer_vulkan/vk_graphics_pipeline.cpp').read_text()
pipeline_h = (src / 'video_core/renderer_vulkan/vk_graphics_pipeline.h').read_text()
rasterizer = (src / 'video_core/renderer_vulkan/vk_rasterizer.cpp').read_text()
blit = (src / 'video_core/renderer_vulkan/blit_image.cpp').read_text()
scheduler_cpp = (src / 'video_core/renderer_vulkan/vk_scheduler.cpp').read_text()
failures = []
phase = ['source model']
R, G, B, A = 1, 2, 4, 8
RGBA = R | G | B | A


def check(condition, message):
    if not condition:
        failures.append(f'[{phase[0]}] {message}')


def block_end(text, open_brace):
    depth, i = 1, open_brace + 1
    while depth:
        depth += (text[i] == '{') - (text[i] == '}')
        i += 1
    return i


def function(text, signature):
    start = text.index(signature)
    return text[start:block_end(text, text.index('{', start))]


def cint(expression, env):
    e = re.sub(r'\b(0x[0-9a-fA-F]+|\d+)[uU]\b', r'\1', expression)
    e = e.replace('~0', '0xFFFFFFFF').replace('&&', ' and ').replace('||', ' or ')
    e = re.sub(r'!(?!=)', ' not ', e)
    return eval(e, {}, env)


# --------------------------------------------------------------------------------------------
# Production pieces.
collect_case = collect[collect.index('    case IR::Opcode::SetFragColor'):]
collect_case = collect_case[:collect_case.index('\n    case IR::Opcode::', 10) + 1]
ctor_start = pipeline_cpp.index('    fragment_has_color0_output = ')
ctor_part = pipeline_cpp[ctor_start:pipeline_cpp.index('\n\n', ctor_start) + 1]
accessors = ''
accessor = re.search(r'    /// Color components of a render target.*?\n    \}\n\n.*?u32 ColorOutputMask\(\) '
                     r'const noexcept \{.*?\n    \}\n', pipeline_h, re.S)
if accessor:
    accessors = accessor[0]
make_pipeline = function(pipeline_cpp, 'void GraphicsPipeline::MakePipeline(')
static_start = make_pipeline.index('        static constexpr std::array mask_table{')
static_mask = make_pipeline[static_start:make_pipeline.index('        cb_attachments.push_back({',
                                                             static_start)]
blending = function(rasterizer, 'void RasterizerVulkan::UpdateBlending(')
blending_mask = blending[:blending.index('    if (state_tracker.TouchBlendEnable()) {')] + '}\n'
blending_signature = blending[:blending.index(') {') + 1].replace('RasterizerVulkan::', '')


# --------------------------------------------------------------------------------------------
# Command script: P id rt:component... | S id index guest | D id common guests... dirty_b dirty_c
SHADERS = {
    'rgb': [(0, 0), (0, 1), (0, 2)],              # RT0 without alpha
    'r_rt1': [(0, 0), (1, 0), (1, 1), (1, 2), (1, 3)],
    'depth': [],                                  # depth-only visibility draw, RT0 still bound
    'rgba': [(0, c) for c in range(4)],
    'ga_rt3': [(3, 1), (3, 3)],
}
components = {name: [sum(1 << c for rt2, c in writes if rt2 == rt) for rt in range(8)]
              for name, writes in SHADERS.items()}
pids = {name: i for i, name in enumerate(SHADERS)}
script = []
for name, writes in SHADERS.items():
    script.append(('P', pids[name], writes))
for name in SHADERS:
    for index in range(8):
        for guest in (RGBA, R | G, B | A, 0):
            script.append(('S', pids[name], index, guest))
full = [RGBA] * 8
mixed = [R | G, RGBA, RGBA, G | A, RGBA, 0, RGBA, RGBA]
# The dirty flags are what Maxwell3D sets for these register changes.
DYNAMIC = [
    # (pipeline, common, guests, dirty blending, dirty colour mask)
    ('rgb', 0, full, True, True),
    ('rgb', 0, full, False, False),        # nothing changed: nothing to record
    ('r_rt1', 0, full, False, False),      # pipeline change alone re-records
    ('depth', 0, full, False, False),
    ('depth', 0, full, False, False),
    (None, 0, full, False, False),         # DrawTexture: full guest mask
    ('rgba', 0, mixed, True, True),        # guest mask clears what the shader writes
    ('ga_rt3', 1, mixed, True, True),      # color_mask_common: RT0's guest mask for all
    ('rgb', 1, mixed, True, False),        # blend change only, pipeline changed
    ('rgb', 0, full, True, True),
]
for name, common, guests, dirty_b, dirty_c in DYNAMIC:
    script.append(('D', -1 if name is None else pids[name], common, guests, dirty_b, dirty_c))


def check_results(results):
    """The dynamic mask in effect (the last one recorded) must be guest AND shader outputs."""
    dynamic = iter(DYNAMIC)
    effective = None
    for command, result in zip(script, results):
        if command[0] == 'S':
            _, pid, index, guest = command
            name = next(n for n, p in pids.items() if p == pid)
            want = guest & components[name][index]
            check(result == want, f'static mask: shader {name} RT{index} guest {guest:04b} -> '
                  f'{result:04b}, expected {want:04b}')
        elif command[0] == 'D':
            name, common, guests, dirty_b, dirty_c = next(dynamic)
            shader = [RGBA] * 8 if name is None else components[name]
            want = [guests[0 if common else i] & shader[i] for i in range(8)]
            effective = result if result is not None else effective
            shown = None if effective is None else [f'{m:04b}' for m in effective]
            check(effective == want, f'dynamic mask: pipeline {name or "null (DrawTexture)"} '
                  f'common={common} dirty blending={dirty_b} colour={dirty_c}: in effect {shown}, '
                  f'expected {[f"{m:04b}" for m in want]}')


# --------------------------------------------------------------------------------------------
# Source model of the production text.
def model():
    collects = re.search(r'info\.frag_color_components\[(\w+)\] \|=\s*static_cast<u8>\(1U << '
                         r'inst\.Arg\(1\)\.U32\(\)\);', collect_case)
    packs = re.search(r'color_output_mask \|= u32\{stage_infos\[NUM_STAGES - 1\]\.'
                      r'frag_color_components\[rt\]\}\s*<< \(rt \* 4\);', ctor_part)
    per_rt = re.search(r'VkColorComponentFlags ColorOutputMask\(size_t (\w+)\) const noexcept '
                       r'\{\s*return (.*?);', accessors, re.S)
    static_and = re.search(r'write_mask &= ColorOutputMask\(index\);', static_mask)
    dyn_mask = re.search(r'const u32 color_output_mask = pipeline \? pipeline->ColorOutputMask\(\) '
                         r': ~0U;', blending_mask)
    dyn_changed = re.search(r'const bool color_output_changed = color_output_mask != '
                            r'last_color_output_mask;', blending_mask)
    dyn_and = re.search(r'current &= (.*?);', blending_mask)
    early = re.search(r'if \(([^{}]*?)\) \{\s*return;', blending_mask)[1]
    record = re.search(r'if \(([^{}]*?)\) \{\s*(?:last_color_output_mask = color_output_mask;\s*)?'
                       r'std::array<VkColorComponentFlags', blending_mask)[1]

    def flags(expression, tb, tc, changed):
        expression = (expression.replace('state_tracker.TouchBlending()', 'tb')
                      .replace('state_tracker.TouchColorMask()', 'tc'))
        return cint(expression, {'tb': tb, 'tc': tc, 'color_output_changed': changed})

    pipelines = {}
    last = [0]
    results = []
    for command in script:
        if command[0] == 'P':
            _, pid, writes = command
            frag = [0] * 8
            for rt, component in writes:
                if collects:
                    frag[rt] |= 1 << component
            pipelines[pid] = sum(frag[rt] << (rt * 4) for rt in range(8)) if packs else 0
            results.append(None)
        elif command[0] == 'S':
            _, pid, index, guest = command
            mask = guest
            if static_and:
                mask &= cint(per_rt[2], {'color_output_mask': pipelines[pid], per_rt[1]: index})
            results.append(mask)
        else:
            _, pid, common, guests, dirty_b, dirty_c = command
            output = (pipelines[pid] if pid >= 0 else 0xFFFFFFFF) if dyn_mask else None
            changed = dyn_changed is not None and output != last[0]
            if not flags(early, dirty_b, dirty_c, changed) and flags(record, dirty_b, dirty_c, changed):
                if dyn_changed:
                    last[0] = output
                masks = []
                for index in range(8):
                    current = guests[0 if common else index]
                    if dyn_and:
                        current &= cint(dyn_and[1], {'color_output_mask': output, 'index': index})
                    masks.append(current)
                results.append(masks)
            else:
                results.append(None)
    return results


check_results(model())

# --------------------------------------------------------------------------------------------
# Bare-image-view BlitColor followed by a draw of the previous pipeline (both modes).
bare_blit = function(blit, 'void BlitImageHelper::BlitColor(const Framebuffer* dst_framebuffer, '
                     'VkImageView src_image_view,')
invalidate = function(scheduler_cpp, 'void Scheduler::InvalidateState()')
update_pipeline = function(scheduler_cpp, 'bool Scheduler::UpdateGraphicsPipeline(')
record_end = block_end(bare_blit, bare_blit.index('{', bare_blit.index('scheduler.Record(')))
blit_binds = 'cmdbuf.BindPipeline(VK_PIPELINE_BIND_POINT_GRAPHICS, pipeline);' in bare_blit
blit_invalidates = 'scheduler.InvalidateState();' in bare_blit[record_end:]
check(blit_binds, 'bare BlitColor no longer binds its own pipeline; the model is stale')
state = {'graphics_pipeline': 'A', 'bound': 'A', 'colour_dirty': False}
state['bound'] = 'blit'  # the blit's BindPipeline; its colour write mask is static
if blit_invalidates:
    if 'state.graphics_pipeline = nullptr;' in invalidate:
        state['graphics_pipeline'] = None
    if 'state_tracker.InvalidateCommandBufferState();' in invalidate:
        state['colour_dirty'] = True
# Next draw of pipeline A: UpdateGraphicsPipeline returns early when it believes A is bound.
skips = re.search(r'if \(state\.graphics_pipeline == pipeline\) \{', update_pipeline)
if not (skips and state['graphics_pipeline'] == 'A'):
    state['graphics_pipeline'] = state['bound'] = 'A'
check(state['bound'] == 'A', 'draw after the bare BlitColor (DrawTexture/DLSS) runs with the blit '
      'pipeline: the scheduler still believes the previous pipeline is bound, so it is not bound '
      'again and its dynamic colour write mask is not recorded again')
check(state['colour_dirty'], 'after the bare BlitColor the colour write mask is not marked dirty')

# Wiring of the dynamic path; behaviour above already failed on main.
prepare = rasterizer[:rasterizer.index('void RasterizerVulkan::DrawTexture()')]
configured = re.findall(r'if \(!(\w+)->Configure\(is_indexed\)\) return;', prepare)
check(configured and f'UpdateDynamicStates({configured[-1]});' in prepare,
      'PrepareDraw does not pass the draw pipeline to UpdateDynamicStates')
draw_texture = function(rasterizer, 'void RasterizerVulkan::DrawTexture()')
check('UpdateDynamicStates(nullptr);' in draw_texture,
      'DrawTexture does not pass a null pipeline (full mask) to UpdateDynamicStates')
dynamic_states = function(rasterizer, 'void RasterizerVulkan::UpdateDynamicStates(')
parameter = re.match(r'void RasterizerVulkan::UpdateDynamicStates\(const GraphicsPipeline\* (\w+)\)',
                     dynamic_states)
check(parameter and f'UpdateBlending(regs, {parameter[1]});' in dynamic_states,
      'UpdateDynamicStates does not pass its pipeline to UpdateBlending')
write_enable = function(rasterizer, 'void RasterizerVulkan::UpdateColorWriteEnable(')
check('(mask.R || mask.G || mask.B || mask.A) ? VK_TRUE : VK_FALSE' in write_enable,
      'UpdateColorWriteEnable is no longer a target-level enable')
check('stores_frag_color[render_target] = true' in collect_case
      or 'stores_frag_color[inst.Arg(0).U32()] = true' in collect_case,
      'stores_frag_color is no longer collected')
check('fragment_has_color0_output = stage_infos[NUM_STAGES - 1].stores_frag_color[0];' in ctor_part,
      'fragment_has_color0_output changed')


def report(mode):
    if failures:
        unique = list(dict.fromkeys(failures))
        print(f'UB-084 {mode}: FAIL ({len(unique)} findings)')
        for name in dict.fromkeys(f[:f.index(']') + 1] for f in unique):
            group = [f[len(name) + 1:] for f in unique if f.startswith(name)]
            print(f'  {name} {len(group)} findings')
            for failure in group[:12] + group[12:][-8:]:
                print('    ' + failure)
        sys.exit(1)


if source_only:
    report('source model')
    print('UB-084 fragment output mask (static, dynamic, pipeline change, blit invalidate) '
          'source model: PASS (C++ not run)')
    sys.exit(0)
assert platform.system() == 'Linux', 'compiled fixture is Linux/dedie-only'
phase[0] = 'compiled'

# --------------------------------------------------------------------------------------------
# Compiled: production pieces with stubs, driven by the same script on stdin.
fixture = r'''
#include <array>
#include <cstdint>
#include <cstdio>
#include <iostream>
#include <map>
#include <utility>
#include <vector>
using u8 = std::uint8_t;
using u32 = std::uint32_t;
using VkColorComponentFlags = u32;
enum VkColorComponentFlagBits : u32 {
    VK_COLOR_COMPONENT_R_BIT = 1,
    VK_COLOR_COMPONENT_G_BIT = 2,
    VK_COLOR_COMPONENT_B_BIT = 4,
    VK_COLOR_COMPONENT_A_BIT = 8,
};
namespace IR {
enum class Opcode { SetFragColor, SetSampleMask };
struct Value {
    u32 v;
    u32 U32() const { return v; }
};
struct Inst {
    Opcode op;
    std::array<Value, 3> args;
    Opcode GetOpcode() const { return op; }
    Value Arg(size_t i) const { return args[i]; }
};
}
struct Info {
    std::array<bool, 8> stores_frag_color{};
    std::array<u8, 8> frag_color_components{};
    bool stores_sample_mask{};
};
void VisitUsages(Info& info, IR::Inst& inst) {
    switch (inst.GetOpcode()) {
@COLLECT@
    default:
        break;
    }
}
namespace Maxwell {
constexpr size_t NumRenderTargets = 8;
}
struct Attachment {
    std::array<bool, 4> mask;
    std::array<bool, 4> Mask() const { return mask; }
};
class GraphicsPipeline {
public:
    static constexpr size_t NUM_STAGES = 5;
    std::array<Info, NUM_STAGES> stage_infos{};
    bool fragment_has_color0_output{};
    u32 color_output_mask{};
    struct {
        struct {
            std::array<Attachment, 8> attachments{};
        } state;
    } key;
@ACCESSORS@
    void Construct() {
@CTOR@
    }
    VkColorComponentFlags StaticMask(size_t index) {
@STATIC@
        return write_mask;
    }
};
struct Regs {
    struct ColorMask {
        u32 R, G, B, A;
    };
    std::array<ColorMask, 8> color_mask{};
    u32 color_mask_common{};
};
namespace Tegra::Engines {
struct Maxwell3D {
    using Regs = ::Regs;
};
}
struct CmdBuf {
    std::vector<std::array<VkColorComponentFlags, 8>>* log;
    void SetColorWriteMaskEXT(u32, const std::array<VkColorComponentFlags, 8>& masks) const {
        log->push_back(masks);
    }
};
namespace vk {
using CommandBuffer = CmdBuf;
}
struct StateTracker {
    bool blending{}, color_mask{};
    bool TouchBlending() { return std::exchange(blending, false); }
    bool TouchColorMask() { return std::exchange(color_mask, false); }
};
struct Scheduler {
    std::vector<std::array<VkColorComponentFlags, 8>> log;
    template <typename F>
    void Record(F&& f) { f(CmdBuf{&log}); }
};
struct RasterizerVulkan {
    StateTracker state_tracker;
    Scheduler scheduler;
    u32 last_color_output_mask{};
    @BLENDING_DECL@;
};
@BLENDING@

// Main's UpdateBlending has no pipeline argument.
template <typename Rasterizer>
void CallUpdateBlending(Rasterizer& r, Regs& regs, const GraphicsPipeline* pipeline) {
    if constexpr (requires { r.UpdateBlending(regs, pipeline); }) {
        r.UpdateBlending(regs, pipeline);
    } else {
        r.UpdateBlending(regs);
    }
}

int main() {
    std::map<int, GraphicsPipeline> pipelines;
    RasterizerVulkan rasterizer;
    Regs regs;
    char kind;
    while (std::cin >> kind) {
        if (kind == 'P') {
            int id, count;
            std::cin >> id >> count;
            Info info;
            for (int i = 0; i < count; ++i) {
                u32 rt, component;
                std::cin >> rt >> component;
                IR::Inst inst{IR::Opcode::SetFragColor, {{{rt}, {component}, {0}}}};
                VisitUsages(info, inst);
            }
            pipelines[id].stage_infos[GraphicsPipeline::NUM_STAGES - 1] = info;
            pipelines[id].Construct();
            std::printf("P\n");
        } else if (kind == 'S') {
            int id;
            size_t index;
            u32 guest;
            std::cin >> id >> index >> guest;
            auto& pipeline = pipelines[id];
            for (int c = 0; c < 4; ++c) pipeline.key.state.attachments[index].mask[c] = (guest >> c) & 1;
            std::printf("S %u\n", pipeline.StaticMask(index));
        } else {
            int id;
            std::cin >> id >> regs.color_mask_common;
            for (auto& m : regs.color_mask) {
                u32 guest;
                std::cin >> guest;
                m = {guest & 1, (guest >> 1) & 1, (guest >> 2) & 1, (guest >> 3) & 1};
            }
            std::cin >> rasterizer.state_tracker.blending >> rasterizer.state_tracker.color_mask;
            const GraphicsPipeline* pipeline = id < 0 ? nullptr : &pipelines.at(id);
            rasterizer.scheduler.log.clear();
            CallUpdateBlending(rasterizer, regs, pipeline);
            if (rasterizer.scheduler.log.empty()) {
                std::printf("D none\n");
            } else {
                std::printf("D");
                for (u32 m : rasterizer.scheduler.log.back()) std::printf(" %u", m);
                std::printf("\n");
            }
        }
    }
    return 0;
}
'''
fixture = (fixture.replace('@COLLECT@', collect_case).replace('@ACCESSORS@', accessors)
           .replace('@CTOR@', ctor_part).replace('@STATIC@', static_mask)
           .replace('@BLENDING_DECL@', blending_signature).replace('@BLENDING@', blending_mask))
lines = []
for command in script:
    if command[0] == 'P':
        lines.append(f'P {command[1]} {len(command[2])} ' +
                     ' '.join(f'{rt} {c}' for rt, c in command[2]))
    elif command[0] == 'S':
        lines.append('S {} {} {}'.format(*command[1:]))
    else:
        _, pid, common, guests, dirty_b, dirty_c = command
        lines.append(f'D {pid} {common} {" ".join(map(str, guests))} {int(dirty_b)} {int(dirty_c)}')
build = root / 'build/nx2-tests'
build.mkdir(parents=True, exist_ok=True)
cpp = build / 'fragment-output-mask.cpp'
exe = build / 'fragment-output-mask'
cpp.write_text(fixture)
if '--emit-fixture' in sys.argv[1:]:
    print(cpp)
    sys.exit(0)
subprocess.run([os.environ.get('CXX', 'clang++-18'), '-std=c++20', '-O1', '-g',
                '-fsanitize=address,undefined', '-fno-sanitize-recover=all', str(cpp), '-o',
                str(exe)], check=True)
output = subprocess.run([str(exe)], input='\n'.join(lines) + '\n', check=True,
                        capture_output=True, text=True).stdout.splitlines()
check(len(output) == len(script), f'compiled fixture answered {len(output)}/{len(script)} commands')
results = []
for line in output:
    fields = line.split()
    if fields[0] == 'P':
        results.append(None)
    elif fields[0] == 'S':
        results.append(int(fields[1]))
    else:
        results.append(None if fields[1] == 'none' else [int(f) for f in fields[1:]])
check_results(results)
report('source model + compiled')
print(f'UB-084 production collect/static/dynamic masks ({len(script)} commands) and blit '
      'invalidate model: PASS')
