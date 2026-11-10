"""UB-098: ProcessDraw skips rasterizer->Draw for draws of 0 vertices/indices or 0 instances.

Compiles the PRODUCTION Maxwell3D::DrawManager::ProcessDraw (extracted from the prepared
draw_manager.cpp; the native_turing-only diagnostics block is cut out by brace matching, so the
general, non-native path is what runs) against a fake Maxwell3D with a counting rasterizer, a
dirty-flag array and a topology override that UpdateTopology applies. Checked:
 - instance_count == 0: no Draw (indexed and not);
 - vertex count 0 (non-indexed) / index count 0 (indexed) with instances > 0: no Draw;
 - a normal draw still calls Draw with the same arguments;
 - UpdateTopology still runs on the empty path (override applied);
 - a dirty flag set by the caller before an empty draw is still set afterwards.
Negative control: on main (a tree without layer 99zzzze) the general path still calls
rasterizer->Draw for zero-count / zero-instance draws, so the "no Draw" expectations fail. The
native_turing-only early return on main does not satisfy this test. --source-only asserts that the
count/instance guard sits between the native block and rasterizer->Draw in the production text.
The compiled harness is Linux/dedie-only.

Usage: check-skip-empty-draws.py [--source-only] [SOURCE_DIR]   SOURCE_DIR contains src/
(default: this checkout's prepared build cache).
"""
from pathlib import Path
import platform
import re
import subprocess
import sys

args = [a for a in sys.argv[1:] if not a.startswith('--')]
source_only = '--source-only' in sys.argv[1:]
if not source_only:
    assert platform.system() == 'Linux', 'Run on the Linux build server'
root = Path(__file__).resolve().parents[1]
if args:
    source = Path(args[0]).resolve()
else:
    source = Path((root / '.local/headless-cache').read_text().strip()) / 'source'
text = (source / 'src/video_core/engines/draw_manager.cpp').read_text()

start = text.index('void Maxwell3D::DrawManager::ProcessDraw(')
open_brace = text.index('{', start)
depth, i = 0, open_brace
while True:
    depth += text[i] == '{'
    depth -= text[i] == '}'
    i += 1
    if depth == 0:
        break
func = text[start:i]

# Cut the native_turing block (brace matched); the general path is what is under test.
nstart = func.index('if (native.native_turing) {')
j = func.index('{', nstart)
depth = 0
while True:
    depth += func[j] == '{'
    depth -= func[j] == '}'
    j += 1
    if depth == 0:
        break
general = func[:nstart] + func[j:]
assert 'rasterizer->Draw(draw_indexed, instance_count)' in general
assert 'UpdateTopology(maxwell3d)' in general
pre_draw = general[general.index('ShouldExecute()'):general.index('rasterizer->Draw(')]
guard = re.search(r'if \(.*instance_count\b.*index_buffer\.count.*vertex_buffer\.count', pre_draw, re.S)
assert guard, 'no empty-draw guard before rasterizer->Draw (main still draws empty draws)'
assert 'return;' in pre_draw[guard.start():], 'the empty-draw guard must return'
assert 'dirty' not in pre_draw[guard.start():], 'the empty path must not touch dirty flags'

if source_only:
    print('skip-empty-draws source checks passed')
    sys.exit(0)

harness = r'''
#include <cstdio>
#include <cstdint>
#include <array>
#define LOG_TRACE(...) ((void)0)
using u32 = std::uint32_t;
struct Native { bool native_turing = false; };
struct Rast {
    int draws = 0; bool last_indexed = false; u32 last_instances = 0;
    void Draw(bool indexed, u32 instances) { ++draws; last_indexed = indexed; last_instances = instances; }
};
struct Maxwell3D {
    struct Regs { struct { u32 count; } index_buffer; };
    struct DrawState {
        int topology = 0;
        u32 draw_element_count = 0; // UB-013 records the active count before this guard.
        struct { u32 count = 0; } index_buffer;
        struct { u32 count = 0; } vertex_buffer;
    };
    struct DrawManager {
        DrawState draw_state;
        void UpdateTopology(Maxwell3D& m) { draw_state.topology = m.topology_override; }
        void ProcessDraw(Maxwell3D& maxwell3d, bool draw_indexed, u32 instance_count);
    };
    Rast* rasterizer; Native native; int topology_override = 0; std::array<bool, 4> dirty{};
    bool ShouldExecute() { return true; }
    Native& GetNativeMacroEngine() { return native; }
};
''' + general + r'''
static int fails = 0;
static void Check(bool ok, const char* what) { if (!ok) { std::fprintf(stderr, "FAIL: %s\n", what); ++fails; } }
static int Run(bool indexed, u32 count, u32 instances, int override_topology = 5, bool dirty_in = true,
               bool* dirty_out = nullptr, int* topology_out = nullptr, u32* inst_out = nullptr) {
    Rast r; Maxwell3D m; m.rasterizer = &r; m.topology_override = override_topology; m.dirty[1] = dirty_in;
    Maxwell3D::DrawManager d;
    (indexed ? d.draw_state.index_buffer.count : d.draw_state.vertex_buffer.count) = count;
    d.ProcessDraw(m, indexed, instances);
    if (dirty_out) *dirty_out = m.dirty[1];
    if (topology_out) *topology_out = d.draw_state.topology;
    if (inst_out) *inst_out = r.last_instances;
    return r.draws;
}
int main() {
    for (bool idx : {false, true}) {
        Check(Run(idx, 10, 0) == 0, "zero instances must not Draw");
        Check(Run(idx, 0, 3) == 0, "zero vertices/indices must not Draw");
        Check(Run(idx, 0, 0) == 0, "zero count and instances must not Draw");
        u32 inst = 0;
        Check(Run(idx, 10, 3, 5, true, nullptr, nullptr, &inst) == 1 && inst == 3, "normal draw must Draw once");
    }
    bool dirty = false; int topo = 0;
    Run(true, 0, 1, 7, true, &dirty, &topo);
    Check(topo == 7, "UpdateTopology must still run on the empty path");
    Check(dirty, "caller-set dirty flag must stay set after an empty draw");
    return fails ? 3 : 0;
}
'''
out = root / 'build/nx2-tests/skip-empty-draws'
out.mkdir(parents=True, exist_ok=True)
cpp = out / 'harness.cpp'
cpp.write_text(harness)
subprocess.run(['g++', '-std=c++20', str(cpp), '-o', str(out / 'h')], check=True)
subprocess.run([str(out / 'h')], check=True)
print('skip-empty-draws checks passed')
