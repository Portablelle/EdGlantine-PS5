"""UB-133 staging residual. Extract ReleaseLevel; model it without a compiler or compile on dedie.

Usage: python3 tests-nx2/check-staging-upload-retain.py [--source-only] [SOURCE_DIR]
Main runs its existing 16-deletion sweep and fails because subsequent requests allocate again.
TrimIdle/IdleAllowance remain the final authority, including over keep-two entries.
"""
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
args = [a for a in sys.argv[1:] if not a.startswith('--')]
source = Path(args[0]) if args else Path((root / '.local/headless-cache').read_text().strip()) / 'source'
text = (source / 'src/video_core/renderer_vulkan/vk_staging_buffer_pool.cpp').read_text()
def function(text, signature):
    start = text.index(signature); pos = text.index('{', start) + 1; depth = 1
    while depth:
        depth += (text[pos] == '{') - (text[pos] == '}'); pos += 1
    return text[start:pos]
body = function(text, 'void StagingBufferPool::ReleaseLevel(')
keep = re.search(r'KeepPerLevel = (\d+)', body)
max_log = re.search(r'KeepMaxLog2 = (\d+)', body)
keep = int(keep[1]) if keep else 0
max_log = int(max_log[1]) if max_log else -1
trim = (root / 'headless/staging_buffers.h').read_text()
prepare = (root / 'tools/prepare-vulkan-port.py').read_text()
assert '    ReleaseCache(MemoryUsage::Download);\n}\n' in text
for token in ('TrimIdle(', 'IdleAllowance(largest)', '!entry.deferred && scheduler.IsFree(entry.tick)',
              '&device_local_cache, &upload_cache, &download_cache'):
    assert token in prepare, token
assert 'kIdleKept = std::uint64_t{256} << 20' in trim
assert 'kLowLargestFree = std::uint64_t{512} << 20' in trim
assert 'largest_free < kLowLargestFree ? 0 : kIdleKept' in trim

if '--source-only' in sys.argv:
    # Execute the existing ReleaseLevel branch too: 16 inspected entries on main, no retention.
    assert 'deletions_per_tick = 16' in body
    assert 'scheduler.IsFree(entry.tick)' in body
    def sweep(kind, log, entries):
        if keep and kind == 'upload' and log <= max_log:
            idle = 0; retained = []
            for busy, deferred in entries:
                if not busy and not deferred:
                    idle += 1
                    if idle > keep: continue
                retained.append((busy, deferred))
            return retained
        return [e for i, e in enumerate(entries) if i >= 16 or e[0] or e[1]]
    swept = {}
    for kind in ['upload', 'download', 'device']:
        for log in range(64):  # a full sweep visits each level once
            swept[kind, log] = sweep(kind, log, [(False, False)]*4 + [(True, False), (False, True)])
    idle = sum(not b and not d for b, d in swept['upload', 24])
    allocations = max(0, 2-idle)
    print('repeated 16 MiB upload load: new allocations after sweep =', allocations)
    assert allocations == 0, 'main deletes reusable upload staging; next load allocates again'
    for (kind, log), entries in swept.items():
        idle = sum(not b and not d for b, d in entries)
        assert idle == (2 if kind == 'upload' and log <= 25 else 0)
        assert (True, False) in entries and (False, True) in entries
    # Final TrimIdle pass is deliberately independent of retention; no floor is reserved.
    caches = [(24, False, False)]*2 + [(25, False, False)]*2 + [(26, True, False), (26, False, True)]
    for largest in [-1, 512<<20, (512<<20)-1]:
        allowance = 256<<20 if largest == -1 or largest >= 512<<20 else 0
        remaining = list(caches)
        idle_bytes = sum(1<<l for l,b,d in remaining if not b and not d)
        for e in sorted(caches, reverse=True):
            l,b,d = e
            if idle_bytes <= allowance: break
            if not b and not d: remaining.remove(e); idle_bytes -= 1<<l
        assert idle_bytes <= allowance
        if allowance == 0: assert all(b or d for _,b,d in remaining)
        assert sum(b or d for _,b,d in remaining) == 2
    assert keep == 2 and max_log == 25
    assert '!entry.deferred && scheduler.IsFree(entry.tick) && ++idle > KeepPerLevel' in body
    print('PASS: source-bound sweep/reuse and pressure model (C++ harness not run)')
    sys.exit(0)

assert platform.system() == 'Linux', 'compiled harness is Linux/dedie only'
harness = r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <span>
#include <vector>
#include "staging_buffers.h"
struct StagingBuffer {bool busy=false, deferred=false; unsigned log2_level=24;
 std::span<unsigned char> mapped_span{}; unsigned tick=0;};
struct Level {std::vector<StagingBuffer> entries; size_t delete_index=0, iterate_index=0;};
using StagingBuffersCache=std::array<Level,64>;
struct StagingBufferPool {
 struct Scheduler {bool IsFree(unsigned tick){return tick==0;}} scheduler;
 StagingBuffersCache upload_cache{},download_cache{},device_local_cache{};
 void ReleaseLevel(StagingBuffersCache&,size_t);
};
''' + body + r'''
int main() {
 StagingBufferPool p;
 for(auto cache:{&p.upload_cache,&p.download_cache,&p.device_local_cache}) {
  for(unsigned log=0;log<64;++log) {
   auto& entries=(*cache)[log].entries;
   for(int i=0;i<4;++i) entries.push_back({false,false,log,{},0});
   entries.push_back({true,false,log,{},1}); entries.push_back({false,true,log,{},~0u});
   p.ReleaseLevel(*cache,log);
   auto idle=std::count_if(entries.begin(),entries.end(),[](auto& e){return e.tick==0;});
   // Main's real ReleaseLevel executes and fails here; no new header is required.
   assert(idle==(cache==&p.upload_cache && log<=25 ? 2 : 0));
   assert(std::count_if(entries.begin(),entries.end(),[](auto& e){return e.tick!=0;})==2);
   entries.erase(std::remove_if(entries.begin(),entries.end(),[](auto& e){return e.log2_level>25;}),entries.end());
  }
 }
 using namespace Eden::StagingBuffers;
 std::array<StagingBuffersCache*,3> caches{&p.device_local_cache,&p.upload_cache,&p.download_cache};
 const auto idle=[](const auto& e){return !e.deferred && e.tick==0;};
 for(auto largest:{size_t(-1),size_t(512)<<20,(size_t(512)<<20)-1}) {
  const auto allowance=IdleAllowance(largest);
  TrimIdle(caches,idle,allowance);
  uint64_t bytes=0;size_t busy=0;
  for(auto cache:caches)for(auto& level:*cache)for(auto& e:level.entries) {
   if(idle(e))bytes+=Holds(e.mapped_span.size(),e.log2_level); else ++busy;
  }
  assert(bytes<=allowance); assert(busy==3*26*2);
  if(allowance==0)assert(bytes==0);
 }
}
'''
with tempfile.TemporaryDirectory(prefix='staging-retain-') as d:
    cpp=Path(d)/'test.cpp'; cpp.write_text(harness)
    subprocess.run(['g++','-std=c++20','-O1','-Wall','-Wextra','-I'+str(root/'headless'),str(cpp),'-o',str(Path(d)/'test')],check=True)
    subprocess.run([str(Path(d)/'test')],check=True)
print('PASS: production ReleaseLevel and TrimIdle/IdleAllowance harness')
