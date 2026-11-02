// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
// Shared layout fixture. Define EDEN_TEXTURE_RECORD_DECODER to record calls;
// otherwise the caller links the production decoder for pixel comparisons.
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
enum class PixelFormat:u32{R8=1,R16=2,RGBA=4,RG32=8};
constexpr u32 BytesPerBlock(PixelFormat f){return u32(f);}
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
  bool native=true;bool UsesNativeTiling(){return native;}
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
#ifdef EDEN_TEXTURE_RECORD_DECODER
 namespace Texture{
 struct Call{const u8* src;u8* dst;u32 width,height,alignment;};inline std::vector<Call> calls;
 void UnswizzleTexture(std::span<u8> dst,std::span<const u8> src,u32 bpp,u32 w,u32 h,u32 d,u32,u32,u32 alignment,bool){assert(dst.size()>=size_t(w)*h*d*bpp);calls.push_back({src.data(),dst.data(),w,h,alignment});}
 void SwizzleTexture(std::span<u8> dst,std::span<const u8> src,u32 bpp,u32 w,u32 h,u32 d,u32,u32,u32 alignment,bool){assert(src.size()>=size_t(w)*h*d*bpp);calls.push_back({src.data(),dst.data(),w,h,alignment});}
 }
#endif
}
