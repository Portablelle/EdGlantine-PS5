"""Run extracted production methods on recording backends; Linux/build-server only.

Covers cache ownership, exactly-once page accounting, and texture transfer
addresses/strides. Decoder calls are recorded: this does not validate pixels or RADV.
"""
from pathlib import Path
import platform
import subprocess
assert platform.system() == 'Linux', 'Run on build-server only'
root = Path(__file__).resolve().parents[1]
source = Path((root / '.local/headless-cache').read_text().strip()) / 'source/src'
out = root / 'build/nx2-tests/eglantine-pages-textures'
out.mkdir(parents=True, exist_ok=True)
def function(text, signature):
    start = text.index(signature)
    brace = text.index('{', start)
    end, depth = brace + 1, 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end] + '\n'
def run(name, code):
    path = out / (name + '.cpp')
    path.write_text(code)
    subprocess.run(['clang++-18', '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
                    str(path), '-o', str(out/name)], check=True)
    subprocess.run([str(out/name)], check=True)
    print(name + ': PASS (ASan/UBSan)', flush=True)
common = r'''
#include <algorithm>
#include <array>
#include <atomic>
#include <bit>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <memory>
#include <numeric>
#include <span>
#include <tuple>
#include <utility>
#include <vector>
using u8=uint8_t; using u32=uint32_t; using u64=uint64_t; using s32=int32_t;
using DAddr=u64; using GPUVAddr=u64;
#define LOG_INFO(...) ((void)0)
#define ASSERT(x) assert(x)
#define UNIMPLEMENTED_IF(x) assert(!(x))
namespace Core {constexpr u32 DEVICE_PAGEBITS=12; constexpr size_t DEVICE_PAGESIZE=4096;}
'''
text = (source/'core/device_memory_manager.inc').read_text()
code = common + r'''
namespace Memory {constexpr u32 YUZU_PAGEBITS=12;constexpr size_t YUZU_PAGESIZE=4096;}
namespace Common {template<class T> T DivCeil(T a,T b){return (a+b-1)/b;}}
struct Asid{size_t id;};
struct Backend{std::vector<std::tuple<u64,size_t,bool>> calls;};
template<class Traits> struct DeviceMemoryManager {
 using CounterType=u8;using CounterAtomicType=std::atomic<u8>;
 static constexpr u32 subentries_shift=0;
 struct Counter {CounterAtomicType value{0};CounterAtomicType& Count(size_t){return value;}};
 std::unique_ptr<std::array<Counter,16>> cached_pages=std::make_unique<std::array<Counter,16>>();
 Backend a,b; std::array<Backend*,2> registered_processes{&a,&b};
 std::array<std::pair<Asid,u64>,16> backing{};
 auto ExtractCPUBacking(size_t p){return backing.at(p);}
 struct DeviceMethods {static void MarkRegionCaching(Backend* b,u64 p,size_t n,bool c){assert(b);b->calls.emplace_back(p,n,c);}};
 void UpdatePagesCachedCountNoLock(DAddr,size_t,s32);
};
''' + 'template<typename Traits>\n' + function(text,'void DeviceMemoryManager<Traits>::UpdatePagesCachedCountNoLock(') + r'''
int main(){
 DeviceMemoryManager<int> m;
 // Contiguous virtual addresses deliberately cross A -> B -> A.
 m.backing[1]={{0},4096};m.backing[2]={{1},8192};m.backing[3]={{0},12288};
 m.UpdatePagesCachedCountNoLock(4096,3*4096,1);
 assert((m.a.calls==std::vector<std::tuple<u64,size_t,bool>>{{4096,4096,true},{12288,4096,true}}));
 assert((m.b.calls==std::vector<std::tuple<u64,size_t,bool>>{{8192,4096,true}}));
 m.a.calls.clear();m.b.calls.clear();m.UpdatePagesCachedCountNoLock(4096,3*4096,-1);
 assert((m.a.calls==std::vector<std::tuple<u64,size_t,bool>>{{4096,4096,false},{12288,4096,false}}));
 assert((m.b.calls==std::vector<std::tuple<u64,size_t,bool>>{{8192,4096,false}}));
 for(int p=1;p<=3;p++)assert(m.cached_pages->at(p).value==0);
 // Same owner batches, a hole ends the run, discontinuity ends the next one.
 DeviceMemoryManager<int> n;
 n.backing[1]={{0},4096};n.backing[2]={{0},8192};n.backing[4]={{0},16384};n.backing[5]={{0},32768};
 n.UpdatePagesCachedCountNoLock(4096,5*4096,1);
 assert((n.a.calls==std::vector<std::tuple<u64,size_t,bool>>{{4096,8192,true},{16384,4096,true},{32768,4096,true}}));
}
'''
run('memory-owners',code)
text = (source/'video_core/texture_cache/texture_cache.h').read_text()
code = common + r'''
constexpr u64 operator""_MiB(unsigned long long n){return n<<20;}
enum class ImageFlagBits:u32{Tracked=1,Sparse=2,Converted=4,AcceleratedUpload=8,Unbacked=16,TrimmedLevels=32,AsynchronousDecode=64,CpuModified=128};
ImageFlagBits operator|(ImageFlagBits a,ImageFlagBits b){return ImageFlagBits(u32(a)|u32(b));}
ImageFlagBits operator&(ImageFlagBits a,ImageFlagBits b){return ImageFlagBits(u32(a)&u32(b));}
ImageFlagBits& operator|=(ImageFlagBits& a,ImageFlagBits b){return a=a|b;}
bool False(ImageFlagBits x){return u32(x)==0;}bool True(ImageFlagBits x){return !False(x);}
enum class ImageType{e2D};struct ImageId{};
struct ImageBase{ImageFlagBits flags=ImageFlagBits::Tracked;struct{ImageType type=ImageType::e2D;}info;
 u64 cpu_addr=4096,gpu_addr=4096,guest_size_bytes=64_MiB;std::vector<u32> partial_dirty_pages,partial_remapped;};
template<class P>struct TextureCache {
 struct Device{std::vector<std::tuple<u64,size_t,int>> calls;void UpdatePagesCachedCount(u64 a,size_t n,int d){calls.emplace_back(a,n,d);}}device_memory;
 bool UploadsByLayer(ImageBase&){return false;}bool IsWatchedImage(u64){return false;}
 void LogWholeUpload(const char*,u64,u64,u64,size_t){}void UntrackImage(ImageBase&,ImageId){assert(false);}
 bool MarkPartialWrite(ImageBase&,DAddr,size_t);void RestorePartialPages(ImageBase&);
};
'''
# The production exclusion mask is constexpr.
code=code.replace('ImageFlagBits operator|(', 'constexpr ImageFlagBits operator|(')
for sig in ['bool TextureCache<P>::MarkPartialWrite(', 'void TextureCache<P>::RestorePartialPages(']:
    code += 'template<class P>\n' + function(text,sig)
code += r'''
int main(){
 TextureCache<int> c;ImageBase i;std::array<int,16385> counts{};counts.fill(1);
 std::array<bool,16384> dirty{};
 auto apply=[&]{for(auto [a,n,d]:c.device_memory.calls){assert(a%4096==0&&n%4096==0);for(u64 p=a/4096;p<(a+n)/4096;p++){counts.at(p)+=d;assert(counts[p]>=0&&counts[p]<=1);}}c.device_memory.calls.clear();};
 assert(c.MarkPartialWrite(i,i.cpu_addr+100*4096,1000*4096));
 assert(c.device_memory.calls.size()==1);for(int p=100;p<1100;p++)dirty[p]=true;apply();
 assert(c.MarkPartialWrite(i,i.cpu_addr+100*4096,1000*4096));assert(c.device_memory.calls.empty());
 u32 seed=73;
 for(int k=0;k<2000;k++){
  seed=seed*1664525+1013904223;u32 first=seed%2000;seed=seed*1664525+1013904223;u32 len=1+seed%40;
  assert(c.MarkPartialWrite(i,i.cpu_addr+first*4096+7,len*4096-9));
  for(u32 p=first;p<first+len;p++)dirty[p]=true;apply();
  std::vector<u32> expected;for(u32 p=0;p<dirty.size();p++){if(dirty[p])expected.push_back(p);assert(counts[p+1]==!dirty[p]);}
  assert(i.partial_dirty_pages==expected);
 }
 c.RestorePartialPages(i);apply();assert(i.partial_dirty_pages.empty());for(int n:counts)assert(n==1);
 // Unaligned image start, single byte crossing a physical-page boundary.
 i.cpu_addr=4099;i.flags=ImageFlagBits::Tracked;
 assert(c.MarkPartialWrite(i,8191,2));assert((i.partial_dirty_pages==std::vector<u32>{0,1}));
 assert(c.device_memory.calls.size()==1);apply();c.RestorePartialPages(i);apply();
}
'''
run('partial-page-batches',code)
text = (source/'video_core/texture_cache/util.cpp').read_text()
code = common + r'''
namespace Common {
 template<class T> constexpr T DivCeil(T a,T b){return (a+b-1)/b;}
 template<class T> constexpr T DivCeilLog2(T a,u32 b){return (a+((T{1}<<b)-1))>>b;}
 template<class T> constexpr T AlignUp(T a,T b){return DivCeil(a,b)*b;}
 template<class T> constexpr T AlignUpLog2(T a,u32 b){return DivCeilLog2(a,b)<<b;}
 template<class T>using ScratchBuffer=std::vector<T>;
}
namespace boost::container{template<class T,size_t N>using small_vector=std::vector<T>;}
struct Extent2D{u32 width,height;};
struct Extent3D{u32 width,height,depth;bool operator==(const Extent3D&)const=default;};
struct Offset3D{s32 x,y,z;};
struct SubresourceExtent{s32 levels=1,layers=2;};
struct Subresource{s32 base_level,base_layer,num_layers;};
enum class PixelFormat{RGBA};
constexpr u32 BytesPerBlock(PixelFormat){return 4;}
constexpr u32 DefaultBlockWidth(PixelFormat){return 1;}
constexpr u32 DefaultBlockHeight(PixelFormat){return 1;}
enum class ImageType{e2D,Linear};
struct ImageInfo{PixelFormat format=PixelFormat::RGBA;ImageType type=ImageType::e2D;
 Extent3D size{80,33,1},block{0,2,0};SubresourceExtent resources;
 u32 tile_width_spacing=2,layer_stride=65536,num_samples=1,pitch=0;};
struct BufferImageCopy{size_t buffer_offset,buffer_size;u32 buffer_row_length,buffer_image_height;
 Subresource image_subresource;Offset3D image_offset;Extent3D image_extent;};
constexpr u32 GOB_SIZE=512,GOB_SIZE_SHIFT=9,GOB_SIZE_X=64,GOB_SIZE_X_SHIFT=6,GOB_SIZE_Y=8,GOB_SIZE_Y_SHIFT=3,GOB_SIZE_Z=1;
constexpr u32 MAX_MIP_LEVELS=16;using LevelArray=std::array<u32,MAX_MIP_LEVELS>;
namespace Tegra {
 struct MemoryManager{
  std::vector<u8> bytes=std::vector<u8>(1024*1024);std::vector<std::pair<u64,size_t>> reads,writes;
  bool UsesNativeTiling(){return true;}
  void ReadBlockUnsafe(u64 a,void* p,size_t n){assert(a+n<=bytes.size());reads.emplace_back(a,n);std::memcpy(p,bytes.data()+a,n);}
 };
 namespace Memory{
 enum class GuestMemoryFlags{UnsafeReadWrite};
 template<class T,GuestMemoryFlags>struct GpuGuestMemoryScoped{
  std::span<T> data;
  GpuGuestMemoryScoped(MemoryManager& m,u64 a,size_t n,Common::ScratchBuffer<u8>*){assert(a+n<=m.bytes.size());m.writes.emplace_back(a,n);data={m.bytes.data()+a,n};}
  operator std::span<T>(){return data;}
 };
 }
 namespace Texture{
 struct Call{const u8* src;u8* dst;u32 width,height,alignment;};inline std::vector<Call> calls;
 void UnswizzleTexture(std::span<u8> dst,std::span<const u8> src,u32 bpp,u32 w,u32 h,u32 d,u32,u32,u32 alignment,bool){assert(dst.size()>=size_t(w)*h*d*bpp);calls.push_back({src.data(),dst.data(),w,h,alignment});}
 void SwizzleTexture(std::span<u8> dst,std::span<const u8> src,u32 bpp,u32 w,u32 h,u32 d,u32,u32,u32 alignment,bool){assert(src.size()>=size_t(w)*h*d*bpp);calls.push_back({src.data(),dst.data(),w,h,alignment});}
 }
}
using Tegra::Texture::UnswizzleTexture;using Tegra::Texture::SwizzleTexture;
'''
helpers = text[text.index('struct LevelInfo {'):text.index('[[nodiscard]] constexpr u32 CalculateLevelOffset(')]
helpers = helpers.replace(function(helpers,'[[nodiscard]] Extent3D AdjustSamplesSize('),'')
code += helpers
code += function(text,'[[nodiscard]] constexpr u32 CalculateLevelOffset(')
code += function(text,'[[nodiscard]] constexpr u32 AlignLayerSize(')
code += function(text,'u32 CalculateLayerSize(')
code += function(text,'u32 CalculateLayerStride(')
for sig in ['void SwizzleBlockLinearImage(', 'boost::container::small_vector<BufferImageCopy, 16> UnswizzleImage(', 'boost::container::small_vector<BufferImageCopy, 16> UnswizzleImageRows(', 'boost::container::small_vector<BufferImageCopy, 16> FullDownloadCopies(']:
    code += function(text,sig)
code += r'''
int main(){
 Tegra::MemoryManager memory;ImageInfo info;Common::ScratchBuffer<u8> tmp;
 std::vector<u8> pixels(80*33*4*2);std::vector<u8> output(pixels.size());
 const auto copies=FullDownloadCopies(info);assert(copies.size()==1);
 SwizzleBlockLinearImage(memory,0,info,copies[0],pixels,tmp);
 assert(memory.writes.size()==2&&memory.writes[1].first==65536);
 assert(Tegra::Texture::calls.size()==2&&Tegra::Texture::calls[0].alignment==6);
 Tegra::Texture::calls.clear();
 UnswizzleImage(memory,0,info,memory.bytes,output);
 assert(Tegra::Texture::calls.size()==2);
 assert(Tegra::Texture::calls[1].src==memory.bytes.data()+65536);
 assert(Tegra::Texture::calls[0].alignment==6);
 // Partial rows must not divide the level's padding among the visible bands.
 // 80 RGBA pixels = five 64-byte GOBs; 17 rows fit one 32-row block band.
 info.size.height=17;memory.reads.clear();output.clear();
 const std::array<std::pair<u64,u64>,1> dirty{{{65536,65536+16384}}};
 auto rows=UnswizzleImageRows(memory,0,info,dirty,output);
 assert(rows.size()==1&&rows[0].image_subresource.base_layer==1);
 assert(rows[0].image_extent.width==80&&rows[0].image_extent.height==17);
 assert((memory.reads==std::vector<std::pair<u64,size_t>>{{65536,5*2048}}));
 // A write entirely in trailing layer padding needs no upload.
 memory.reads.clear();output.clear();
 const std::array<std::pair<u64,u64>,1> padding{{{65536+10240,65536+16384}}};
 assert(UnswizzleImageRows(memory,0,info,padding,output).empty());assert(memory.reads.empty());
 // Mip chains preserve the explicit layer stride; zero uses the calculated fallback.
 for(u32 stride:{0u,65536u}){
  info.layer_stride=stride;info.resources.levels=3;info.size={80,33,1};
  const u32 actual=stride?stride:CalculateLayerStride(info);
  auto levels=CalculateLevelSizes(MakeLevelInfo(info),3);auto cs=FullDownloadCopies(info);
  pixels.resize(1024*1024);output.resize(pixels.size());
  memory.writes.clear();Tegra::Texture::calls.clear();
  SwizzleBlockLinearImage(memory,0,info,cs[1],pixels,tmp);
  assert(memory.writes[0].first==levels[0]);assert(memory.writes[1].first==levels[0]+actual);
  Tegra::Texture::calls.clear();UnswizzleImage(memory,0,info,memory.bytes,output);
  assert(Tegra::Texture::calls.size()==6);
  assert(Tegra::Texture::calls[3].src==memory.bytes.data()+levels[0]+actual);
 }
 info.num_samples=2;output.clear();assert(UnswizzleImageRows(memory,0,info,dirty,output).empty());
}
'''
run('texture-transfer-layouts',code)
