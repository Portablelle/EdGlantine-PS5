"""UB-088: QuadIndexBuffer::UpdateBuffer grows without scheduler.Finish(), by at least 1.5x.

Compiles the PRODUCTION decision path of QuadIndexBuffer::UpdateBuffer (extracted from the prepared
vk_buffer_cache.cpp, from `void UpdateBuffer(` up to the `index_type = ...` line, before any Vulkan
buffer creation) against a fake scheduler (Finish counter, CurrentTick, controllable IsFree) and a
fake movable buffer. Checked:
 - growing never calls Finish();
 - the previous buffer is retired with the current tick, held while IsFree is false and released by
   a later UpdateBuffer once IsFree is true;
 - num_indices becomes max(request, old + old / 2): 100 -> request 101 gives 150, 100 -> 400 gives 400;
 - a request <= num_indices is a no-op (but still releases already-free retired buffers).
Negative control: on main (no layer 99zzzzg) UpdateBuffer calls Finish() and sets num_indices to the
exact request (101, not 150), so the compiled harness fails on behavior; --source-only fails on the
Finish/max assertions. The compiled harness is Linux/dedie-only (needs g++).

Usage: check-quad-index-grow-no-finish.py [--source-only] [SOURCE_DIR]   SOURCE_DIR contains src/
(default: this checkout's prepared build cache).
"""
from pathlib import Path
import platform
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
text = (source / 'src/video_core/renderer_vulkan/vk_buffer_cache.cpp').read_text()

start = text.index('void UpdateBuffer(u32 num_indices_) {')
end = text.index('index_type = IndexTypeFromNumElements(device, num_indices);', start)
body = text[start:end]

assert 'Finish()' not in body, 'UpdateBuffer must not wait for the GPU (scheduler.Finish)'
assert 'retired_buffers' in body and 'CurrentTick()' in body and 'IsFree(' in body, \
    'old buffer must be retired with the current tick and freed on IsFree'
assert 'num_indices / 2' in body and 'max)(num_indices_' in body, 'growth must be at least 1.5x'
assert 'std::vector<std::pair<u64, vk::Buffer>> retired_buffers' in text

if source_only:
    print('quad-index-grow-no-finish source checks passed')
    sys.exit(0)

harness = r'''
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <utility>
#include <vector>
using u32 = std::uint32_t;
using u64 = std::uint64_t;
struct Buf {
    int id = 0;
    Buf() = default;
    explicit Buf(int i) : id{i} {}
    Buf(Buf&& o) noexcept : id{std::exchange(o.id, 0)} {}
    Buf& operator=(Buf&& o) noexcept { id = std::exchange(o.id, 0); return *this; }
    explicit operator bool() const { return id != 0; }
};
struct Sched {
    int finishes = 0;
    u64 tick = 5;
    u64 free_below = 0;  // IsFree(t) == t < free_below
    void Finish() { ++finishes; }
    u64 CurrentTick() const { return tick; }
    bool IsFree(u64 t) const { return t < free_below; }
};
struct Dev {};
static u32 IndexTypeFromNumElements(const Dev&, u32) { return 0; }
struct Q {
    Dev device; Sched scheduler; Buf buffer; std::vector<std::pair<u64, Buf>> retired_buffers;
    u32 index_type = 0; u32 num_indices = 0; int next_id = 1;
    void UpdateBuffer(u32 num_indices_) {
''' + body.split('{', 1)[1] + r'''
        index_type = IndexTypeFromNumElements(device, num_indices);
        buffer = Buf{next_id++};  // stands in for the buffer creation after the decision path
    }
};
static int fails = 0;
#define EXPECT(c) do { if (!(c)) { std::fprintf(stderr, "line %d: %s\n", __LINE__, #c); ++fails; } } while (0)
int main() {
    Q q;
    q.UpdateBuffer(100);
    EXPECT(q.num_indices == 100 && q.scheduler.finishes == 0 && q.retired_buffers.empty());
    EXPECT(q.buffer.id == 1);
    q.UpdateBuffer(100);  // no-op
    EXPECT(q.buffer.id == 1 && q.num_indices == 100);
    q.scheduler.tick = 7;
    q.UpdateBuffer(101);  // grow by max(101, 150)
    EXPECT(q.num_indices == 150);
    EXPECT(q.scheduler.finishes == 0);
    EXPECT(q.retired_buffers.size() == 1 && q.retired_buffers[0].first == 7 && q.retired_buffers[0].second.id == 1);
    EXPECT(q.buffer.id == 2);
    q.UpdateBuffer(120);  // no-op, GPU not past tick 7: old buffer kept
    EXPECT(q.retired_buffers.size() == 1 && q.buffer.id == 2 && q.num_indices == 150);
    q.scheduler.free_below = 8;  // tick 7 is now free
    q.UpdateBuffer(150);  // no-op still releases the free one
    EXPECT(q.retired_buffers.empty() && q.buffer.id == 2 && q.scheduler.finishes == 0);
    q.UpdateBuffer(400);  // request above 1.5x uses the request
    EXPECT(q.num_indices == 400 && q.retired_buffers.size() == 1 && q.retired_buffers[0].second.id == 2);
    EXPECT(q.scheduler.finishes == 0);
    return fails ? 3 : 0;
}
'''
out = root / 'build/nx2-tests/quad-index-grow-no-finish'
out.mkdir(parents=True, exist_ok=True)
cpp = out / 'harness.cpp'
cpp.write_text(harness)
subprocess.run(['g++', '-std=c++20', str(cpp), '-o', str(out / 'h')], check=True)
subprocess.run([str(out / 'h')], check=True)
print('quad-index-grow-no-finish checks passed')
