"""UB-013: active draw count and (separately) Ampere early submission.

Extract ProcessDraw/ProcessDrawIndirect (omit only native diagnostics/error branches),
BuiltPipeline and FlushWork from PRODUCTION. Linux/dedie compiles them with recording
stubs; each env case gets a new process because production caches the override.
--source-only runs a constrained model of the extracted decisions, plus source checks.
Main compiles with the same stubs and fails by BEHAVIOR: large indexed draws with a
stale small vertex count synchronously build, and Ampere waits for the desktop threshold.
Zero is UNKNOWN for indirect draws, not a known small quad; test after a small direct
draw to catch stale counts. UB-056's draw_deferred and the empty-draw guard must survive.

512 is a conservative tuning default: 16 desktop dispatch intervals, 8x earlier than
4096, with 4x upstream 128's batching to limit submission overhead. No measured FPS
claim (including PS5). Test cadence independently of submission and round overrides
up to the next check. Non-Ampere ignores the override (4096 desktop / 512 Android).

Usage: python3 eden/tests-nx2/check-active-draw-early-submit.py [--source-only] [SOURCE_DIR]
SOURCE_DIR contains src/; default is this checkout's prepared build cache.
Negative control: same command against effective main c67207d (without 99zzzzh).
"""
from pathlib import Path
import os
import platform
import re
import subprocess
import sys
import tempfile

args = [a for a in sys.argv[1:] if not a.startswith('--')]
source_only = '--source-only' in sys.argv[1:]
root = Path(__file__).resolve().parents[1]
source = Path(args[0]).resolve() if args else Path(
    (root / '.local/headless-cache').read_text().strip()) / 'source'
src = source / 'src/video_core'
draw_text = (src / 'engines/draw_manager.cpp').read_text()
pipe_text = (src / 'renderer_vulkan/vk_pipeline_cache.cpp').read_text()
rast_text = (src / 'renderer_vulkan/vk_rasterizer.cpp').read_text()


def function(text, signature):
    start = text.index(signature)
    end = text.index('{', start) + 1
    depth = 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


def general(fn):
    # Keep the general draw path; native-only diagnostics require the complete engine.
    block = function(fn, 'if (native.native_turing)')
    return fn.replace(block, '')


direct = function(draw_text, 'void Maxwell3D::DrawManager::ProcessDraw(')
indirect = function(draw_text, 'void Maxwell3D::DrawManager::ProcessDrawIndirect(')
built = function(pipe_text, 'GraphicsPipeline* PipelineCache::BuiltPipeline(')
flush = function(rast_text, 'void RasterizerVulkan::FlushWork()')
small_expr = re.search(r'if \((draw_state\..*?)\) \{', built)[1]


def number(text):
    return int(text.replace("'", ''))


def source_behavior():
    """Faithful, bounded model of these decisions; main fails actual fixture expectations."""
    failures = []

    def check(ok, message):
        if not ok:
            failures.append(message)

    # Evaluate the actual production small-quad expression, including main's old OR.
    for indexed, indices, vertices, want in [(True, 600, 3, False), (False, 3, 600, False),
                                            (True, 1, 900, True), (False, 900, 6, True)]:
        active = indices if indexed else vertices
        expr = small_expr.replace('draw_state.index_buffer.count', str(indices)).replace(
            'draw_state.vertex_buffer.count', str(vertices)).replace(
            'draw_state.draw_element_count', str(active))
        check(bool(eval(expr.replace('&&', ' and ').replace('||', ' or '),
                        {'__builtins__': {}})) == want, 'active-count small-quad decision')
    unknown = small_expr.replace('draw_state.draw_element_count', '0').replace(
        'draw_state.index_buffer.count', '3').replace('draw_state.vertex_buffer.count', '3')
    check(not eval(unknown.replace('&&', ' and ').replace('||', ' or '),
                   {'__builtins__': {}}), 'unknown indirect count must stay asynchronous')

    defaults = re.findall(r'DRAWS_TO_DISPATCH = (\d+);', flush)
    masks = re.findall(r'CHECK_MASK = (\d+);', flush)
    fallback = re.search(r'fallback = ([\d\']+);', flush)
    clamp = re.search(r'std::clamp\(parsed, ([\d\']+)UL, ([\d\']+)UL\)', flush)
    native_policy = bool(re.search(r'g_nx2_ampere.load\(.*?\)\s*\? native_flush_draws\s*'
                                 r': DRAWS_TO_DISPATCH', flush))
    phase = re.search(r'\+\+draw_counter & CHECK_MASK\) != (CHECK_MASK|0)', flush)[1]
    for dispatch, mask in zip(map(int, defaults), map(int, masks)):
        period = mask + 1
        check((dispatch, period) in [(512, 4), (4096, 32)], 'unchanged platform cadence')
        for ampere in (False, True):
            for value, expected in CASES:
                threshold = dispatch
                if ampere and native_policy and fallback and clamp:
                    threshold = number(fallback[1])
                    # Model leading digit + strtoul + complete consumption + nonzero.
                    if value and re.fullmatch(r'[0-9]+', value) and int(value):
                        threshold = min(max(int(value), number(clamp[1])), number(clamp[2]))
                counter = 0
                while True:
                    counter += 1
                    if counter & mask != (mask if phase == 'CHECK_MASK' else 0):
                        continue
                    if counter >= threshold:
                        break
                want = expected if ampere else dispatch
                check(counter == ((want + period - 1) // period) * period,
                      f'flush behavior ampere={ampere} env={value!r}: {counter}')
    assert not failures, '\n'.join(failures)


# Expected effective threshold; each process starts before the static env parse.
CASES = [(None, 512), ('128', 128), ('513', 513), ('1', 32), ('1048577', 1048576),
         ('999999999999999999999999999999999999', 1048576), ('00064', 64),
         ('0', 512), ('', 512), ('-32', 512), ('+32', 512), (' 32', 512),
         ('32x', 512), ('32 ', 512)]


def source_checks():
    header = (src / 'engines/maxwell_3d.h').read_text()
    assert 'u32 draw_element_count{};' in header
    assert re.search(r'draw_state.draw_element_count\s*=\s*draw_indexed\s*\?\s*'
                     r'draw_state.index_buffer.count\s*:\s*draw_state.vertex_buffer.count;', direct)
    assert direct.index('draw_state.draw_element_count =') < direct.index('UpdateTopology(')
    assert indirect.index('draw_state.draw_element_count = 0;') < indirect.index('UpdateTopology(')
    assert 'draw_deferred = true;' in built and 'Native draws are dropped on purpose' in built
    assert 'if (!instance_count ||' in direct  # UB-098 guard stays in production.
    assert '#include "video_core/nx2.h"' in rast_text
    for part in ['std::getenv("EDEN_NX2_FLUSH_DRAWS")', "value[0] < '0'", "value[0] > '9'",
                 'std::strtoul(value, &end, 10)', "*end != '\\0' || parsed == 0",
                 'static_assert(fallback % (CHECK_MASK + 1) == 0)',
                 '16 desktop dispatch intervals', "upstream's 128", '[32, 1048576]']:
        assert part in flush, part
    lines = (root / 'tests-nx2/run.sh').read_text().splitlines()
    at = lines.index('python3 tests-nx2/check-skip-empty-draws.py')
    assert lines[at + 1] == 'python3 tests-nx2/check-active-draw-early-submit.py'


if source_only:
    source_behavior()
    source_checks()
    print('UB-013: source decision models/checks PASS (C++ not run)')
    sys.exit(0)

assert platform.system() == 'Linux', 'Run C++ fixture on Linux/dedie'
harness = r'''
#include <algorithm>
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
using u32 = std::uint32_t;
#define LOG_TRACE(...) ((void)0)
namespace Tegra { std::atomic<bool> g_nx2_ampere{}; }
struct Native { bool native_turing = false; };
struct Rast {
    int draws = 0;
    void Draw(bool, u32) { ++draws; }
    void DrawIndirect() { ++draws; }
};
struct Maxwell3D {
    struct DrawManager {
        struct {
            int topology = 0;
            u32 draw_element_count = 0;
            struct { u32 count = 0; } index_buffer, vertex_buffer;
        } draw_state;
        void UpdateTopology(Maxwell3D&) {}
        void ProcessDraw(Maxwell3D&, bool, u32);
        void ProcessDrawIndirect(Maxwell3D&);
    } draw_manager;
    Native native;
    Rast* rasterizer;
    bool ShouldExecute() { return true; }
    Native& GetNativeMacroEngine() { return native; }
};
struct GraphicsPipeline { bool built = false; bool IsBuilt() const { return built; } };
struct PipelineCache {
    Maxwell3D* maxwell3d;
    bool use_asynchronous_shaders = true;
    mutable bool draw_deferred = false;
    GraphicsPipeline* BuiltPipeline(GraphicsPipeline*) const noexcept;
};
struct Scheduler {
    u32 dispatches = 0, flushes = 0;
    void DispatchWork() { ++dispatches; }
    void Flush() { ++flushes; }
};
struct RasterizerVulkan {
    u32 draw_counter = 0;
    Scheduler scheduler;
    void FlushWork();
};
PRODUCTION
static int fails = 0;
static void Check(bool ok, const char* message) {
    if (!ok) { std::fprintf(stderr, "UB-013 FAIL: %s\n", message); ++fails; }
}
int main(int argc, char** argv) {
    Rast r;
    Maxwell3D m; m.rasterizer = &r;
    PipelineCache cache{&m}; GraphicsPipeline p;
    auto& d = m.draw_manager;
    for (bool indexed : {false, true}) {
        d.draw_state.index_buffer.count = indexed ? 600 : 3;
        d.draw_state.vertex_buffer.count = indexed ? 3 : 600;
        d.ProcessDraw(m, indexed, 1);
        cache.draw_deferred = false;
        Check(cache.BuiltPipeline(&p) == nullptr && cache.draw_deferred,
              "large active draw must defer despite stale small inactive count");
        Check(d.draw_state.draw_element_count == 600, "record the active count");
        for (u32 count = 1; count <= 6; ++count) {
            (indexed ? d.draw_state.index_buffer.count : d.draw_state.vertex_buffer.count) = count;
            d.ProcessDraw(m, indexed, 1);
            cache.draw_deferred = false;
            Check(cache.BuiltPipeline(&p) == &p && !cache.draw_deferred, "known small quad sync");
        }
    }
    d.ProcessDrawIndirect(m); // Immediately after count 6: must clear the recorded count.
    cache.draw_deferred = false;
    Check(d.draw_state.draw_element_count == 0, "indirect count is unknown");
    Check(cache.BuiltPipeline(&p) == nullptr && cache.draw_deferred, "unknown indirect must defer");
    cache.use_asynchronous_shaders = false;
    Check(cache.BuiltPipeline(&p) == &p, "sync setting preserved");
    cache.use_asynchronous_shaders = true; p.built = true;
    Check(cache.BuiltPipeline(&p) == &p, "built pipeline preserved");
    int before = r.draws;
    d.ProcessDraw(m, false, 0);
    d.draw_state.index_buffer.count = 0; d.ProcessDraw(m, true, 1);
    Check(r.draws == before, "empty draw guard preserved");
#ifdef __ANDROID__
    constexpr u32 desktop = 512, period = 4;
#else
    constexpr u32 desktop = 4096, period = 32;
#endif
    const bool ampere = std::strtoul(argv[1], nullptr, 10) != 0;
    const u32 threshold = ampere ? std::strtoul(argv[2], nullptr, 10) : desktop;
    const u32 interval = (threshold + period - 1) / period * period;
    Tegra::g_nx2_ampere = ampere;
    RasterizerVulkan raster;
    // Two full cycles: each check dispatches until the submission check, which resets.
    for (u32 draw = 1; draw <= interval * 2; ++draw) {
        raster.FlushWork();
        if (raster.scheduler.flushes != draw / interval ||
            raster.scheduler.dispatches != draw / period - draw / interval ||
            raster.draw_counter != draw % interval) {
            Check(false, "FlushWork cadence, threshold or reset");
            break;
        }
    }
    return fails ? 3 : 0;
}
'''.replace('PRODUCTION', '\n\n'.join([general(direct), general(indirect), built, flush]))

with tempfile.TemporaryDirectory(prefix='ub013-') as temp:
    cpp = Path(temp) / 'harness.cpp'
    cpp.write_text(harness)
    for android in (False, True):
        binary = Path(temp) / ('android' if android else 'desktop')
        subprocess.run([os.environ.get('CXX', 'g++'), '-std=c++20', '-O1',
                        *(['-D__ANDROID__'] if android else []), str(cpp), '-o', str(binary)],
                       check=True)
        for value, expected in CASES:
            env = dict(os.environ)
            env.pop('EDEN_NX2_FLUSH_DRAWS', None)
            if value is not None:
                env['EDEN_NX2_FLUSH_DRAWS'] = value
            for ampere in (True, False):
                subprocess.run([str(binary), str(int(ampere)), str(expected)], env=env, check=True)
source_behavior()
source_checks()
print('UB-013: production C++ behavior (desktop/Android) and source checks PASS')
