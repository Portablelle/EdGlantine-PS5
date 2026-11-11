"""UB-167. Source-bound model, plus extracted production C++ on Linux/dedie.

Usage: python3 tests-nx2/check-upload-batch-barriers.py [--source-only] [SOURCE_DIR]
The same CopyBuffer fixture runs on main: it records per-copy barriers and fails by behavior.
No Vulkan driver is needed; the command-buffer double applies copies and counts barriers.
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
vk = source / 'src/video_core/renderer_vulkan'

def function(text, signature):
    start = text.index(signature)
    opening = text.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]

cache = (vk / 'vk_buffer_cache.cpp').read_text()
copy = function(cache, 'void BufferCacheRuntime::CopyBuffer(')
post = function(cache, 'void BufferCacheRuntime::PostCopyBarrier()')
scheduler = (vk / 'vk_scheduler.cpp').read_text()
sh = (vk / 'vk_scheduler.h').read_text()
header = (vk / 'upload_batch.h').read_text() if (vk / 'upload_batch.h').exists() else ''
# Decide from the real CopyBuffer path, including main's unbatched path, before any new-header checks.
batched = 'scheduler.RecordUpload(' in copy
reordered = 'src_buffer == staging_pool.StreamBuf() && can_reorder_upload' in copy
assert reordered and 'VideoCommon::FixSmallVectorADL(vk_copies)' in copy
stages = re.findall(r'PipelineBarrier\(VK_PIPELINE_STAGE_TRANSFER_BIT,\s*vk::(\w+)', copy + post)

prelude = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <functional>
#include <memory>
#include <span>
#include <utility>
#include <vector>
using u32 = uint32_t; using VkBuffer = int;
struct VkBufferCopy { size_t srcOffset, dstOffset, size; };
struct VkMemoryBarrier { int sType; const void* pNext; int srcAccessMask, dstAccessMask; };
constexpr int VK_STRUCTURE_TYPE_MEMORY_BARRIER=1, VK_ACCESS_MEMORY_WRITE_BIT=2,
 VK_ACCESS_TRANSFER_READ_BIT=4, VK_ACCESS_TRANSFER_WRITE_BIT=8, VK_ACCESS_MEMORY_READ_BIT=16,
 VK_PIPELINE_STAGE_TRANSFER_BIT=4;
namespace vk {
constexpr int PIPELINE_STAGE_GRAPHICS_COMPUTE=3, PIPELINE_STAGE_GRAPHICS_COMPUTE_TRANSFER=7;
template<class T> using Span = std::span<const T>;
inline int pairs=0, writes=0, last_stage=0;
inline std::vector<unsigned char> memory[5];
struct CommandBuffer {
 void PipelineBarrier(int src, int dst, int, VkMemoryBarrier) {
  if(src==VK_PIPELINE_STAGE_TRANSFER_BIT) {++pairs; last_stage=dst;}
 }
 void CopyBuffer(int src, int dst, std::span<const VkBufferCopy> copies) {
  ++writes;
  for(auto c:copies) std::copy_n(memory[src].begin()+c.srcOffset,c.size,memory[dst].begin()+c.dstOffset);
 }
};
}
namespace VideoCommon {
template<class T> const T& FixSmallVectorADL(const T& t) {return t;}
namespace GpuSplit { constexpr bool check_owner=false; inline void CheckOwner(const char*) {} }
}
'''

if '--source-only' in sys.argv:
    # Faithful bounded CanAdd/RecordUpload model, bound below to the production comparisons.
    pending, batches, events = [], [], []
    mem = {i: bytearray((j + i) % 256 for j in range(2048)) for i in range(1, 5)}
    oracle = {i: bytearray(b) for i, b in mem.items()}
    def flush():
        if pending:
            batches.append(list(pending))
            for src, dst, so, do, n in pending:
                mem[dst][do:do+n] = mem[src][so:so+n]
            events.append('copies')
            pending.clear()
    def can_add(src, dst, do, n):
        return len(pending) < 64 and not any(src == d or dst == s or
                    (dst == d and do < off + size and off < do + n)
                    for s, d, _, off, size in pending)
    def upload(src, dst, so, do, n, barrier=True, reorder=False):
        oracle[dst][do:do+n] = oracle[src][so:so+n]
        if src == 1 and reorder and reordered:
            flush(); events.append('reordered'); mem[dst][do:do+n] = mem[src][so:so+n]; return
        if batched and barrier and src == 1:
            if not can_add(src, dst, do, n):
                flush()
            pending.append((src, dst, so, do, n))
        else:
            flush(); batches.append([(src, dst, so, do, n)])
            mem[dst][do:do+n] = mem[src][so:so+n]
    for i in range(65):
        upload(1, 2, i*4, i*4, 4)  # adjacency is independent
    flush()
    print('65 independent stream uploads: barrier pairs =', len(batches), '; WRITE dst stages =', stages)
    assert [len(b) for b in batches] == [64, 1], 'existing CopyBuffer records a barrier pair per upload'
    upload(1, 2, 0, 0, 8); upload(1, 2, 8, 4, 8)  # WAW
    assert len(pending) == 1
    flush()
    pending.append((1, 2, 0, 0, 8))
    assert not can_add(2, 3, 100, 4)  # RAW, even with disjoint offsets
    assert not can_add(3, 1, 100, 4)  # WAR
    assert can_add(1, 2, 8, 4)       # adjacency
    pending.clear()
    for src, barrier, reorder in [(3, True, False), (1, False, False), (2, True, False), (1, True, True)]:
        upload(src, 4, 0, 0, 4, barrier, reorder)
        assert not pending  # dedicated, barrier=false, download, reordered
    for operation in ['Record', 'RecordWithUploadBuffer', 'DispatchWork', 'SubmitExecution']:
        upload(1, 2, 0, 0, 4)
        flush(); events.append(operation)
        assert events[-2:] == ['copies', operation]
    assert mem == oracle
else:
    assert platform.system() == 'Linux', 'compiled harness is Linux/dedie only'

# The compiled negative control executes main's original CopyBuffer, using the same command double.
if not header and '--source-only' not in sys.argv:
    assert platform.system() == 'Linux', 'compiled harness is Linux/dedie only'
    tail = copy[copy.index('    static constexpr VkMemoryBarrier READ_BARRIER'):]
    tail = tail.replace('boost::container::small_vector<VkBufferCopy, 8>', 'std::vector<VkBufferCopy>')
    tail = tail.replace('std::ranges::transform(copies, vk_copies.begin(), MakeBufferCopy);',
                        'std::copy(copies.begin(), copies.end(), vk_copies.begin());')
    witness = prelude + r'''
struct Runtime {
 struct Scheduler {
  void RequestOutsideRenderPassOperationContext() {}
  template<class T> void Record(T c) {c(vk::CommandBuffer{});}
  template<class T> void RecordWithUploadBuffer(T c) {c(vk::CommandBuffer{},vk::CommandBuffer{});}
 } scheduler;
 struct Pool {int StreamBuf(){return 1;}} staging_pool;
 void CopyBuffer(int dst_buffer,int src_buffer,std::span<const VkBufferCopy> copies,bool barrier,bool can_reorder_upload) {
''' + tail + r'''
};
int main() {
 for(auto& b:vk::memory)b.resize(2048);
 Runtime r;
 for(size_t i=0;i<65;++i){VkBufferCopy c{i*4,i*4,4};r.CopyBuffer(2,1,{&c,1},true,false);}
 assert(vk::pairs==2 && vk::last_stage==7);
}
'''
    with tempfile.TemporaryDirectory(prefix='upload-main-witness-') as d:
        cpp=Path(d)/'test.cpp'; cpp.write_text(witness)
        subprocess.run(['g++','-std=c++20',str(cpp),'-o',str(Path(d)/'test')],check=True)
        subprocess.run([str(Path(d)/'test')],check=True)
    raise AssertionError('main unexpectedly passed the upload witness')

# Bind the model to the exact production policy and flush boundaries.
assert stages == ['PIPELINE_STAGE_GRAPHICS_COMPUTE_TRANSFER'] * 2, stages
assert 'barrier && src_buffer == staging_pool.StreamBuf() && !vk_copies.empty()' in copy
assert copy.index('can_reorder_upload)') < copy.index('scheduler.RecordUpload(') < copy.index('scheduler.Record([src_buffer')
assert 'MaxCopies = 64' in header
assert re.search(r'PipelineBarrier\(VK_PIPELINE_STAGE_TRANSFER_BIT,\s*vk::PIPELINE_STAGE_GRAPHICS_COMPUTE_TRANSFER, 0, WRITE_BARRIER\)', header)
assert 'VK_ACCESS_MEMORY_READ_BIT | VK_ACCESS_MEMORY_WRITE_BIT' in header
for rule in ('copies.size() + new_copies.size() > MaxCopies', 'src == group.dst || dst == group.src',
             'copy.dstOffset < pending.dstOffset + pending.size', 'pending.dstOffset < copy.dstOffset + copy.size'):
    assert rule in header, rule
record_upload = function(scheduler, 'void Scheduler::RecordUpload(')
flush_uploads = function(scheduler, 'void Scheduler::FlushUploads()')
assert 'for (const VkBufferCopy& copy : copies)' in record_upload
assert 'upload_batch->CanAdd(src, dst, region)' in record_upload
assert flush_uploads.index('uploads_pending = false') < flush_uploads.index('Record(std::move(command))')
record_with = function(sh, 'void RecordWithUploadBuffer(')
assert record_with.index('FlushUploads();') < record_with.index('chunk->Record(command)')
for sig, marker in [('void Scheduler::DispatchWork()', 'if (chunk'),
                    ('u64 Scheduler::SubmitExecution(', 'master_semaphore->NextTick()')]:
    body = function(scheduler, sig)
    assert body.index('FlushUploads();') < body.index(marker)
assert 'this->RecordWithUploadBuffer(' in function(sh, 'void Record(T&& c)')
assert 'Finish(' not in record_upload + flush_uploads + copy

if '--source-only' in sys.argv:
    print('PASS: source-bound behavior and flush ordering (C++ harness not run)')
    sys.exit(0)

# Extract real CopyBuffer (including main) and batch methods. Replace only external dependencies.
copy_tail = copy[copy.index('    static constexpr VkMemoryBarrier READ_BARRIER'):]
copy_tail = copy_tail.replace('boost::container::small_vector<VkBufferCopy, 8>', 'std::vector<VkBufferCopy>')
copy_tail = copy_tail.replace('std::ranges::transform(copies, vk_copies.begin(), MakeBufferCopy);',
                              'std::copy(copies.begin(), copies.end(), vk_copies.begin());')
clean_header = '\n'.join(l for l in header.splitlines() if not l.startswith('#'))

# The scheduler's production batching and RecordWithUploadBuffer template run with a chunk double.
scaffold = r'''
namespace Vulkan {
struct Scheduler {
 std::unique_ptr<UploadBatch> upload_batch=std::make_unique<UploadBatch>(); bool uploads_pending=false;
 std::vector<std::function<void()>> commands;
 struct Chunk {Scheduler* owner; template<class T> bool Record(T& c) {
   owner->commands.push_back([c]{c(vk::CommandBuffer{},vk::CommandBuffer{});}); return true; }};
 Chunk storage{this}; Chunk* chunk=&storage;
 void DispatchWork() { if(uploads_pending) FlushUploads(); }
 void Execute() { DispatchWork(); for(auto& c:commands)c(); commands.clear(); }
 void RequestOutsideRenderPassOperationContext() {}
 void RecordUpload(VkBuffer,VkBuffer,std::span<const VkBufferCopy>);
 void FlushUploads();
 template<class T>
''' + record_with + r'''
 template<class T> void Record(T&& c) {RecordWithUploadBuffer([c](auto cb,auto){c(cb);});}
};
''' + record_upload + '\n' + flush_uploads + r'''
struct Runtime {
 Scheduler scheduler;
 struct Pool {int StreamBuf(){return 1;}} staging_pool;
 void CopyBuffer(int dst_buffer,int src_buffer,std::span<const VkBufferCopy> copies,bool barrier,bool can_reorder_upload=false) {
''' + copy_tail + r'''
};
}
int main() {
 using namespace Vulkan;
 for(int i=1;i<5;++i) {vk::memory[i].resize(2048); for(int j=0;j<2048;++j)vk::memory[i][j]=(i+j)%256;}
 Runtime r;
 for(size_t i=0;i<65;++i){VkBufferCopy c{i*4,i*4,4};r.CopyBuffer(2,1,{&c,1},true);}
 r.scheduler.Execute();
 assert(vk::pairs==2 && vk::last_stage==7);
 assert(std::equal(vk::memory[1].begin(),vk::memory[1].begin()+260,vk::memory[2].begin()));
 VkBufferCopy first{0,0,8}, second{8,4,8};
 r.CopyBuffer(2,1,{&first,1},true); r.CopyBuffer(2,1,{&second,1},true);
 assert(r.scheduler.commands.size()==1 && r.scheduler.upload_batch->copies.size()==1);
 r.scheduler.Execute();
 assert(std::equal(vk::memory[1].begin()+8,vk::memory[1].begin()+16,vk::memory[2].begin()+4));
 std::vector<VkBufferCopy> many;
 for(size_t i=0;i<65;++i)many.push_back({i*4,i*4,4});
 r.CopyBuffer(2,1,many,true);
 assert(r.scheduler.commands.size()==1 && r.scheduler.upload_batch->copies.size()==1);
 r.scheduler.Execute();
 UploadBatch b; VkBufferCopy c{0,0,8}, adjacent{8,8,8}, overlap{8,4,8}; b.Add(1,2,{&c,1});
 assert(b.CanAdd(1,2,{&adjacent,1})); assert(!b.CanAdd(1,2,{&overlap,1}));
 assert(!b.CanAdd(2,3,{&c,1})); assert(!b.CanAdd(3,1,{&c,1})); // RAW / WAR
 for(auto mode:{0,1,2,3}) {
  r.CopyBuffer(2,1,{&c,1},true);
  if(mode==0) r.scheduler.Record([](auto){});
  if(mode==1) r.scheduler.RecordWithUploadBuffer([](auto,auto){});
  if(mode==2) r.scheduler.DispatchWork();
  if(mode==3) r.scheduler.Execute(); // source guard checks SubmitExecution flushes before NextTick
  assert(!r.scheduler.uploads_pending);r.scheduler.Execute();
 }
 for(auto src:{1,2,3}) {r.CopyBuffer(4,src,{&c,1},src!=1);assert(!r.scheduler.uploads_pending);r.scheduler.Execute();}
 r.CopyBuffer(2,1,{&c,1},true,true);assert(!r.scheduler.uploads_pending);r.scheduler.Execute();
}
'''
with tempfile.TemporaryDirectory(prefix='upload-batch-') as d:
    cpp = Path(d) / 'test.cpp'
    cpp.write_text(prelude + clean_header + scaffold)
    subprocess.run(['g++', '-std=c++20', '-O1', '-Wall', '-Wextra', str(cpp), '-o', str(Path(d)/'test')], check=True)
    subprocess.run([str(Path(d)/'test')], check=True)
print('PASS: extracted UploadBatch, CopyBuffer and scheduler recording harness')
