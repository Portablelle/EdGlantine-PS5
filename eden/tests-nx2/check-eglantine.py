"""Exercise production device mapping and ASTC layer selection with recording backends."""
from pathlib import Path
import subprocess
root = Path(__file__).resolve().parents[1]
source = Path((root / '.local/headless-cache').read_text().strip()) / 'source/src'
out = root / 'build/nx2-tests'
out.mkdir(parents=True, exist_ok=True)
def method(text, name):
    start = text.index(name)
    start = text.rfind('template <', 0, start)
    brace = text.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end] + '\n'
def run(name, code):
    path = out / (name + '.cpp')
    path.write_text(code)
    subprocess.run(['clang++-18','-std=c++20','-O1','-g','-fsanitize=address,undefined',
                    '-I'+str(source),str(path),'-o',str(out/name)],check=True)
    subprocess.run([str(out/name)],check=True)
text = (source/'core/device_memory_manager.inc').read_text()
code = r'''
#include <algorithm>
#include <array>
#include <atomic>
#include <cassert>
#include <cstring>
#include <memory>
#include <mutex>
#include <vector>
#include "common/scope_exit.h"
using u8=uint8_t; using u32=uint32_t; using u64=uint64_t;
using VAddr=u64; using DAddr=u64; using PAddr=u64;
namespace Common { using ProcessAddress=u64; template<class T> T AlignUp(T n,T a){return (n+a-1)&~(a-1);} }
namespace Core::Memory {
constexpr size_t YUZU_PAGESIZE=4096,YUZU_PAGEBITS=12,YUZU_PAGEMASK=4095;
struct Memory { std::array<u8,16*4096> bytes{}; u8* GetPointerSilent(u64 a){return a<bytes.size()?bytes.data()+a:nullptr;} };
}
namespace Memory=Core::Memory;
struct Asid { size_t id=0; };
template<class T> struct Table : std::array<T,32> {
 void CommitRegion(size_t,size_t) {} T& GetUnchecked(size_t n){return this->at(n);}
 T& GetAndFault(size_t n){return this->at(n);}
};
inline std::atomic<u64> device_translation_generation{1};  // device_memory_manager.inc: unique across instances
template<class Traits> struct DeviceMemoryManager {
 struct Entry {u64 cpu_backing_address=0;u32 continuity_tracker=0,compressed_physical_ptr=0;};
 Table<Entry> tracked_entries;
 Table<u32> compressed_device_addr{};
 Core::Memory::Memory memory;
 std::array<Core::Memory::Memory*,1> registered_processes{&memory};
 std::mutex mapping_guard;
 std::atomic<u64> translation_generation{};
 struct Interface { void InvalidateRegion(u64,size_t) {} } interface;
 Interface* device_inter=&interface;
 struct Multi { u32 Register(u32){return 0;} void Register(u32,u32){} std::pair<bool,u32> Unregister(u32,u32){return {false,0};} u32 ReleaseEntry(u32){return 0;} };
 struct Impl { Multi multi_dev_address; };
 std::unique_ptr<Impl> impl=std::make_unique<Impl>();
 static constexpr u32 MULTI_FLAG_BITS=31,MULTI_MASK=0x7fffffff,MULTI_FLAG=0x80000000;
 static constexpr size_t page_size=4096;
 u64 GetRawPhysicalAddr(u8* p){return p-memory.bytes.data();}
 template<class T> T* GetPointerFromRaw(u64 a){return reinterpret_cast<T*>(memory.bytes.data()+a);}
 void InsertCPUBacking(size_t p,u64 a,Asid){tracked_entries.at(p).cpu_backing_address=a;}
 void Map(DAddr,VAddr,size_t,Asid,bool);
 void Unmap(DAddr,size_t);
 void CutContinuityAt(size_t);
 void TrackContinuityImpl(DAddr,VAddr,size_t,Asid);
 void WalkBlock(DAddr,size_t,auto,auto,auto);
 std::vector<u8> Read(u64 address,size_t size) {
  std::vector<u8> result(size,0xee);size_t offset=0;
  WalkBlock(address,size,[&](size_t n,u64){std::memset(result.data()+offset,0,n);},
    [&](size_t n,u8* p){std::memcpy(result.data()+offset,p,n);},[&](size_t n){offset+=n;});
  return result;
 }
};
'''
for name in ('Map(', 'Unmap(', 'CutContinuityAt(', 'TrackContinuityImpl(', 'WalkBlock('):
    # Match definitions, not calls.
    code += method(text, 'DeviceMemoryManager<Traits>::'+name)
code += r'''
int main(){
 constexpr size_t P=4096;
 DeviceMemoryManager<int> m;
 for(size_t i=0;i<16;i++) std::memset(m.memory.bytes.data()+i*P,int(i+1),P);
 m.Map(2*P,0,6*P,{},true);
 assert(m.tracked_entries[2].continuity_tracker==5);
 m.Unmap(4*P,2*P);
 auto b=m.Read(2*P,6*P);
 for(size_t i=0;i<b.size();i++) assert(b[i]==(i/P==2||i/P==3?0:i/P+1));
 // Starting on the hole must not zero mapped pages that follow it.
 b=m.Read(4*P,4*P);assert(b[2*P]==5 && b[3*P]==6);
 m.Map(4*P,8*P,2*P,{},false);
 b=m.Read(2*P+P/2,5*P);
 assert(b[0]==1 && b[P/2]==2 && b[3*P/2]==9 && b[5*P/2]==10 && b[7*P/2]==5);
 // Remapping the middle of a tracked run directly must cut preceding pages too.
 DeviceMemoryManager<int> n;
 for(size_t i=0;i<16;i++) std::memset(n.memory.bytes.data()+i*P,int(i+1),P);
 n.Map(P,0,6*P,{},true);n.Map(3*P,10*P,P,{},false);
 b=n.Read(P,6*P);assert(b[2*P]==11 && b[3*P]==4);
 n.Map(3*P,100*P,P,{},false);b=n.Read(P,6*P);assert(b[2*P]==0 && b[3*P]==4);
 n.Unmap(0,0);n.CutContinuityAt(0);
}
'''
run('device-page-runs',code)
text = (source/'video_core/texture_cache/texture_cache.h').read_text()
code = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <span>
#include <vector>
using u32=uint32_t;using u64=uint64_t;using DAddr=u64;
namespace Common { template<class T> T DivCeil(T a,T b){return (a+b-1)/b;} }
namespace VideoCommon {enum class CacheType {NoTextureCache};}
struct ImageFlagBits {static constexpr u32 CpuModified=1;};
bool True(u32 v){return v;}bool False(u32 v){return !v;}
struct Image {
 u32 flags=1;u64 cpu_addr=4099,gpu_addr=8192,guest_size_bytes=8*1024;
 u32 host_level_offset=0;
 struct Info {struct Resources {int layers=8;} resources;u32 layer_stride=1024;} info;
 std::vector<u64> dirty_layers{0};
};
struct Swizzle {size_t buffer_offset;};
std::vector<Swizzle> FullUploadSwizzles(const Image::Info&){return {{0},{512}};}
struct Runtime {
 struct Staging {std::vector<uint8_t> data;std::span<uint8_t> mapped_span; explicit Staging(size_t n):data(n),mapped_span(data){}};
 std::vector<u32> decoded;
 Staging UploadStagingBuffer(size_t n){return Staging(n);}
 void AccelerateImageUploadLayers(Image&,Staging&,const std::vector<Swizzle>&,std::span<const u32> layers){decoded.insert(decoded.end(),layers.begin(),layers.end());}
};
struct Gpu {std::vector<std::pair<u64,size_t>> reads;void ReadBlock(u64 a,uint8_t*,size_t n,VideoCommon::CacheType){reads.emplace_back(a,n);}};
template<class P>struct TextureCache {
 using Runtime=::Runtime;Runtime runtime;Gpu gpu;Gpu* gpu_memory=&gpu;
 u64 images_uploaded=0,uploaded_bytes=0,largest_upload=0,layer_uploads=0;
 bool UploadsByLayer(const Image&)const{return true;}
 void MarkLayersWritten(Image&,DAddr,size_t);
 bool UploadWrittenLayers(Image&);
};
'''
code += method(text,'TextureCache<P>::MarkLayersWritten(')
code += method(text,'TextureCache<P>::UploadWrittenLayers(')
code += r'''
int main(){
 TextureCache<int> cache;Image image;
 cache.MarkLayersWritten(image,image.cpu_addr+1023,2);
 assert(image.dirty_layers[0]==3);
 cache.MarkLayersWritten(image,0,4096);assert(image.dirty_layers[0]==3);
 cache.MarkLayersWritten(image,UINT64_MAX-1,8);assert(image.dirty_layers[0]==3);
 assert(cache.UploadWrittenLayers(image));
 assert((cache.runtime.decoded==std::vector<u32>{0,1}));
 assert(cache.uploaded_bytes==2048 && cache.gpu.reads[1].first==image.gpu_addr+1024);
 image.dirty_layers={1ULL<<7};image.host_level_offset=1;
 assert(cache.UploadWrittenLayers(image));
 assert(cache.gpu.reads.back().first==image.gpu_addr+7*1024+512 && cache.gpu.reads.back().second==512);
 image.dirty_layers={255};assert(!cache.UploadWrittenLayers(image));
 image.dirty_layers={1};image.host_level_offset=2;assert(!cache.UploadWrittenLayers(image));
 // A single dirty CPU page may intersect multiple layers when the image is unaligned.
 image.host_level_offset=0;image.dirty_layers={0};cache.MarkLayersWritten(image,4096,4096);
 assert(image.dirty_layers[0]==15);
}
'''
run('astc-written-layers',code)
print('Device mapping runs and ASTC layer selection/upload ranges: PASS (ASan/UBSan)')
# Execute both the portable writer and the generated PS5 writer with a fake Vulkan driver.
# Real filesystem operations cover replacement, write failure and truncated headers.
cache_source = (source/'video_core/renderer_vulkan/vk_pipeline_cache.cpp').read_text()
cache_files = [('portable', cache_source)]
scratch = source.parent.parent
for path in scratch.rglob('vk_pipeline_cache_cost.cpp'):
    cache_files.append(('ps5', path.read_text()))
    break
assert len(cache_files) == 2, 'Generated PS5 cache implementation missing'
for variant, text in cache_files:
    begin = text.index('void PipelineCache::SerializeVulkanPipelineCache')
    end = text.index('} // namespace Vulkan',begin)
    code = r'''
#include <array>
#include <cassert>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <vector>
#include <unistd.h>
using u32=uint32_t;
#define LOG_ERROR(...) ((void)0)
#define LOG_INFO(...) ((void)0)
namespace Eden::Performance { int VulkanTimer(int){return 0;} }
namespace Common::FS {bool RemoveFile(const std::filesystem::path& p){std::error_code e;return std::filesystem::remove(p,e);} }
constexpr int VK_STRUCTURE_TYPE_PIPELINE_CACHE_CREATE_INFO=0;
struct VkPipelineCacheCreateInfo {int sType;void* pNext;int flags;size_t initialDataSize;const void* pInitialData;};
namespace vk {
struct PipelineCache {
 std::vector<char> bytes{'n','e','w'};bool fail=false;
 operator bool()const{return true;}
 void Read(size_t* n,char* data)const{if(fail)throw std::ios_base::failure("injected failure");*n=bytes.size();if(data)std::memcpy(data,bytes.data(),*n);}
};
}
struct Device {
 Device& GetLogical(){return *this;}
 vk::PipelineCache CreatePipelineCache(const VkPipelineCacheCreateInfo& i){vk::PipelineCache c;c.bytes.resize(i.initialDataSize);if(i.initialDataSize)std::memcpy(c.bytes.data(),i.pInitialData,i.initialDataSize);return c;}
};
constexpr std::array<char,8> VULKAN_CACHE_MAGIC_NUMBER{'t','e','s','t','c','a','c','h'};
struct PipelineCache {
 Device device;
 void SerializeVulkanPipelineCache(const std::filesystem::path&,const vk::PipelineCache&,u32);
 vk::PipelineCache LoadVulkanPipelineCache(const std::filesystem::path&,u32);
};
'''+text[begin:end]+r'''
int main(){
 auto dir=std::filesystem::temp_directory_path()/ ("nx2-cache-test-"+std::to_string(getpid()));
 std::filesystem::create_directory(dir);auto path=dir/"cache.bin";
 PipelineCache cache;vk::PipelineCache payload;
 cache.SerializeVulkanPipelineCache(path,payload,1);
 assert(cache.LoadVulkanPipelineCache(path,1).bytes==payload.bytes);
 payload.fail=true;cache.SerializeVulkanPipelineCache(path,payload,1);
 assert(cache.LoadVulkanPipelineCache(path,1).bytes==std::vector<char>({'n','e','w'}));
 for(size_t n=0;n<12;n++) {
  {std::ofstream file(path,std::ios::binary);for(size_t j=0;j<n;j++)file.put('x');}
  assert(cache.LoadVulkanPipelineCache(path,1).bytes.empty());
 }
 payload.fail=false;cache.SerializeVulkanPipelineCache(path,payload,1);
 assert(cache.LoadVulkanPipelineCache(path,2).bytes.empty());
 std::filesystem::remove_all(dir);
}
'''
    run('pipeline-cache-'+variant,code)
print('Portable and generated PS5 cache: atomic replacement, failed write preserves old file, truncated header rejection PASS')
