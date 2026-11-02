"""dedie only: exercise the real gather cache and write-publication methods.

The recording backend replaces Vulkan allocation/encoding, not cache decisions.
No claim about PS5 driver behavior follows from this test.
"""
from pathlib import Path
import platform
import subprocess
import os

assert platform.system() == 'Linux', 'Run on dedie only'
root = Path(__file__).resolve().parents[1]
source = Path((root / '.local/headless-cache').read_text().strip()) / 'source/src'
out = root / 'build/nx2-tests/gather-reuse'
out.mkdir(parents=True, exist_ok=True)


def function(text, signature):
    start = text.index(signature)
    end = text.index('{', start) + 1
    depth = 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end] + '\n'


cache = (source / 'video_core/renderer_vulkan/vk_multi_range_buffer.cpp').read_text()
runtime = (source / 'video_core/renderer_vulkan/vk_buffer_cache.cpp').read_text()
header = (source / 'video_core/renderer_vulkan/vk_multi_range_buffer.h').read_text()
entry = function(header, '    struct Entry {') + ';\n'
code = r'''
#include <algorithm>
#include <array>
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <limits>
#include <map>
#include <span>
#include <stdexcept>
#include <utility>
#include <vector>
using u32=uint32_t;using u64=uint64_t;using VkBuffer=u64;
using VkDeviceMemory=u64;using VkDeviceAddress=u64;using VkDeviceSize=u64;
using VkBufferUsageFlags=u32;
#define LOG_INFO(...) ((void)0)
constexpr u64 VK_NULL_HANDLE=0;
constexpr u32 VK_BUFFER_USAGE_TRANSFER_SRC_BIT=1,VK_BUFFER_USAGE_TRANSFER_DST_BIT=2,
 VK_BUFFER_USAGE_STORAGE_BUFFER_BIT=4,VK_BUFFER_USAGE_SHADER_DEVICE_ADDRESS_BIT=8,
 VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO=1,VK_SHARING_MODE_EXCLUSIVE=0;
struct VkBufferCreateInfo{u32 sType;void* pNext;u32 flags;u64 size;u32 usage,sharingMode,
 queueFamilyIndexCount;void* pQueueFamilyIndices;};
struct Handle{u64 id{};u64 operator*()const{return id;}explicit operator bool()const{return id!=0;}};
namespace vk{using Buffer=Handle;}
using SparseBuffer=Handle;
enum class MemoryUsage{DeviceLocal};
struct MemoryAllocator{u64 serial=100;Handle CreateBuffer(VkBufferCreateInfo,MemoryUsage){return {++serial};}};
struct Scheduler{std::vector<int> events;void BeforeNativeBufferWrite(u64,u64,u64){events.push_back(1);}};
struct Device{bool IsBufferDeviceAddressSupported()const{return true;}
 const Device& GetLogical()const{return *this;}u64 GetBufferDeviceAddress(u64 h)const{return h*4096;}};
struct MultiRangeSource{u64 handle{},memory{},memory_offset{},offset{},size{},write_tick{};u32 memory_type{};};
struct MultiRangeRef{u64 handle{},address{},size{};bool sparse{},needs_gather{};};
struct MultiRangeBufferCache{
'''+entry+r'''
 std::map<u64,Entry> entries;std::vector<int> retired;u64 write_epoch=1;bool use_sparse=false;
 u64 HashSources(std::span<const MultiRangeSource>)const;
 u64 HashContent(std::span<const MultiRangeSource>)const;
 bool CanBindSparse(std::span<const MultiRangeSource>)const{return use_sparse;}
 Handle CreateSparse(const Device&,Scheduler&,std::span<const MultiRangeSource>,u64){return {77};}
 void DrainRetired(Scheduler&){retired.clear();}
 void RetireEntry(Scheduler&,Entry&){retired.push_back(1);}
 MultiRangeRef Get(const Device&,Scheduler&,MemoryAllocator&,u64,std::span<const MultiRangeSource>,u64);
 void MarkGathered(u64);void Invalidate(u64);void InvalidateAll();void DropOwner(Scheduler&,VkBuffer);
};
namespace Eden::Performance{
 struct Counter{u64 n=0;void fetch_add(u64 x,std::memory_order){n+=x;}};
 inline Counter storage_scatter_bytes,storage_scatter_calls,storage_gather_bytes,
 storage_gather_calls,storage_reused_bytes,storage_reused_calls;
}
namespace VideoCommon{struct BufferCopy{u64 src_offset,dst_offset;size_t size;};}
struct Buffer{u64 handle=1;u64 Handle()const{return handle;}};
namespace Shader{using RuntimeError=std::runtime_error;}
struct BufferCacheRuntime{
 Scheduler scheduler;MultiRangeBufferCache multi_range_buffers;
 Device device;MemoryAllocator memory_allocator;
 std::vector<MultiRangeSource> multi_range_sources;u64 multi_range_total=0;bool grouped_storage=true;
 struct{void AddBuffer(u64,u64,u64,u64){}}guest_descriptor_queue;
 u64 GetStorageBufferAlignment(){return 1;}
 struct Batch{u64 key;MultiRangeRef ref;std::vector<MultiRangeSource> sources;bool written;};
 std::vector<Batch> storage_batch;bool pending_storage_writes=false;
 void PreCopyBarrier(){scheduler.events.push_back(2);}void PostCopyBarrier(){scheduler.events.push_back(4);}
 void CopyBuffer(u64,u64,std::span<const VideoCommon::BufferCopy>,bool,bool=false,bool is_gather=false){
  scheduler.events.push_back(3);if(!is_gather)multi_range_buffers.InvalidateAll();}
 void MarkBufferWritten(const Buffer&,u64,u64);void FlushStorageWrites();
 bool BindMultiRangeStorageBuffer(u64,bool,u32=0,u32=0);
};
'''
for signature in ['u64 MultiRangeBufferCache::HashSources(',
                  'u64 MultiRangeBufferCache::HashContent(',
                  'MultiRangeRef MultiRangeBufferCache::Get(',
                  'void MultiRangeBufferCache::MarkGathered(',
                  'void MultiRangeBufferCache::InvalidateAll(',
                  'void MultiRangeBufferCache::Invalidate(',
                  'void MultiRangeBufferCache::DropOwner(']:
    code += function(cache, signature)
for signature in ['void BufferCacheRuntime::MarkBufferWritten(',
                  'void BufferCacheRuntime::FlushStorageWrites(',
                  'bool BufferCacheRuntime::BindMultiRangeStorageBuffer(']:
    code += function(runtime, signature)
code += r'''
int main(){
 Device d;MemoryAllocator a;BufferCacheRuntime r;
 std::array src{MultiRangeSource{.handle=1,.offset=0,.size=32,.write_tick=7},
                MultiRangeSource{.handle=2,.offset=32,.size=32,.write_tick=7}};
 auto get=[&](u64 key){return r.multi_range_buffers.Get(d,r.scheduler,a,key,src,64);};
 auto gather=[&](u64 key){auto ref=get(key);if(ref.needs_gather)r.multi_range_buffers.MarkGathered(key);return ref.needs_gather;};
 if(const char* value=std::getenv("EDEN_NX2_GATHER_REUSE");value&&value[0]=='0'){
  for(int i=0;i<1000;++i)assert(gather(1)&&gather(2));
  puts("Conservative A/B fallback: 2000 gathers, no snapshot reuse: PASS");return 0;}
 assert(get(1).needs_gather);assert(gather(1));assert(!get(1).needs_gather);
 // Different keys over the same physical sources must both be invalidated.
 assert(gather(2));r.multi_range_buffers.InvalidateAll();assert(get(1).needs_gather&&get(2).needs_gather);
 assert(gather(1));assert(gather(2));
 // Reproduce the old ordering defect: binding invalidates, a later binding
 // gathers, then the shader writes. The scheduler/write ticks have not changed.
 r.MarkBufferWritten(Buffer{},0,32);assert(gather(2));assert(!get(2).needs_gather);
 r.FlushStorageWrites();assert(get(2).needs_gather);assert(!r.pending_storage_writes);
 assert(gather(1));assert(gather(2));r.FlushStorageWrites();assert(!get(1).needs_gather&&!get(2).needs_gather);
 // Read-only sequences need only one gather per group, not one per draw.
 r.multi_range_buffers.InvalidateAll();u64 gathers=0;
 for(int draw=0;draw<1000;++draw){gathers+=gather(1);gathers+=gather(2);r.FlushStorageWrites();}
 assert(gathers==2);printf("Read-only fixture: %llu gathers instead of 2000\n",(unsigned long long)gathers);
 // Contents as well as decisions: aliases see the producer's next value even
 // when its binding gathered in the same tick before the write actually ran.
 u64 source_value=0,cached_value=0;
 for(int i=1;i<=100;++i){r.MarkBufferWritten(Buffer{},0,32);if(gather(2))cached_value=source_value;
  source_value=i;r.FlushStorageWrites();if(gather(2))cached_value=source_value;assert(cached_value==source_value);}
 // Individual invalidation, content stamps and changed geometry still work.
 r.multi_range_buffers.Invalidate(2);assert(gather(2));assert(!get(2).needs_gather);
 ++src[0].write_tick;assert(gather(2));++src[0].offset;auto old=get(2).handle;assert(gather(2));
 assert(get(2).handle==old);assert(!get(2).needs_gather);
 // Construct real FNV collisions: matching fingerprints must not bypass exact
 // geometry/content comparison. Each round step is (hash ^ word) * prime.
 auto prefix=[](u64 handle,u64 offset,u64 size){u64 h=0xcbf29ce484222325ULL;
  for(u64 value:{handle,offset,size})h=(h^value)*0x100000001b3ULL;return h;};
 auto original=src;assert(gather(5));auto handle=get(5).handle;
 src[0].handle^=0x1234;
 src[1].handle=prefix(src[0].handle,src[0].offset,src[0].size)^
               prefix(original[0].handle,original[0].offset,original[0].size)^original[1].handle;
 assert(r.multi_range_buffers.HashSources(src)==r.multi_range_buffers.HashSources(original));
 assert(get(5).needs_gather&&get(5).handle!=handle);assert(gather(5));
 auto old_content=r.multi_range_buffers.HashContent(src);u64 first=src[0].write_tick;
 src[0].write_tick^=0x5678;
 src[1].write_tick^=((0xcbf29ce484222325ULL^first)*0x100000001b3ULL)^
                    ((0xcbf29ce484222325ULL^src[0].write_tick)*0x100000001b3ULL);
 assert(r.multi_range_buffers.HashContent(src)==old_content);assert(gather(5));
 src=original;
 r.multi_range_buffers.DropOwner(r.scheduler,1);assert(get(2).needs_gather);
 // Sparse bindings are aliases, not copies: they never gather.
 r.multi_range_buffers.entries.clear();r.multi_range_buffers.use_sparse=true;
 assert(get(3).sparse&&!get(3).needs_gather);r.multi_range_buffers.InvalidateAll();assert(!get(3).needs_gather);
 // Generation wrap cannot resurrect an old snapshot.
 r.multi_range_buffers.use_sparse=false;r.multi_range_buffers.entries.clear();assert(gather(4));
 r.multi_range_buffers.write_epoch=std::numeric_limits<u64>::max();r.multi_range_buffers.InvalidateAll();assert(get(4).needs_gather);
 // Written multi-range groups scatter before the post-producer invalidation.
 r.storage_batch.push_back({4,get(4),{src.begin(),src.end()},true});r.MarkBufferWritten(Buffer{},0,32);
 auto epoch=r.multi_range_buffers.write_epoch;r.FlushStorageWrites();assert(r.multi_range_buffers.write_epoch>epoch);
 assert(r.storage_batch.empty()&&get(4).needs_gather);
 // Exercise the production binding path. Read-only groups allocate no per-draw
 // source vector; a later writable binding captures it before scattering.
 r.multi_range_sources.assign(src.begin(),src.end());r.multi_range_total=64;
 assert(r.BindMultiRangeStorageBuffer(10,false,0,32));assert(r.storage_batch.size()==1);
 assert(r.storage_batch[0].sources.empty()&&!r.storage_batch[0].written);
 r.MarkBufferWritten(Buffer{},0,32);assert(r.BindMultiRangeStorageBuffer(10,true,32,32));
 assert(r.storage_batch[0].sources.size()==2&&r.storage_batch[0].written);
 r.FlushStorageWrites();assert(r.storage_batch.empty());
 auto before=Eden::Performance::storage_gather_calls.n;
 for(int i=0;i<1000;++i){assert(r.BindMultiRangeStorageBuffer(11,false,0,32));
  assert(r.BindMultiRangeStorageBuffer(12,false,0,32));
  for(const auto& batch:r.storage_batch)assert(batch.sources.empty());r.FlushStorageWrites();}
 assert(Eden::Performance::storage_gather_calls.n-before==2);
 puts("Gather cache aliases, same-tick producers, post-write publication, content/geometry changes, sparse and wrap: PASS");
}
'''
# Confirm copy/fill invalidation and the private-gather exception are wired into
# the real runtime; the native build also type-checks these Vulkan paths.
copy = function(runtime, 'void BufferCacheRuntime::CopyBuffer(')
clear = function(runtime, 'void BufferCacheRuntime::ClearBuffer(')
bind = function(runtime, 'bool BufferCacheRuntime::BindMultiRangeStorageBuffer(')
assert 'if (!is_gather) multi_range_buffers.InvalidateAll();' in copy
assert 'multi_range_buffers.InvalidateAll();' in clear
assert bind.count('CopyBuffer(ref.handle, source.handle, copy, false, false, true);') == 2
text = source / 'video_core/renderer_vulkan/vk_rasterizer.cpp'
draw = function(text.read_text(), 'void RasterizerVulkan::PrepareDraw(')
compute = function(text.read_text(), 'void RasterizerVulkan::DispatchCompute()')
assert draw.index('draw_func();') < draw.index('FlushStorageWrites();')
assert 'if (dispatched) buffer_cache.runtime.FlushStorageWrites();' in compute
path = out / 'gather.cpp'
path.write_text(code)
subprocess.run(['c++', '-std=c++20', '-O1', '-g', '-DEDEN_NX2_PS5_PROTO',
                '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                str(path), '-o', str(out / 'gather')], check=True)
subprocess.run([str(out / 'gather')], check=True)
subprocess.run([str(out / 'gather')], env={**os.environ, 'EDEN_NX2_GATHER_REUSE': '0'}, check=True)
