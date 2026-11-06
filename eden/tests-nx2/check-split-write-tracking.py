"""GPU split front-side write tracking (99zzzt1/99zzzt2): compile the page bitmap against the
patched source and check its marks; check that the early paths keep their fallbacks. Run on dedie."""
from pathlib import Path
import platform
import subprocess
import tempfile

assert platform.system() == 'Linux', 'Compile on dedie'
root = Path(__file__).resolve().parents[1]
source = Path((root / '.local/headless-cache').read_text().strip()) / 'source/src'
video = source / 'video_core'

cpp = r'''
#include <cassert>
#include <cstdio>
#include "video_core/gpu_written_pages.h"
namespace P = VideoCommon::GpuWrittenPages;
int main() {
    assert(!P::Any(0x10000, 0x3000));
    assert(!P::Any(0x10000, 0));               // empty range: nothing to wait for
    P::Mark(0x11ffc, 8);                       // straddles pages 0x11 and 0x12 (one word)
    assert(P::new_marks.load() == 1);
    assert(!P::Any(0x10000, 0x1000));
    assert(P::Any(0x11000, 1) && P::Any(0x12fff, 1));
    assert(!P::Any(0x13000, 0x1000));
    P::Mark(0x11000, 0x2000);                  // already marked: no new mark
    assert(P::new_marks.load() == 1);
    P::Mark(0x3f000, 0x42000);                 // pages 0x3f..0x80, across 64-page words
    assert(P::new_marks.load() == 4);           // one per 64-page word with new bits
    for (unsigned long long page = 0x3f; page <= 0x80; ++page) assert(P::Any(page << 12, 1));
    assert(!P::Any(0x81000, 1) && !P::Any(0x3e000, 1));
    assert(P::Any((1ULL << 36) - 1, 2));       // past the device space: counts as written
    P::Mark((1ULL << 36) + 0x1000, 0x1000);    // ignored, no crash
    std::puts("SPLIT_TRACK_BITMAP_OK");
}
'''
with tempfile.TemporaryDirectory() as tmp:
    src = Path(tmp) / 't.cpp'
    src.write_text(cpp)
    exe = Path(tmp) / 't'
    subprocess.run(['c++', '-std=c++20', '-O1', '-I', str(source), str(src), '-o', str(exe)], check=True)
    run = subprocess.run([str(exe)], capture_output=True, text=True)
    assert run.returncode == 0 and 'SPLIT_TRACK_BITMAP_OK' in run.stdout, run.stdout + run.stderr

dma = (video / 'dma_pusher.cpp').read_text()
read = dma[dma.index('bool ReadSegmentOnFront('):]
read = read[:read.index('\n}\n')]
order = ['SplitTracking::disabled', 'use_safe || header.sync', 'SettleTime',
         'GpuToCpuAddress(page)', 'Pages::Any(', 'ReadBlockUnsafe', 'Defer(FrontSegmentCheck']
positions = [read.index(token) for token in order]
assert positions == sorted(positions), 'ReadSegmentOnFront checks out of order'
check = dma[dma.index('struct FrontSegmentCheck'):dma.index('bool ReadSegmentOnFront(')]
assert 'IsMemoryDirty' in check and 'memcmp' in check and 'disabled.store(true' in check
assert '} else if (split.Active()) {' in dma and 'split.Synchronize([memory = &memory_manager' in dma

puller = (video / 'engines/puller.cpp').read_text()
poll = puller[puller.index('bool Puller::CanResumeNativeAcquire'):]
poll = poll[:poll.index('DrainBack();')]
assert poll.count('return true;') == 1
assert 'met && native_acquire->operation == static_cast<u32>(GpuSemaphoreOperation::AcquireGequal)' in poll
assert '!met && !split.BackCaughtUp() && now - last_drained_poll_ns < 1\'000\'000' in poll

split = (video / 'gpu_split.h').read_text()
for field in ['list_direct=', 'list_waits=', 'list_misses=', 'sem_fast=', 'sem_skip=', 'track=']:
    assert field in split, field
print('SPLIT_WRITE_TRACKING_CHECKS_PASS')
