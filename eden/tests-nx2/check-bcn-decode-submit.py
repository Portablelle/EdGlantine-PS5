"""dedie only: real BCn transcode orchestration and real decoder submission policy.

Recording scheduler, not a Vulkan device: verifies ordering/ticks, not PS5 pixels.
"""
from pathlib import Path
import os,platform,subprocess
assert platform.system()=='Linux','Run on dedie only'
root=Path(__file__).resolve().parents[1]
source=Path((root/'.local/headless-cache').read_text().strip())/'source/src/video_core/renderer_vulkan'
out=root/'build/nx2-tests/bcn-decode-submit';out.mkdir(parents=True,exist_ok=True)
def function(text,signature):
 start=text.index(signature);brace=text.index('{',start);end=brace+1;depth=1
 while depth:
  depth+=(text[end]=='{')-(text[end]=='}');end+=1
 return text[start:end]+'\n'
texture=(source/'vk_texture_cache.cpp').read_text()
compute=(source/'vk_compute_pass.cpp').read_text()
transcode=function(texture,'void TextureCacheRuntime::TranscodeAstcToBcn(')
assert '.wait = true,' in transcode
old=transcode.replace('TextureCacheRuntime::TranscodeAstcToBcn(', 'TextureCacheRuntime::OldTranscodeAstcToBcn(').replace('.wait = true,','.wait = false,')
decoder=function(compute,'void ASTCDecoderPass::AssembleInto(')
# The real scheduling tail runs after the recorded compute->shader barrier.
tail=decoder[decoder.index('    static const char* const flush_setting'):]
code=r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <functional>
#include <span>
#include <string>
#include <utility>
#include <vector>
using u32=uint32_t;using s32=int32_t;using u64=uint64_t;
#define LOG_INFO(...) ((void)0)
constexpr int VK_FORMAT_A8B8G8R8_UNORM_PACK32=1,VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO=2,
VK_IMAGE_TYPE_2D=3,VK_SAMPLE_COUNT_1_BIT=4,VK_IMAGE_TILING_OPTIMAL=5,
VK_IMAGE_USAGE_STORAGE_BIT=6,VK_SHARING_MODE_EXCLUSIVE=7,VK_IMAGE_LAYOUT_UNDEFINED=8,
VK_IMAGE_ASPECT_COLOR_BIT=9,VK_STRUCTURE_TYPE_MEMORY_BARRIER=10,
VK_ACCESS_SHADER_WRITE_BIT=11,VK_ACCESS_TRANSFER_READ_BIT=12,
VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT=13,VK_PIPELINE_STAGE_TRANSFER_BIT=14;
using VkFormat=int;
struct VkImageCreateInfo {int sType;void* pNext;int flags,imageType,format;
 struct {u32 width,height,depth;}extent;u32 mipLevels,arrayLayers;int samples,tiling,usage,sharingMode;
 u32 queueFamilyIndexCount;void* pQueueFamilyIndices;int initialLayout;};
struct VkMemoryBarrier {int sType;void* pNext;int srcAccessMask,dstAccessMask;};
struct Handle{int value=1;int operator*()const{return value;}};
namespace vk{struct CommandBuffer{void PipelineBarrier(int,int,int,VkMemoryBarrier){}};}
namespace Common{template<class T>T DivCeil(T a,T b){return (a+b-1)/b;}}
namespace boost::container{template<class T,size_t N>using small_vector=std::vector<T>;}
namespace Settings{enum class AstcRecompression{Bc1,Bc3};struct {struct {
 AstcRecompression value=AstcRecompression::Bc3;AstcRecompression GetValue(){return value;}
 }astc_recompression;}values;}
namespace VideoCommon{
struct ImageInfo{struct {u32 width=33,height=17;}size;struct {s32 levels=3,layers=2;}resources;
 bool native_tiling=true,opaque=false;};struct SwizzleParameters{};
struct BufferImageCopy{u64 buffer_offset,buffer_size;u32 buffer_row_length,buffer_image_height;
 struct{s32 base_level,base_layer,num_layers;}image_subresource;struct{s32 x,y,z;}image_offset;
 struct{u32 width,height,depth;}image_extent;};}
using ImageInfo=VideoCommon::ImageInfo;
struct Scheduler{std::vector<std::string> events;u64 tick=1;int flushes=0,finishes=0;
 void Flush(){++flushes;events.push_back("flush");++tick;}
 void Finish(){++finishes;events.push_back("finish");++tick;}
 u64 CurrentTick(){return tick;}template<class F>void Record(F f){f(vk::CommandBuffer{});events.push_back("barrier");}
};
struct Image{ImageInfo info;u32 host_level_offset=1,guest_size_bytes=65536;Scheduler* scheduler;
 void UploadMemory(int,u32,const std::vector<VideoCommon::BufferImageCopy>& copies){
  assert(!copies.empty());for(const auto& c:copies)assert(c.image_subresource.num_layers==info.resources.layers);
  scheduler->events.push_back("image-upload");}
};
struct StagingBufferRef{};
namespace MemoryUsage{constexpr int DeviceLocal=1;}
struct ASTCDecoderPass{
 Scheduler& scheduler;
 struct Target{int image,aspect_mask;bool initialized;std::function<int(s32)> level_view;bool wait;};
 void AssembleInto(const ImageInfo& info,u32 skip,u32,const Target& target,const StagingBufferRef&,
                   std::span<const VideoCommon::SwizzleParameters>){
  assert(target.level_view(0)==1);scheduler.events.push_back("decode");
  scheduler.events.push_back("compute-to-shader-barrier");
'''+tail+r'''
};
struct Encoder{Scheduler& scheduler;std::vector<u64> ticks;
 void Encode(int,u32 w,u32 h,u32 layers,bool bc3,int,u32,u64,u64){
  assert(w&&h&&layers);assert(bc3==(Settings::values.astc_recompression.GetValue()==Settings::AstcRecompression::Bc3));
  ticks.push_back(scheduler.CurrentTick());scheduler.events.push_back("encode");}
};
struct PendingTranscode{u64 tick;Handle image;std::vector<Handle> views;};
Handle MakeStorageView(int,s32,int,int){return {};}
bool IsOpaqueBc1Astc(int,const ImageInfo& info){return info.opaque;}
struct TextureCacheRuntime{
 Scheduler scheduler;int device=0;
 struct Allocator{Handle CreateImage(VkImageCreateInfo i){assert(i.mipLevels&&i.arrayLayers);return {};}}memory_allocator;
 struct Pool{struct Output{int buffer=2;u32 offset=256;};Output Request(u64 n,int){assert(n>0);return {};}}staging_buffer_pool;
 struct Device{int GetLogical(){return 0;}operator int()const{return 0;}}device_object;
 ASTCDecoderPass decoder{scheduler};ASTCDecoderPass* astc_decoder_pass=&decoder;
 Encoder encoder{scheduler};Encoder* bc_encoder_pass=&encoder;std::vector<PendingTranscode> pending_transcodes;
 void TranscodeAstcToBcn(Image&,const StagingBufferRef&,std::span<const VideoCommon::SwizzleParameters>);
 void OldTranscodeAstcToBcn(Image&,const StagingBufferRef&,std::span<const VideoCommon::SwizzleParameters>);
};
'''
# Keep the actual device API used by the production function.
code=code.replace('Scheduler scheduler;int device=0;','Scheduler scheduler;').replace('}device_object;','}device;')
code+=transcode+old+r'''
int main(){
 const char* env=std::getenv("EDEN_NX2_ASTC_FLUSH");
 for(bool native:{false,true})for(auto format:{Settings::AstcRecompression::Bc1,Settings::AstcRecompression::Bc3}){
  Settings::values.astc_recompression.value=format;
  const bool flush=env?env[0]=='1':native;
  TextureCacheRuntime fixed;Image image;image.info.native_tiling=native;image.scheduler=&fixed.scheduler;
  fixed.TranscodeAstcToBcn(image,{},{});
  assert(fixed.scheduler.flushes==(flush?1:0));assert(fixed.scheduler.finishes==(flush?0:1));
  assert(fixed.encoder.ticks.size()==2);for(auto tick:fixed.encoder.ticks)assert(tick==2);
  assert(fixed.pending_transcodes.size()==1&&fixed.pending_transcodes[0].tick==2);
  const auto& events=fixed.scheduler.events;
  assert(events[0]=="decode"&&events[1]=="compute-to-shader-barrier");
  assert(events[2]==(flush?"flush":"finish")&&events[3]=="encode");
  assert(events.back()=="image-upload");
  TextureCacheRuntime previous;image.scheduler=&previous.scheduler;
  previous.OldTranscodeAstcToBcn(image,{},{});
  assert(previous.scheduler.flushes==0&&previous.scheduler.finishes==0);
  for(auto tick:previous.encoder.ticks)assert(tick==1); // old path lacked the submission boundary
  assert(previous.pending_transcodes[0].tick==1);
 }
 std::puts("BC1/BC3, native/legacy, trimmed mips/layers, decode-before-encode and retirement tick: PASS");
}
'''
p=out/'transcode.cpp';p.write_text(code)
subprocess.run(['clang++-18','-std=c++20','-O1','-g','-fsanitize=address,undefined',str(p),'-o',str(out/'transcode')],check=True)
for value in (None,'0','1'):
 env=os.environ.copy();env.pop('EDEN_NX2_ASTC_FLUSH',None)
 if value is not None:env['EDEN_NX2_ASTC_FLUSH']=value
 subprocess.run([str(out/'transcode')],env=env,check=True)
print('Actual transcode and decoder submission policy: PASS (ASan/UBSan; default/finish/flush)')
