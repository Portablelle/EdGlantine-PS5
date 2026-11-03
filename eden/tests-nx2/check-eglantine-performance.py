"""Exercise the actual patched GC and buffer methods; compile only on dedie."""
from pathlib import Path
import os
import platform
import subprocess
import sys
import tempfile

assert platform.system() == 'Linux', 'Compile on dedie'
root = Path(__file__).resolve().parents[1]
scratch = Path((root / '.local/headless-cache').read_text().strip())
source = scratch / 'source/src'

def method(text, name):
    start = text.index('void TextureCache<P>::' + name) if name == 'RunGarbageCollector' else text.index(name)
    begin = text.index('{', start)
    depth = 1
    end = begin + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]

gc = method((source / 'video_core/texture_cache/texture_cache.h').read_text(), 'RunGarbageCollector')
generated = '--generated' in sys.argv
if generated:
    gc = method((scratch / 'native-local/headless/vulkan-cache/video_core/texture_cache/texture_cache.h').read_text(), 'RunGarbageCollector')
buffer = (source / 'video_core/buffer_cache/buffer_cache.h').read_text()
bind = method(buffer, 'void BufferCache<P>::BindGraphicsUniformBuffer')
disable = method(buffer, 'void BufferCache<P>::DisableGraphicsUniformBuffer')
find = method(buffer, 'BufferId BufferCache<P>::FindBuffer')
cpp = r'''
#include <algorithm>
#include <array>
#include <atomic>
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <optional>
#include <vector>
#include <unordered_map>
#include "common/lru_cache.h"
namespace boost::container {template<class T,size_t N>using small_vector=std::vector<T>;}
template<class F>struct Exit {F f;~Exit(){f();}};
struct ExitMaker {template<class F>auto operator+(F f){return Exit<F>{f};}};
#define SCOPE_EXIT const auto scope_exit = ExitMaker{} + [&]()
namespace Eden::Performance {
 struct Timer {Timer(int,size_t=0){}};
 inline std::atomic<bool> vulkan_cost_enabled{false},texture_budget_log{false},gc_count_visits{false},gc_keep_dirty{false},graphics_memory_short{false};
 inline int vulkan_api[32]{},gc_unbatched_drain{},gc_batched_drain{};
 bool KeepDirtyTextures(){return gc_keep_dirty.load();}
}
using DAddr=u64;using GPUVAddr=u64;using BufferId=unsigned;using ImageId=unsigned;
constexpr u64 operator""_MiB(unsigned long long n){return n*1024*1024;}
bool True(unsigned x){return x!=0;}bool False(unsigned x){return !x;}
#define LOG_INFO(...) ((void)0)
namespace VideoCommon::Nx2Profile {bool Enabled(){return false;}}
enum ImageFlagBits {IsDecoding=1, BadOverlap=2, CostlyLoad=4, Tracked=8};
inline std::vector<unsigned> download_order,delete_order;
struct Image {struct Block {u64 block{},block_size{},size{};};Block block{};
 Block MemoryBlock()const{return block;}
 unsigned flags{};u64 unswizzled_size_bytes{},guest_size_bytes{},gpu_addr{},scale_tick{},lru_index{};
 int info{};bool downloadable=false,deleted=false;size_t lru{};
 template<class...T>void DownloadMemory(T&&...){download_order.push_back(unsigned(gpu_addr));};};
struct Map {int mapped_span{};};struct Runtime {unsigned downloads{},finishes{};
 Map DownloadStagingBuffer(u64,bool=false){++downloads;return {};};void Finish(){++finishes;}
 void FreeDeferredStagingBuffer(Map&){};};
namespace Vulkan {using TextureCacheRuntime=::Runtime;}
int FullDownloadCopies(int){return 0;}int FixSmallVectorADL(int x){return x;}
template<class...T>void SwizzleImage(T&&...){}
struct Traits {using ObjectType=ImageId;using TickType=u64;};
struct Images {
 std::vector<Image> data=std::vector<Image>(6000);
 Image&operator[](size_t i){return data[i];}
 struct Iterator {Images* owner;size_t index;
  auto operator*()const{return std::pair{unsigned(index),&owner->data[index]};}
  Iterator&operator++(){++index;return *this;}
  bool operator!=(const Iterator&other)const{return index!=other.index;}};
 Iterator begin(){return {this,0};}Iterator end(){return {this,data.size()};}
};
struct TextureMemory {bool native=false;bool UsesNativeTiling()const{return native;}};
template<class P>struct TextureCache {
 using Runtime=::Runtime;
 u64 ReclaimableImageBytes(const Image&){return 10;}
 bool IsDownloadable(const Image&i){return i.downloadable;}
 void UntrackImage(Image&,ImageId){}
 void UnregisterImage(ImageId i){total_used_memory-=10;}
 void DeleteImage(ImageId i,bool){delete_order.push_back(i);slot_images[i].deleted=true;lru_cache.Free(slot_images[i].lru);}
 void Add(unsigned i,u64 tick,unsigned flags=CostlyLoad,bool downloadable=false){
  slot_images[i].gpu_addr=i;slot_images[i].flags=flags;slot_images[i].downloadable=downloadable;
  slot_images[i].lru_index=tick;slot_images[i].lru=lru_cache.Insert(i,tick);total_used_memory+=10;}
 void RunGarbageCollector();
 u64 block_fill_tick=~0ULL;std::unordered_map<u64,u64>block_image_bytes;
 u64 total_used_memory{},expected_memory=15,critical_memory=1000,frame_tick=4000;
 unsigned gc_download_deletes{},gc_costly_deletes{},gc_deletes{};
 TextureMemory memory{},*gpu_memory=&memory;int swizzle_data_buffer{};Runtime runtime;
 Images slot_images;Common::LeastRecentlyUsedCache<Traits>lru_cache;
};
namespace Settings {bool IsGPUFenceBehaviorAccurate(){return false;}}
struct Binding {DAddr device_addr{};u32 size{};BufferId buffer_id{};
 inline static unsigned assignments{};
 Binding&operator=(const Binding&other){++assignments;device_addr=other.device_addr;size=other.size;buffer_id=other.buffer_id;return *this;}};
constexpr Binding NULL_BINDING{};constexpr BufferId NULL_BUFFER_ID=0;
struct Buffer {bool IsInBounds(u64,u32){return true;}bool IsSparseCompatible(){return true;}};
struct Memory {std::optional<DAddr>address=32;std::optional<DAddr>GpuToCpuAddress(GPUVAddr){return address;}};
template<class P>struct BufferCache {
 static constexpr unsigned CACHING_PAGEBITS=32;
 struct State {std::array<std::array<Binding,4>,2>uniform_buffers{};}state,*channel_state=&state;
 Memory memory,*gpu_memory=&memory;std::array<BufferId,16>page_table{};std::array<Buffer,4>slot_buffers{};
 unsigned creates{};BufferId CreateBuffer(DAddr,u32,bool){++creates;return 2;}
 void SynchronizeBufferWrites(Buffer&){}
 void BindGraphicsUniformBuffer(size_t,u32,GPUVAddr,u32);
 void DisableGraphicsUniformBuffer(size_t,u32);
 BufferId FindBuffer(DAddr,u32,bool);
};
'''
cpp += '\ntemplate<class P>\n' + gc + '\n'
cpp += '#define NATIVE_GC '+str(int(generated))+'\n'
for body in (bind, disable, find):
    cpp += '\ntemplate<class P>\n' + body + '\n'
cpp += r'''
int main(int argc,char**argv){
 const std::string mode=argc>1?argv[1]:"default";
 TextureCache<int> c;
 if(mode=="disabled"||mode=="minimum"){
  c.Add(0,100);c.Add(1,101);c.RunGarbageCollector();
  assert(!c.slot_images[0].deleted&&!c.slot_images[1].deleted);
 }else{
  // Over expected use: retire an old costly image, preserve the recently used one.
  c.Add(0,100);c.Add(1,3900);c.RunGarbageCollector();
  assert(c.slot_images[0].deleted&&!c.slot_images[1].deleted&&c.gc_costly_deletes==1);
  // Prefer draining an emptier allocation block, without changing eligibility.
  TextureCache<int> blocks;blocks.memory.native=true;blocks.expected_memory=25;
  for(unsigned i=0;i<3;++i)blocks.Add(i,100+i);
  blocks.slot_images[0].block={1,20,10};blocks.slot_images[1].block={1,20,10};
  blocks.slot_images[2].block={2,1000,10};blocks.RunGarbageCollector();
  assert(blocks.slot_images[2].deleted&&!blocks.slot_images[0].deleted&&!blocks.slot_images[1].deleted);
#if NATIVE_GC
  download_order.clear();delete_order.clear();
  TextureCache<int> sorted;sorted.memory.native=true;sorted.expected_memory=1;
  for(unsigned i=0;i<25;++i){sorted.Add(i,100+i,CostlyLoad,true);sorted.slot_images[i].block={i+1,1000+i*100,10};}
  sorted.RunGarbageCollector();assert(delete_order.size()==20&&download_order==delete_order);
#endif
  // Below expected use and while decoding, the old protection remains.
  TextureCache<int> below;below.Add(0,100);below.RunGarbageCollector();assert(!below.slot_images[0].deleted);
  TextureCache<int> decode;decode.Add(0,100,CostlyLoad|IsDecoding);decode.Add(1,3900);
  decode.RunGarbageCollector();assert(!decode.slot_images[0].deleted);
  // Don't continue deleting costly images after recovering the expected budget.
  TextureCache<int> stop;stop.expected_memory=25;
  stop.Add(0,100);stop.Add(1,101);stop.Add(2,102);stop.RunGarbageCollector();
  assert(stop.slot_images[0].deleted&&!stop.slot_images[1].deleted&&!stop.slot_images[2].deleted);
  // Downloadable old images retain the download/finish before deletion.
  TextureCache<int> dirty;dirty.Add(0,100,CostlyLoad|Tracked,true);dirty.Add(1,3900);
  dirty.RunGarbageCollector();assert(dirty.slot_images[0].deleted&&dirty.runtime.downloads==1&&dirty.runtime.finishes==1);
  // A clean eviction can restore the budget before the next costly dirty image.
  TextureCache<int> relief;relief.Add(0,100);relief.Add(1,101,CostlyLoad,true);
  relief.RunGarbageCollector();assert(relief.slot_images[0].deleted&&!relief.slot_images[1].deleted);
  assert(relief.runtime.downloads==0&&relief.runtime.finishes==0);
  // The per-pass work limit is preserved.
  TextureCache<int> many;many.expected_memory=1;
  for(unsigned i=0;i<40;++i)many.Add(i,100+i);
  many.RunGarbageCollector();assert(many.gc_costly_deletes==20);
  // A newly started session must not underflow the additional old-age pass.
  TextureCache<int> young;young.frame_tick=100;young.Add(0,0);young.Add(1,1);
  young.RunGarbageCollector();assert(!young.slot_images[0].deleted);
#if NATIVE_GC
  // The native scan still reaches reclaimable images behind protected ones.
  TextureCache<int> skipped;skipped.expected_memory=1;
  for(unsigned i=0;i<25;++i)skipped.Add(i,100+i,CostlyLoad|IsDecoding);
  skipped.Add(25,200);skipped.RunGarbageCollector();assert(skipped.slot_images[25].deleted);
  // Native dirty-texture retention must also hold in the extra old-image pass.
  Eden::Performance::gc_keep_dirty=true;
  TextureCache<int> kept;kept.Add(0,100,CostlyLoad,true);kept.Add(1,3900);
  kept.RunGarbageCollector();assert(!kept.slot_images[0].deleted&&kept.runtime.downloads==0);
  // Old protected dirty images must not consume the normal pass's scan allowance.
  TextureCache<int> blocked;blocked.expected_memory=1;blocked.critical_memory=100000;
  for(unsigned i=0;i<5000;++i)blocked.Add(i,100,CostlyLoad,true);
  blocked.Add(5000,3900,0);blocked.RunGarbageCollector();
  assert(blocked.slot_images[5000].deleted&&blocked.gc_deletes==1);
  assert(blocked.runtime.downloads==0&&!blocked.slot_images[0].deleted);
  Eden::Performance::gc_keep_dirty=false;
#endif
 }
 BufferCache<int>b;b.memory.address=std::nullopt;b.state.uniform_buffers[0][0]={1,16,1};
 b.BindGraphicsUniformBuffer(0,0,32,16);assert(b.state.uniform_buffers[0][0].device_addr==0);
 b.memory.address=64;b.BindGraphicsUniformBuffer(1,2,32,16);
 assert(b.state.uniform_buffers[1][2].device_addr==64&&b.state.uniform_buffers[1][2].size==16);
 const auto assignments=Binding::assignments;
 b.DisableGraphicsUniformBuffer(1,2);assert(Binding::assignments==assignments+1);
 b.DisableGraphicsUniformBuffer(1,2);assert(Binding::assignments==assignments+1);
 assert(b.state.uniform_buffers[1][2].size==0&&!b.state.uniform_buffers[1][2].buffer_id);
 constexpr u64 end=u64{1}<<36;
 for(auto addr:std::array<u64,4>{0,end,end+1,std::numeric_limits<u64>::max()})assert(b.FindBuffer(addr,16,false)==0);
 assert(b.FindBuffer(end-8,16,false)==0&&b.creates==0);
 assert(b.FindBuffer(end-16,16,false)==2&&b.creates==1);
 std::cout<<"EGLANTINE_PERFORMANCE_CONTRACT_PASS "<<mode<<" native="<<NATIVE_GC<<"\n";
}
'''
with tempfile.TemporaryDirectory(prefix='eglantine-perf-') as td:
    temp = Path(td)
    (temp / 'check.cpp').write_text(cpp)
    subprocess.run(['c++', '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
                    '-fno-omit-frame-pointer', '-I'+str(source), str(temp/'check.cpp'),
                    '-o', str(temp/'check')], check=True)
    for mode, age, minimum in [('default', '1800', '0'), ('disabled', '0', '0'),
                                ('minimum', '1800', '10000')]:
        subprocess.run([str(temp/'check'), mode], check=True,
                       env={**os.environ, 'EDEN_NX2_TC_OLD_AGE':age, 'EDEN_NX2_TC_MIN_AGE':minimum})
