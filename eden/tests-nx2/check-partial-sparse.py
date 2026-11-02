"""Build-server only: production sparse tracking and real decoder differential tests."""
from pathlib import Path
import platform
import subprocess
assert platform.system() == 'Linux', 'Run on dedie only'
root = Path(__file__).resolve().parents[1]
source = Path((root / '.local/headless-cache').read_text().strip()) / 'source/src'
out = root / 'build/nx2-tests/partial-sparse'
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
                    '-fno-omit-frame-pointer', str(path), '-o', str(out/name)], check=True)
    subprocess.run([str(out/name)], check=True)
    print(name + ': PASS (ASan/UBSan)', flush=True)
common = r'''
#include <algorithm>
#include <array>
#include <bit>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <limits>
#include <map>
#include <numeric>
#include <optional>
#include <span>
#include <tuple>
#include <utility>
#include <vector>
using u8=uint8_t; using u32=uint32_t; using u64=uint64_t; using s32=int32_t;
namespace Core {constexpr u32 DEVICE_PAGEBITS=12;constexpr u64 DEVICE_PAGESIZE=4096,DEVICE_PAGEMASK=4095;}
using DAddr=u64; using GPUVAddr=u64; using ImageId=u32;
#define LOG_INFO(...) ((void)0)
#define ASSERT(x) assert(x)
#define ASSERT_MSG(x,...) assert(x)
#define UNIMPLEMENTED_IF(x) assert(!(x))
constexpr u64 operator""_MiB(unsigned long long n){return n<<20;}
'''
text = (source/'video_core/texture_cache/texture_cache.h').read_text()
code = common + r'''
enum class ImageFlagBits:u32{Tracked=1,Sparse=2,Converted=4,AcceleratedUpload=8,Unbacked=16,
 TrimmedLevels=32,AsynchronousDecode=64,CpuModified=128,Remapped=256,Rescaled=512,GpuModified=1024,Strong=2048,IsDecoding=4096};
constexpr ImageFlagBits operator|(ImageFlagBits a,ImageFlagBits b){return ImageFlagBits(u32(a)|u32(b));}
constexpr ImageFlagBits operator&(ImageFlagBits a,ImageFlagBits b){return ImageFlagBits(u32(a)&u32(b));}
constexpr ImageFlagBits operator~(ImageFlagBits a){return ImageFlagBits(~u32(a));}
ImageFlagBits& operator|=(ImageFlagBits& a,ImageFlagBits b){return a=a|b;}
ImageFlagBits& operator&=(ImageFlagBits& a,ImageFlagBits b){return a=a&b;}
bool False(ImageFlagBits x){return u32(x)==0;}bool True(ImageFlagBits x){return !False(x);}
enum class ImageType{e2D,Linear};enum class SurfaceType{ColorTexture,Depth};
enum class PixelFormat{R8,R16,RG16,BC,Depth};
SurfaceType GetFormatType(PixelFormat f){return f==PixelFormat::Depth?SurfaceType::Depth:SurfaceType::ColorTexture;}
u32 DefaultBlockWidth(PixelFormat f){return f==PixelFormat::BC?4:1;}
u32 DefaultBlockHeight(PixelFormat f){return DefaultBlockWidth(f);}
struct ImageBase{ImageFlagBits flags=ImageFlagBits::Tracked|ImageFlagBits::Sparse;
 struct {u32 pitch=0;ImageType type=ImageType::e2D;PixelFormat format=PixelFormat::R8;
 struct {u32 layers=1;}resources;struct {u32 depth=1;}size;struct {u32 depth=0;}block;u32 num_samples=1;}info;
 u64 guest_size_bytes=64_MiB,gpu_addr=0x100000000,cpu_addr=0xfffffeffffffffff;
 std::vector<u32> partial_dirty_pages;std::vector<std::pair<u64,u32>> sparse_dirty_pages;std::vector<std::pair<u64,u64>> partial_remapped;
 std::vector<int> dirty_layers,aliased_images;bool sparse_mappings_changed=false,scaled=false;size_t lru_index=3;u64 modification_tick=0,async_decode_generation=0;
 bool HasScaled()const{return scaled;}
};using Image=ImageBase;using ImageInfo=decltype(ImageBase::info);
u64 CalculateGuestSizeInBytes(const ImageInfo&){return 64_MiB;}
enum class RelaxedOptions:u32{Size=1,Format=2,ForceBrokenViews=4};
RelaxedOptions operator&(RelaxedOptions a,RelaxedOptions b){return RelaxedOptions(u32(a)&u32(b));}
bool True(RelaxedOptions o){return u32(o)!=0;}bool False(RelaxedOptions o){return !True(o);}
bool IsSubresource(const ImageInfo&,const ImageBase& i,u64 g,RelaxedOptions,bool,bool){return i.gpu_addr==g;}
bool IsPitchLinearSameSize(const ImageInfo&,const ImageInfo&,bool){return true;}
bool IsViewCompatible(PixelFormat a,PixelFormat b,bool,bool){return a==b;}

struct MapId{u32 index;bool operator==(const MapId&)const=default;operator int()const{return index;}};
struct Map{u64 gpu_addr,cpu_addr;size_t size;ImageId image_id;};
struct Maps{std::map<int,Map> values;int next=1;
 MapId insert(u64 g,u64 c,size_t n,ImageId i){int id=next++;values.emplace(id,Map{g,c,n,i});return MapId{u32(id)};}
 Map& operator[](int id){return values.at(id);}void erase(int id){assert(values.erase(id)==1);}};
namespace boost::container{template<class T,size_t N>using small_vector=std::vector<T>;}
void LogWholeUpload(const char*,u64,u64,u64,size_t){}bool IsWatchedImage(u64){return false;}
namespace VideoCommon::Nx2Profile{bool Enabled(){return false;}}
// This fixture tracks actual reference-count deltas and current mappings; two
// GPU segments deliberately alias the same physical CPU page.
template<class P>struct TextureCache{
 struct Runtime{bool HasBrokenTextureViewFormats(){return false;}bool HasNativeBgr(){return false;}}runtime;
 struct Channel{struct Gpu{size_t GetID(){return 1;}}gpu_memory;}channel;
 Channel* channel_state=&channel;
 std::optional<DAddr> ImageCpuAddress(u64,size_t){return 0x50000;}
 template<class F>void ForEachImageInRegion(u64,size_t,F){/* old CPU maps cannot find a moved first page */}
 template<class F>void ForEachSparseImageInRegion(size_t,u64,size_t,F f){for(auto& [id,i]:slot_images)if(f(id,i))break;}
 ImageId FindImage(const ImageInfo&,GPUVAddr,RelaxedOptions);
 std::map<ImageId,Image> slot_images;std::map<ImageId,std::vector<MapId>> sparse_views;
 Maps slot_map_views;std::map<u64,std::vector<MapId>> page_table;
 std::vector<std::tuple<u64,u64,size_t>> segments;
 struct Device{std::map<u64,int> counts;void UpdatePagesCachedCount(u64 a,size_t n,int d){
  for(u64 p=a/4096;p<(a+n+4095)/4096;++p){counts[p]+=d;assert(counts[p]>=0);}}}device_memory;
 struct Lru{void Touch(size_t,u64){}}lru_cache;u64 frame_tick=0;
 template<class F>void ForEachCPUPage(u64 a,size_t n,F f){for(u64 p=a/4096;p<(a+n+4095)/4096;++p)f(p);}
 template<class F>void ForEachSparseSegment(Image&,F f){for(auto [g,c,n]:segments)f(g,c,n);}
 bool CanUploadSparsePartial(const ImageBase&)const;bool AddSparseDirtyRange(ImageBase&,u64,u64);
 bool MarkSparseWrite(ImageId,Image&,DAddr,size_t);void RebuildSparseMappings(ImageId,Image&);
 bool MarkPartialRemap(ImageBase&,GPUVAddr,size_t);void PrepareImage(ImageId,bool,bool);
 void RestorePartialPages(Image& i);
 void UntrackImage(Image& i,ImageId id){RestorePartialPages(i);for(auto m:sparse_views.at(id)){auto& v=slot_map_views[m];device_memory.UpdatePagesCachedCount(v.cpu_addr,v.size,-1);}i.flags&=~ImageFlagBits::Tracked;}
 void TrackImage(Image& i,ImageId id){for(auto m:sparse_views.at(id)){auto& v=slot_map_views[m];device_memory.UpdatePagesCachedCount(v.cpu_addr,v.size,1);}i.flags|=ImageFlagBits::Tracked;}
 void RefreshContents(Image& i,ImageId){assert(!i.sparse_mappings_changed);i.flags&=~ImageFlagBits::CpuModified;}
 void SynchronizeAliases(ImageId){}void MarkModification(Image& i){i.flags|=ImageFlagBits::GpuModified;}
};
'''
code += function(text,'inline void InvalidateAsyncDecode(')
for sig in ['ImageId TextureCache<P>::FindImage(', 'bool TextureCache<P>::CanUploadSparsePartial(', 'bool TextureCache<P>::AddSparseDirtyRange(',
            'bool TextureCache<P>::MarkSparseWrite(', 'void TextureCache<P>::RebuildSparseMappings(',
            'bool TextureCache<P>::MarkPartialRemap(', 'void TextureCache<P>::RestorePartialPages(', 'void TextureCache<P>::PrepareImage(']:
    code += 'template<class P>\n' + function(text,sig)
code += r'''
int main(){
 TextureCache<int> c;auto& i=c.slot_images[1];c.sparse_views[1]={};
 const auto g=i.gpu_addr;
 c.segments={{g,0x10000,4096},{g+65536,0x10000,4096},{g+131072,0x30000,8192}};
 i.sparse_mappings_changed=true;c.RebuildSparseMappings(1,i);
 assert(c.device_memory.counts[0x10]==2&&c.device_memory.counts[0x30]==1);
 assert(c.MarkSparseWrite(1,i,0x10000+100,10));
 assert((i.partial_remapped==std::vector<std::pair<u64,u64>>{{0,4096},{65536,69632}}));
 assert(c.MarkSparseWrite(1,i,0x10000+105,20));
 assert((i.partial_remapped==std::vector<std::pair<u64,u64>>{{0,4096},{65536,69632}}));
 assert(c.device_memory.counts[0x10]==0); // no double decrement on repeat writes
 c.RestorePartialPages(i);i.flags&=~ImageFlagBits::CpuModified;
 assert(c.MarkPartialRemap(i,g+65536,65536));assert(i.sparse_mappings_changed);
 assert((i.partial_remapped==std::vector<std::pair<u64,u64>>{{65536,131072}}));
 c.segments={{g,0x10000,4096},{g+65536,0x50000,8192}};
 assert(c.FindImage(i.info,g,RelaxedOptions{})==1); // GPU index survives a moved first CPU page
 c.RebuildSparseMappings(1,i);
 assert(c.device_memory.counts[0x10]==1&&c.device_memory.counts[0x30]==0&&c.device_memory.counts[0x50]==1);
 assert(c.page_table[0x30].empty());assert(c.sparse_views[1].size()==2);
 assert(c.MarkSparseWrite(1,i,0x50000+4090,20));
 assert((i.partial_remapped==std::vector<std::pair<u64,u64>>{{65536,131072}}));
 // Most of the image changed: subsequent small writes must retain a full refresh.
 c.RestorePartialPages(i);i.flags&=~ImageFlagBits::CpuModified;
 assert(c.MarkPartialRemap(i,g,32_MiB));assert(i.partial_remapped.empty());
 assert(c.MarkSparseWrite(1,i,0x50000,1));assert(i.partial_remapped.empty());
 // Rebuild also precedes the invalidate/clear path, without uploading guest pixels.
 c.segments={{g,0x80000,4096}};c.PrepareImage(1,true,true);
 assert(!i.sparse_mappings_changed&&c.device_memory.counts[0x50]==0&&c.device_memory.counts[0x80]==1);
 assert(True(i.flags&ImageFlagBits::GpuModified));assert(!c.CanUploadSparsePartial(i));
 i.flags&=~ImageFlagBits::GpuModified;
 for(auto flag:{ImageFlagBits::Unbacked,ImageFlagBits::Converted,ImageFlagBits::Rescaled,
  ImageFlagBits::Remapped,ImageFlagBits::TrimmedLevels,ImageFlagBits::AsynchronousDecode}){
  i.flags|=flag;assert(!c.CanUploadSparsePartial(i));i.flags&=~flag;
 }
 for(auto f:{PixelFormat::R8,PixelFormat::R16,PixelFormat::RG16}){i.info.format=f;assert(c.CanUploadSparsePartial(i));}
 for(auto f:{PixelFormat::BC,PixelFormat::Depth}){i.info.format=f;assert(!c.CanUploadSparsePartial(i));}
 i.info.format=PixelFormat::R8;i.info.resources.layers=2;assert(!c.CanUploadSparsePartial(i));
 i.info.resources.layers=1;i.info.num_samples=2;assert(!c.CanUploadSparsePartial(i));i.info.num_samples=1;
 // Repeat map -> unmap -> map, including no CPU segments at all.
 for(int pass=0;pass<100;++pass){
  i.flags&=~ImageFlagBits::CpuModified;assert(c.MarkPartialRemap(i,g,4096));
  c.segments.clear();c.RebuildSparseMappings(1,i);assert(c.page_table[0x80].empty());
  c.segments={{g,0x80000,4096}};c.RebuildSparseMappings(1,i);assert(c.device_memory.counts[0x80]==1);
  c.RestorePartialPages(i);
 }
 // Merge duplicated, unsorted, adjacent dirty ranges, with a bounded metadata fallback.
 i.partial_remapped.clear();assert(c.AddSparseDirtyRange(i,20,30));assert(c.AddSparseDirtyRange(i,0,10));
 assert(c.AddSparseDirtyRange(i,10,20));assert((i.partial_remapped==std::vector<std::pair<u64,u64>>{{0,30}}));
 i.partial_remapped.clear();for(u64 p=0;p<4096;++p)assert(c.AddSparseDirtyRange(i,p*2,p*2+1));
 assert(!c.AddSparseDirtyRange(i,8192,8193));assert(i.partial_remapped.empty());
}
'''
run('sparse-mapping-tracking',code)
# The same explicit fixture supports recording calls and real decoder comparisons.
declarations = '#include "' + str(root/'tests-nx2/texture-transfer-fixture.h') + '"\n'
decoder=(source/'video_core/textures/decoders.cpp').read_text()
decoder=decoder[decoder.index('namespace Tegra::Texture {'):decoder.index('void SwizzleSubrect(')]
decoder+='}\n'
decoder=decoder.replace('namespace Tegra::Texture {','namespace Tegra::Texture {\nconstexpr u32 SWIZZLE_X_BITS=0b100101111,SWIZZLE_Y_BITS=0b011010000;')
text=(source/'video_core/texture_cache/util.cpp').read_text()
code=common+declarations+decoder+'using Tegra::Texture::UnswizzleTexture;using Tegra::Texture::SwizzleTexture;\n'
helpers=text[text.index('struct LevelInfo {'):text.index('[[nodiscard]] constexpr u32 CalculateLevelOffset(')]
helpers=helpers.replace(function(helpers,'[[nodiscard]] Extent3D AdjustSamplesSize('),'')
code+=helpers
for sig in ['[[nodiscard]] constexpr u32 CalculateLevelOffset(', '[[nodiscard]] constexpr u32 AlignLayerSize(',
            'u32 CalculateLayerSize(', 'u32 CalculateLayerStride(',
            'boost::container::small_vector<BufferImageCopy, 16> UnswizzleImage(',
            'boost::container::small_vector<BufferImageCopy, 16> UnswizzleImageRows(']:
    code+=function(text,sig)
code+=r'''
int main(){
 u32 random=0x792fac1;auto next=[&](){random^=random<<13;random^=random>>17;random^=random<<5;return random;};
 size_t cases=0,read_bytes=0,full_bytes=0;
 for(bool native:{false,true})for(PixelFormat f:{PixelFormat::R8,PixelFormat::R16,PixelFormat::RGBA,PixelFormat::RG32})
 for(u32 spacing:{0u,1u,2u})for(u32 height:{1u,17u,65u,131u})for(u32 levels:{1u,3u}){
  ImageInfo info;info.format=f;info.resources={s32(levels),1};info.size={80+(next()%89),height,1};
  info.block={0,next()%5,0};info.tile_width_spacing=spacing;info.layer_stride=0;
  const auto sizes=CalculateLevelSizes(MakeLevelInfo(info),levels);
  size_t guest=0;for(u32 l=0;l<levels;++l)guest+=sizes[l];
  Tegra::MemoryManager memory;memory.native=native;memory.bytes.resize(guest);
  for(auto& b:memory.bytes)b=u8(next());
  size_t pixels=0;for(u32 l=0;l<levels;++l)pixels+=size_t(std::max(1u,info.size.width>>l))*std::max(1u,height>>l)*BytesPerBlock(f);
  std::vector<u8> full(pixels);UnswizzleImage(memory,0,info,memory.bytes,full);
  std::vector<std::pair<u64,u64>> ranges;
  for(int n=0;n<4;++n){u64 a=next()%guest;ranges.emplace_back(a,std::min<u64>(guest,a+1+next()%4096));}
  ranges.push_back(ranges.front());std::reverse(ranges.begin(),ranges.end());
  std::vector<u8> partial;auto copies=UnswizzleImageRows(memory,0,info,ranges,partial);
  for(const auto& copy:copies){
   size_t level_offset=0;for(int l=0;l<copy.image_subresource.base_level;++l)level_offset+=size_t(std::max(1u,info.size.width>>l))*std::max(1u,height>>l)*BytesPerBlock(f);
   u32 w=std::max(1u,info.size.width>>copy.image_subresource.base_level);
   for(u32 y=0;y<copy.image_extent.height;++y){
    const size_t a=copy.buffer_offset+size_t(y)*copy.buffer_row_length*BytesPerBlock(f);
    const size_t b=level_offset+(size_t(y+copy.image_offset.y)*w+copy.image_offset.x)*BytesPerBlock(f);
    assert(std::memcmp(partial.data()+a,full.data()+b,size_t(copy.image_extent.width)*BytesPerBlock(f))==0);
   }
  }
  // Apply partial rectangles to a pre-write image. This proves dirty-byte
  // coverage too: missing copies cannot pass merely by comparing emitted rows.
  auto previous=memory.bytes;for(const auto [a,b]:ranges)for(u64 p=a;p<b;++p)previous[p]^=0x55;
  std::vector<u8> patched(pixels);UnswizzleImage(memory,0,info,previous,patched);
  for(const auto& copy:copies){
   size_t offset=0;for(int l=0;l<copy.image_subresource.base_level;++l)offset+=size_t(std::max(1u,info.size.width>>l))*std::max(1u,height>>l)*BytesPerBlock(f);
   u32 w=std::max(1u,info.size.width>>copy.image_subresource.base_level);
   for(u32 y=0;y<copy.image_extent.height;++y)std::memcpy(patched.data()+offset+(size_t(y+copy.image_offset.y)*w+copy.image_offset.x)*BytesPerBlock(f),partial.data()+copy.buffer_offset+size_t(y)*copy.buffer_row_length*BytesPerBlock(f),size_t(copy.image_extent.width)*BytesPerBlock(f));
  }
  assert(patched==full);
  for(auto [a,n]:memory.reads)read_bytes+=n;full_bytes+=guest;++cases;
 }
 assert(cases==192);
 // A realistic large R8 mask: 64 KiB of changed guest blocks must not read 256 MiB.
 ImageInfo info;info.format=PixelFormat::R8;info.size={16384,16384,1};info.resources={1,1};info.block={0,5,0};info.tile_width_spacing=0;info.layer_stride=0;
 Tegra::MemoryManager memory;memory.bytes.resize(256_MiB);std::vector<u8> partial;
 const std::array<std::pair<u64,u64>,1> dirty{{{64_MiB,64_MiB+65536}}};
 const auto copies=UnswizzleImageRows(memory,0,info,dirty,partial);
 size_t read=0;for(auto [a,n]:memory.reads)read+=n;
 assert(!copies.empty()&&read==65536&&partial.size()==65536);
 std::printf("decoder differential cases=%zu; large-mask read=%zu vs %llu bytes full\n",cases,read,(unsigned long long)(256_MiB));
}
'''
code=code.replace('#include <cstring>','#include <cstring>\n#include <cstdio>')
run('real-decoder-rectangles',code)
