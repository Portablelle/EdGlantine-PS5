"""dedie only: production CPU asynchronous decode publication, with a controlled worker."""
from pathlib import Path
import platform,subprocess,sys
assert platform.system()=='Linux','Run on dedie only'
root=Path(__file__).resolve().parents[1]
source=Path((root/'.local/headless-cache').read_text().strip())/'source/src/video_core/texture_cache'
out=root/'build/nx2-tests/async-decode-generation';out.mkdir(parents=True,exist_ok=True)
def function(text,sig):
 start=text.index(sig);end=text.index('{',start)+1;depth=1
 while depth:
  depth+=(text[end]=='{')-(text[end]=='}');end+=1
 return text[start:end]+'\n'
text=(source/'texture_cache.h').read_text();header=(source/'texture_cache_base.h').read_text()
context=function(header,'struct AsyncDecodeContext')+';\n'
helper=function(text,'inline void InvalidateAsyncDecode(') if 'inline void InvalidateAsyncDecode(' in text else ''
code=r'''
#include <algorithm>
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <deque>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <span>
#include <thread>
#include <utility>
#include <vector>
using u8=uint8_t;using u32=uint32_t;using u64=uint64_t;using DAddr=u64;using ImageId=u32;
#define LOG_DEBUG(...) ((void)0)
#define LOG_ERROR(...) ((void)0)
#define LOG_INFO(...) ((void)0)
#define UNIMPLEMENTED_IF(x) assert(!(x))
namespace Common {template<class T>struct ScratchBuffer:std::vector<T>{using std::vector<T>::vector;void resize_destructive(size_t n){this->resize(n);}};}
namespace boost::container{template<class T,size_t N>using small_vector=std::vector<T>;}
enum class ImageFlagBits:u32{Converted=1,IsDecoding=2,ZeroFilled=4,CpuModified=8,Tracked=16,GpuModified=32};
constexpr ImageFlagBits operator|(ImageFlagBits a,ImageFlagBits b){return ImageFlagBits(u32(a)|u32(b));}
constexpr ImageFlagBits operator&(ImageFlagBits a,ImageFlagBits b){return ImageFlagBits(u32(a)&u32(b));}
constexpr ImageFlagBits operator~(ImageFlagBits a){return ImageFlagBits(~u32(a));}
ImageFlagBits& operator|=(ImageFlagBits& a,ImageFlagBits b){return a=a|b;}
ImageFlagBits& operator&=(ImageFlagBits& a,ImageFlagBits b){return a=a&b;}
bool True(ImageFlagBits f){return u32(f)!=0;}bool False(ImageFlagBits f){return !True(f);}
struct BufferImageCopy{};struct ImageInfo{};
struct Staging{std::vector<u8> bytes;std::span<u8> mapped_span;explicit Staging(size_t n):bytes(n),mapped_span(bytes){}};
struct ImageBase{ImageFlagBits flags=ImageFlagBits::Converted|ImageFlagBits::ZeroFilled|ImageFlagBits::Tracked;
 u64 gpu_addr=0x1000,modification_tick=0,async_decode_generation=0;
 u32 unswizzled_size_bytes=4,guest_size_bytes=4;ImageInfo info;u8 displayed=0x77;
 void UploadMemory(Staging& s,const std::vector<BufferImageCopy>&){displayed=s.mapped_span[0];}
};using Image=ImageBase;
'''+helper+context+r'''
struct Memory{std::vector<u8> bytes=std::vector<u8>(4,0x11);};
namespace Tegra::Memory {
 enum class GuestMemoryFlags{UnsafeRead};
 template<class T,GuestMemoryFlags>struct GpuGuestMemory{
  std::span<T> data;GpuGuestMemory(::Memory& m,u64,size_t n,Common::ScratchBuffer<u8>*):data(m.bytes.data(),n){}
  operator std::span<T>(){return data;}
 };
}
std::vector<BufferImageCopy> UnswizzleImage(Memory&,u64,const ImageInfo&,std::span<u8> src,std::vector<u8>& dst){std::copy(src.begin(),src.end(),dst.begin());return {{}};}
void ConvertedLayout(const ImageInfo&,std::vector<BufferImageCopy>&){}
int conversions=0;
void ConvertImage(std::span<const u8> in,const ImageInfo&,std::span<u8> out,std::span<BufferImageCopy>){++conversions;std::copy(in.begin(),in.end(),out.begin());}
template<class T>T& FixSmallVectorADL(T& x){return x;}
bool IsWatchedImage(u64){return false;}void LogWholeUpload(const char*,u64,u64,u64,size_t){}
template<class P>struct TextureCache{
 struct Slots{std::map<ImageId,Image> values;Image& operator[](ImageId id){return values.at(id);}}slot_images;
 struct Runtime{int barriers=0;Staging UploadStagingBuffer(size_t n){return Staging(n);}void InsertUploadMemoryBarrier(){++barriers;}}runtime;
 struct Worker{std::vector<std::function<void()>> jobs;template<class F>void QueueWork(F f){jobs.emplace_back(std::move(f));}void Run(size_t n){auto job=std::move(jobs.at(n));job();}}texture_decode_worker;
 std::vector<std::unique_ptr<AsyncDecodeContext>> async_decodes;u64 async_decodes_queued=0,modification_tick=0;
 Memory memory;Memory* gpu_memory=&memory;Common::ScratchBuffer<u8> swizzle_data_buffer;
 TextureCache(){slot_images.values.emplace(1,Image{});}
 size_t MapSizeBytes(const Image&){return 4;}
 void QueueAsyncDecode(Image&,ImageId);void TickAsyncDecode();void WriteMemory(DAddr,size_t);void MarkModification(ImageBase&)noexcept;
 template<class F>void ForEachImageInRegion(u64,size_t,F f){for(auto& [id,image]:slot_images.values)f(id,image);}
 bool MarkSparseWrite(ImageId,Image&,DAddr,size_t){return false;}bool MarkPartialWrite(ImageBase&,DAddr,size_t){return false;}
 void UntrackImage(Image& image,ImageId){image.flags&=~ImageFlagBits::Tracked;}
};
'''
for sig in ['void TextureCache<P>::QueueAsyncDecode(', 'void TextureCache<P>::TickAsyncDecode(',
            'void TextureCache<P>::WriteMemory(', 'void TextureCache<P>::MarkModification(ImageBase&']:
 code+='template<class P>\n'+function(text,sig)
code+=r'''
int main(int argc,char**){
 const bool baseline=argc>1;
 {TextureCache<int> c;auto& image=c.slot_images[1];c.QueueAsyncDecode(image,1);
  c.memory.bytes.assign(4,0x22);c.WriteMemory(0x1000,4);
  // The fresh bytes were synchronously uploaded while the old background job waited.
  Staging fresh(4);std::fill(fresh.bytes.begin(),fresh.bytes.end(),0x22);image.UploadMemory(fresh,{{}});
  c.texture_decode_worker.Run(0);c.TickAsyncDecode();
  if(baseline){assert(image.displayed==0x11);std::puts("BASELINE REPRODUCED: stale async decode overwrites newer synchronous content");return 0;}
  assert(image.displayed==0x22);assert(c.async_decodes.empty());assert(False(image.flags&ImageFlagBits::IsDecoding));}
 {TextureCache<int> c;auto& image=c.slot_images[1];c.QueueAsyncDecode(image,1);
  image.displayed=0x44;c.MarkModification(image);c.texture_decode_worker.Run(0);c.TickAsyncDecode();
  assert(image.displayed==0x44);assert(True(image.flags&ImageFlagBits::GpuModified));}
 {TextureCache<int> c;auto& image=c.slot_images[1];int before=conversions;c.QueueAsyncDecode(image,1);
  c.memory.bytes.assign(4,0x33);c.WriteMemory(0x1000,4);c.QueueAsyncDecode(image,1);
  c.texture_decode_worker.Run(0);c.TickAsyncDecode();
  assert(conversions==before);assert(True(image.flags&ImageFlagBits::IsDecoding));assert(c.async_decodes.size()==1);
  c.texture_decode_worker.Run(1);c.TickAsyncDecode();assert(conversions==before+1);
  assert(image.displayed==0x33);assert(False(image.flags&ImageFlagBits::IsDecoding));assert(c.async_decodes.empty());}
 {TextureCache<int> c;auto& image=c.slot_images[1];c.QueueAsyncDecode(image,1);
  c.texture_decode_worker.Run(0);c.memory.bytes.assign(4,0x55);c.WriteMemory(0x1000,4);
  image.displayed=0x55;c.TickAsyncDecode();assert(image.displayed==0x55);}
 {TextureCache<int> c;c.QueueAsyncDecode(c.slot_images[1],1);c.async_decodes[0]->cancelled=true;
  c.slot_images.values.erase(1);c.texture_decode_worker.Run(0);c.TickAsyncDecode();assert(c.async_decodes.empty());}
 {TextureCache<int> c;auto& image=c.slot_images[1];int before=conversions;
  for(int n=1;n<=200;++n){c.memory.bytes.assign(4,u8(n));c.WriteMemory(0x1000,4);c.QueueAsyncDecode(image,1);}
  for(int n=0;n<199;++n){c.texture_decode_worker.Run(n);c.TickAsyncDecode();assert(True(image.flags&ImageFlagBits::IsDecoding));}
  assert(conversions==before);c.texture_decode_worker.Run(199);c.TickAsyncDecode();
  assert(conversions==before+1&&image.displayed==u8(200));assert(c.async_decodes.empty());}
 // Concurrent cancellation is atomic; the worker owns its input until completion.
 {TextureCache<int> c;auto& image=c.slot_images[1];c.QueueAsyncDecode(image,1);
  std::thread worker([&]{c.texture_decode_worker.Run(0);});c.async_decodes[0]->cancelled=true;
  worker.join();image.displayed=0x66;c.TickAsyncDecode();assert(image.displayed==0x66);}
 std::puts("Production async decode: CPU/GPU updates preserved, stale completions discarded, superseded work skipped, deletion/cancellation PASS");
}
'''
p=out/'decode.cpp';p.write_text(code)
subprocess.run(['clang++-18','-std=c++20','-pthread','-O1','-g','-fsanitize=address,undefined',str(p),'-o',str(out/'decode')],check=True)
subprocess.run([str(out/'decode')]+(['baseline'] if '--baseline' in sys.argv else []),check=True)
