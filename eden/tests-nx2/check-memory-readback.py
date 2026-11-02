"""Run on dedie after native configure: extracted production accounting/read queries."""
from pathlib import Path
import platform, subprocess
assert platform.system() == 'Linux', 'Compile only on dedie'
r=Path(__file__).resolve().parents[1]
scratch=Path((r/'.local/headless-cache').read_text().strip())
src=scratch/'source/src'; generated=scratch/'native-local/headless'
def function(text,signature):
 a=text.index(signature);b=text.index('{',a);end=b+1;depth=1
 while depth:
  depth+=(text[end]=='{')-(text[end]=='}');end+=1
 return text[a:end]+'\n'
common=r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <optional>
#include <set>
#include <mutex>
#include <vector>
using u64=uint64_t;using u32=uint32_t;using s32=int32_t;using DAddr=u64;using VAddr=u64;
namespace Common {template<class T> T AlignDown(T n,u64 a){return n/a*a;}template<class T>T AlignUp(T n,u64 a){return (n+a-1)/a*a;}}
namespace Core {constexpr u64 DEVICE_PAGESIZE=4096;}
'''
# The generated PS5 query, including the ImagePages optimization and real lock order.
text=(generated/'vulkan_rasterizer.cpp').read_text()
query=function(text,'VideoCore::RasterizerDownloadArea RasterizerVulkan::GetFlushArea(')
code=common+r'''
namespace VideoCore {struct RasterizerDownloadArea{u64 start_address,end_address;bool preemtive;};}
using Area=VideoCore::RasterizerDownloadArea;
std::vector<int> order;
namespace Eden {namespace Performance {constexpr int guest_cpu_read=0;struct Timer{Timer(int){}};void GuestCacheLock(std::mutex& m){m.lock();}}
namespace ImagePages {bool never=true;bool NeverHeld(u64,u64){return never;}}}
struct Cache{std::mutex mutex;bool flush=true;int kind=0,calls=0;std::optional<Area> area;
 bool FlushesOnCpuRead(){return flush;}auto GetFlushArea(u64,u64){++calls;order.push_back(kind);return area;}};
struct RasterizerVulkan {Cache texture_cache,buffer_cache;RasterizerVulkan(){texture_cache.kind=2;buffer_cache.kind=1;}
 Area GetFlushArea(DAddr,u64);};
'''+query+r'''
int main(){
 for(bool dirty_buffer:{false,true})for(bool has_texture:{false,true})for(bool dirty_texture:{false,true}){
  RasterizerVulkan r;order.clear();Eden::ImagePages::never=!has_texture;
  r.buffer_cache.area=Area{0x1000,0x3000,!dirty_buffer};
  r.texture_cache.area=Area{0x1000,0x10000,!dirty_texture};
  auto a=r.GetFlushArea(0x10ff,4096);
  assert(a.start_address==0x1000&&a.end_address==0x3000);
  assert(a.preemtive==!(dirty_buffer||(has_texture&&dirty_texture)));
  assert(r.buffer_cache.calls==1);assert(r.texture_cache.calls==int(has_texture));
  assert(order.front()==1);if(has_texture)assert(order.back()==2);
 }
 RasterizerVulkan r;Eden::ImagePages::never=true;r.buffer_cache.flush=false;
 assert(r.GetFlushArea(0x1000,8).preemtive);assert(r.buffer_cache.calls==0);
}
'''
out=r/'build/nx2-tests/memory-readback';out.mkdir(parents=True,exist_ok=True)
def run(name,code):
 p=out/(name+'.cpp');p.write_text(code)
 subprocess.run(['clang++-18','-std=c++20','-O1','-g','-fsanitize=address,undefined',str(p),'-o',str(out/name)],check=True)
 subprocess.run([str(out/name)],check=True)
 print(name+': PASS (ASan/UBSan)',flush=True)
run('rasterizer-read-query',code)
# Actual Memory read gate: NX2 slow reads stay coherent with reactive flushing off.
memory=(src/'core/memory.cpp').read_text()
code=common+r'''
namespace Settings {bool nx2=false;bool CurrentProgramIsSwitch2(){return nx2;}
struct{struct{bool value=false;bool GetValue(){return value;}}use_reactive_flushing;}values;}
struct MemoryImpl{struct{void* fastmem_arena=nullptr;}table;decltype(table)* current_page_table=&table;int downloads=0;
 void HandleRasterizerDownload(VAddr,size_t){++downloads;}
'''+function(memory,'void HandleRasterizerReadDownload(')+r'''};
int main(){for(bool nx2:{false,true})for(bool fast:{false,true})for(bool reactive:{false,true}){
 Settings::nx2=nx2;Settings::values.use_reactive_flushing.value=reactive;MemoryImpl m;m.table.fastmem_arena=fast?&m:nullptr;
 m.HandleRasterizerReadDownload(0x1000,8);assert(m.downloads==int(reactive||(nx2&&!fast)));
}}
'''
run('memory-read-gate',code)
# BufferCache's production read classification, write notification and fence policy.
h=(src/'video_core/buffer_cache/buffer_cache.h').read_text();base=(src/'video_core/buffer_cache/buffer_cache_base.h').read_text()
code=common+r'''
namespace VideoCore {struct RasterizerDownloadArea{u64 start_address,end_address;bool preemtive;};}
struct Tracker{bool dirty=false;std::set<u64> pages;bool IsRegionPreflushable(u64 a,u64 n){for(u64 p=a/4096*4096;p<a+n;p+=4096)if(pages.contains(p))return true;return false;}
 void MarkRegionAsPreflushable(u64 a,u64 n){for(u64 p=a;p<a+n;p+=4096)pages.insert(p);}void MarkRegionAsGpuModified(u64,u64){dirty=true;}};
struct Ranges{int adds=0;void Add(u64,u64){++adds;}};
struct Buffer{void setWriteTick(u64){}};using BufferId=int;
template<class P>struct BufferCache{static constexpr bool IS_OPENGL=false;
 bool async=false;Tracker memory_tracker;Ranges gpu_modified_ranges,uncommitted_gpu_modified_ranges;
 std::array<Buffer,1> slot_buffers;struct{u64 CurrentTick(){return 1;}}runtime;
 bool AsyncBufferDownloads()const{return async;}
 bool IsRegionGpuModified(u64,u64){return memory_tracker.dirty;}
 std::optional<VideoCore::RasterizerDownloadArea> GetFlushArea(DAddr,u64);
 void MarkWrittenBuffer(BufferId,DAddr,u32,bool);
'''+function(base,'bool DownloadsAtFence(')+function(base,'bool FlushesOnCpuRead(')+'};\n'
for sig in ['std::optional<VideoCore::RasterizerDownloadArea> BufferCache<P>::GetFlushArea(', 'void BufferCache<P>::MarkWrittenBuffer(']:code+='template<class P>\n'+function(h,sig)
code+=r'''
int main(){
 BufferCache<int> c;c.MarkWrittenBuffer(0,0x1000,64,true);
 assert(c.uncommitted_gpu_modified_ranges.adds==0);
 // First CPU read asks for a synchronous download and learns the range.
 auto a=c.GetFlushArea(0x1010,8);assert(!a->preemtive&&c.memory_tracker.IsRegionPreflushable(0x1000,4096));
 c.memory_tracker.dirty=false; // synchronous DownloadMemory published the first write
 c.MarkWrittenBuffer(0,0x1000,64,true);assert(c.uncommitted_gpu_modified_ranges.adds==1);
 // A cached/preflushable read relies on the normal fence copy of later writes.
 assert(c.GetFlushArea(0x1010,8)->preemtive);
 BufferCache<int> mixed;mixed.memory_tracker.pages.insert(0x1000);mixed.memory_tracker.dirty=true;
 assert(!mixed.GetFlushArea(0x1ff0,32)->preemtive);
 assert(mixed.memory_tracker.pages.contains(0x2000));
 BufferCache<int> all;all.async=true;all.MarkWrittenBuffer(0,0x1000,64,false);
 assert(all.uncommitted_gpu_modified_ranges.adds==1&&!all.FlushesOnCpuRead());
}
'''
run('buffer-read-fences',code)
# Actual backend-aware image helpers: no phantom gigabytes for unbacked textures.
t=(src/'video_core/texture_cache/texture_cache.h').read_text()
code=common+r'''
enum ImageFlagBits{Unbacked=1,AcceleratedUpload=2,Converted=4};bool True(int x){return x!=0;}
bool IsPixelFormatASTC(int f){return f==1;}
struct Image {int flags=0;struct{int format=0;}info;u64 guest_size_bytes=0,unswizzled_size_bytes=0;bool scaled=false;bool HasScaled()const{return scaled;}};
template<class P>struct TextureCache {u64 ImageMemoryBytes(const Image&)const;u64 ReclaimableImageBytes(const Image&);
 u64 GetScaledImageSizeBytes(const Image&){return 8192;}};
u64 TranscodedAstcSize(u64 n,int){return n*4;}
'''
for sig in ['u64 TextureCache<P>::ImageMemoryBytes(', 'u64 TextureCache<P>::ReclaimableImageBytes(']:code+='template<class P>\n'+function(t,sig)
# Use the exact deletion accounting expression and GC's actual saturated lookahead.
a=t.index('    total_used_memory -= (std::min)(total_used_memory, ReclaimableImageBytes(');b=t.index('\n',a)
delete=t[a:b].replace('slot_images[image_id]','image').replace('ReclaimableImageBytes(', 'cache.ReclaimableImageBytes(')
gc=(r/'headless/vulkan_gc_downloads.inc').read_text();a=gc.index('                usage -=');b=gc.index('\n',a)
lookahead=gc[a:b].replace('ReclaimedBytes(image)','cache.ReclaimableImageBytes(image)')
code+='int main(){TextureCache<int> cache;Image image;image.guest_size_bytes=3ULL<<30;image.flags=Unbacked;assert(cache.ImageMemoryBytes(image)==0);\n'
code+='image.flags=0;image.guest_size_bytes=1025;image.unswizzled_size_bytes=2050;assert(cache.ImageMemoryBytes(image)==3072);image.info.format=1;image.flags=AcceleratedUpload;assert(cache.ImageMemoryBytes(image)==9216);\n'
code+='image.scaled=true;assert(cache.ReclaimableImageBytes(image)==17408);u64 total_used_memory=64,usage=64;\n'+delete+'\n'+lookahead+'\nassert(total_used_memory==0&&usage==0);}\n'
run('image-accounting',code)
# Production budget getters, with recorded heaps and VMA allocation statistics.
d=(src/'video_core/vulkan_common/vulkan_device.cpp').read_text()
code=common+r'''
constexpr size_t VK_MAX_MEMORY_HEAPS=4;constexpr int VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_MEMORY_BUDGET_PROPERTIES_EXT=1;
struct VkPhysicalDeviceMemoryBudgetPropertiesEXT{int sType;void* pNext;u64 heapUsage[4]{},heapBudget[4]{};};
struct VmaStatistics{u64 blockBytes=0,allocationBytes=0;};struct VmaBudget{VmaStatistics statistics;};
std::array<VmaBudget,4> allocation_stats;
void vmaGetHeapBudgets(void*,VmaBudget* p){std::copy(allocation_stats.begin(),allocation_stats.end(),p);}
struct Physical{VkPhysicalDeviceMemoryBudgetPropertiesEXT data{};void GetMemoryProperties(VkPhysicalDeviceMemoryBudgetPropertiesEXT* p)const{*p=data;}};
struct Device {struct{bool memory_budget=true;}extensions;Physical physical;void* allocator=this;std::vector<size_t> valid_heap_memory{0,1};size_t main_heap=0;
 u64 GetDeviceMemoryUsage()const;u64 GetDeviceMemoryBudget()const;};
'''+function(d,'u64 Device::GetDeviceMemoryUsage() const')+function(d,'u64 Device::GetDeviceMemoryBudget() const')+r'''
int main(){Device d;d.physical.data.heapBudget[0]=8192;d.physical.data.heapBudget[1]=8192;
 d.physical.data.heapUsage[0]=6000;d.physical.data.heapUsage[1]=700;
 allocation_stats[0].statistics={1000,800};allocation_stats[1].statistics={900,0};
 // The second heap's unused blocks cannot subtract from the first heap's usage.
 assert(d.GetDeviceMemoryUsage()==5800);assert(d.GetDeviceMemoryBudget()==8192);
 allocation_stats[1].statistics={700,500};assert(d.GetDeviceMemoryUsage()==6300);assert(d.GetDeviceMemoryBudget()==8692);
 d.main_heap=1;assert(d.GetDeviceMemoryBudget()==13992);
 d.allocator=nullptr;assert(d.GetDeviceMemoryUsage()==6700);assert(d.GetDeviceMemoryBudget()==14192);
 d.extensions.memory_budget=false;assert(d.GetDeviceMemoryBudget()==0);
}
'''
run('vram-heaps',code)
print('PASS: production PS5 read query, selective fence downloads, image deletion/lookahead and per-heap VRAM accounting. No PS5 visual result claimed.')
