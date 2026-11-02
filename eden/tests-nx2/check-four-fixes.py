"""Focused real-source regression checks for the four selected upstream fixes; dedie only."""
from pathlib import Path
import importlib.util,platform,re,subprocess,tempfile
assert platform.system()=='Linux','Run on dedie'
r=Path(__file__).resolve().parents[1];cache=Path((r/'.local/headless-cache').read_text().strip());src=cache/'source/src'
def method(text,signature):
 start=text.index(signature);pos=text.index('{',start);depth=1;end=pos+1
 while depth:depth+=(text[end]=='{')-(text[end]=='}');end+=1
 return text[start:end]
pre=r'''
#include <algorithm>
#include <array>
#include <bit>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <span>
#include <string>
#include <vector>
using u32=uint32_t;using u64=uint64_t;using s32=int32_t;using DAddr=u64;using VAddr=u64;
'''
with tempfile.TemporaryDirectory(prefix='four-fixes-') as tmp:
 p=Path(tmp)
 def run(name,code,extra=()):
  cpp=p/(name+'.cpp');cpp.write_text(pre+code);exe=p/name
  subprocess.run(['c++','-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer',*extra,str(cpp),'-o',str(exe)],check=True)
  subprocess.run([str(exe)],check=True)
 # Classify bound/bindless storage opcodes before they are rewritten to indexed ones.
 text=(src/'shader_recompiler/ir_opt/texture_pass.cpp').read_text()
 functions=method(text,'IR::Opcode IndexedInstruction(')+'\n'+method(text,'bool IsStorageImageOpcode(')
 names=sorted(set(re.findall(r'IR::Opcode::(\w+)',functions)))
 code='namespace IR{enum class Opcode{'+','.join(names)+'};struct Inst{Opcode op;Opcode GetOpcode()const{return op;}};}\n'+functions
 code+='\nint main(){using IR::Opcode;\n'
 for name in names:
  if not name.startswith(('Bound','Bindless')):continue
  expected=bool(re.search(r'Image(Read|Write|Atomic)',name))
  code+=f'assert(IsStorageImageOpcode(IndexedInstruction(IR::Inst{{Opcode::{name}}}))=={str(expected).lower()});\n'
 code+='puts("PASS storage reads/writes/atomics select surface descriptors; samples retain texture descriptors");}\n'
 assert '? env.SurfaceBoundBuffer() : env.TextureBoundBuffer()' in text
 run('storage-classification',code)
 # Real native lowering must keep the two tables independent in both instruction orders.
 rel=Path('shader_recompiler/frontend/ampere/lower_to_maxwell.h');(p/rel).parent.mkdir(parents=True)
 (p/rel).write_text((src/rel).read_text())
 run('native-tables',r'''
#include "shader_recompiler/frontend/ampere/lower_to_maxwell.h"
using namespace Shader::Ampere;
int main(){
 const Instruction tex{{0x00047b6f,2U<<22,0x000001ff,0}};
 const Instruction load{{0x08047b97,(3U<<22)|(3U<<29),0x001e0100,0}};
 const Instruction store{{0x08007b9b,4U|(3U<<22)|(3U<<29),0x00100f00,0}};
 const Instruction done{{0x794d,0,0x03800000,0}};
 for(const auto& code:{std::array{tex,load,store,done},std::array{store,tex,load,done}}){
  auto fixed=LowerToMaxwell(code);if(!fixed)std::fprintf(stderr,"lower failed: %s at %u\n",fixed.error.data(),fixed.error_offset);
  assert(fixed);assert(fixed.required_texture_buffer==2);assert(fixed.required_surface_buffer==3);
 }
 auto surface_only=LowerToMaxwell(std::array{store,done});assert(surface_only);assert(surface_only.required_texture_buffer==~0U&&surface_only.required_surface_buffer==3);
 puts("PASS native mixed tables in both orders and surface-only sentinel");}
''', ['-I'+str(p),'-I'+str(src)])
 # Actual MustFlushRegion plus both native DMA conditions with a recording query cache.
 text=(src/'video_core/renderer_vulkan/vk_rasterizer.cpp').read_text();must=method(text,'bool RasterizerVulkan::MustFlushRegion(')
 macro=(src/'video_core/macro.cpp').read_text();front=(src/'video_core/engines/maxwell_3d.cpp').read_text()
 paths=[method(macro,'if (memory.IsMemoryDirty(source, read_bytes,'),method(front,'if (memory_manager.IsMemoryDirty(source, read_bytes,')]
 code=r'''
#define LOG_INFO(...) (void)0
namespace VideoCommon{enum class CacheType{BufferCache=1,QueryCache=2,TextureCache=4};CacheType operator|(CacheType a,CacheType b){return CacheType(int(a)|int(b));}CacheType operator&(CacheType a,CacheType b){return CacheType(int(a)&int(b));}}
bool True(VideoCommon::CacheType a){return int(a)!=0;}
namespace Settings{bool IsGPULevelHigh(){return false;}}
struct Cache{std::mutex mutex;bool dirty=false;bool IsRegionGpuModified(DAddr,u64){return dirty;}};
struct RasterizerVulkan{Cache buffer_cache,texture_cache,query_cache;bool MustFlushRegion(DAddr,u64,VideoCommon::CacheType);};
'''+must+r'''
struct Memory{RasterizerVulkan& raster;u32 value=0;std::vector<int> events;
 bool IsMemoryDirty(DAddr a,u64 n,VideoCommon::CacheType which){events.push_back(1);return raster.MustFlushRegion(a,n,which);}
 void FlushRegion(DAddr,u64,VideoCommon::CacheType which){assert(True(which&VideoCommon::CacheType::QueryCache));events.push_back(2);value=73;raster.query_cache.dirty=false;}
 u32 Read(){events.push_back(3);return value;}
};
int main(){RasterizerVulkan r;Memory memory{r};Memory& memory_manager=memory;DAddr source=0x1000;u64 read_bytes=8;
'''
 for guard in paths:
  code+='r.query_cache.dirty=true;memory.value=0;memory.events.clear();\n'+guard+'\nassert(memory.Read()==73);assert((memory.events==std::vector<int>{1,2,3}));\n'
 code+='r.query_cache.dirty=false;assert(!r.MustFlushRegion(source,read_bytes,VideoCommon::CacheType::BufferCache|VideoCommon::CacheType::QueryCache));puts("PASS query-only dirtiness at low accuracy, flush-before-read on both native paths and clean no-op");}\n'
 run('query-dma',code)
 # Exact shader arithmetic, including the reciprocal-rounding regression, every D24 input.
 glsl=(src/'video_core/host_shaders/x8d24_conversion.glsl').read_text()
 run('depth',r'''
using uint=u32;using std::round;
uint floatBitsToUint(float v){return std::bit_cast<uint>(v);}float uintBitsToFloat(uint v){return std::bit_cast<float>(v);}
'''+glsl+r'''
int main(){for(uint d=0;d<0x1000000;++d){float z=DecodeX8D24(float(d&255)/255,float((d>>8)&255)/255,float((d>>16)&255)/255);assert(EncodeX8D24(z)==d);assert(z==float(double(d)/16777215.));}
 assert(EncodeX8D24(1)==0x00ffffff);assert(EncodeX8D24(0)==0);puts("PASS all 16777216 D24 values round-trip with correctly rounded normalization and zero padding");}
''')
 conversion=(src/'video_core/texture_cache/conversion.h').read_text();conversion='\n'.join(x for x in conversion.splitlines() if not x.startswith(('#include','#pragma')))
 code=r'''
namespace VideoCore::Surface{enum class PixelFormat{X8_D24_UNORM,A8B8G8R8_UNORM,B8G8R8A8_SRGB,R32_UINT,R16_UNORM};enum class SurfaceType{ColorTexture,Depth};
SurfaceType GetFormatType(PixelFormat f){return f==PixelFormat::X8_D24_UNORM?SurfaceType::Depth:SurfaceType::ColorTexture;}
int BytesPerBlock(PixelFormat f){return f==PixelFormat::R16_UNORM?2:4;}}
namespace VideoCommon{struct Sub{int base_level=0,base_layer=0,num_layers=1;};struct ImageCopy{Sub src_subresource,dst_subresource;std::array<int,3> src_offset{},dst_offset{},extent{};};}
'''+conversion+r'''
int main(){using namespace VideoCommon;using VideoCore::Surface::PixelFormat;
 for(auto f:{PixelFormat::A8B8G8R8_UNORM,PixelFormat::B8G8R8A8_SRGB,PixelFormat::R32_UINT})assert(GetAliasConversionFormat(f,PixelFormat::X8_D24_UNORM)==PixelFormat::A8B8G8R8_UNORM);
 assert(GetAliasConversionFormat(PixelFormat::R16_UNORM,PixelFormat::X8_D24_UNORM)==PixelFormat::R16_UNORM);
 ImageCopy c{{2,4,3},{1,7,3},{2,3,0},{4,5,0},{16,8,1}};auto out=MakeImageCopyLayers(std::span{&c,1});assert(out.size()==3);
 for(int i=0;i<3;++i){assert(out[i].src_subresource.base_layer==4+i&&out[i].dst_subresource.base_layer==7+i);assert(out[i].src_subresource.base_level==2&&out[i].dst_subresource.base_level==1);assert(out[i].src_offset==c.src_offset&&out[i].dst_offset==c.dst_offset&&out[i].extent==c.extent);assert(out[i].src_subresource.num_layers==1&&out[i].dst_subresource.num_layers==1);}
 puts("PASS raw-byte alias views and distinct layers/mip offsets");}
'''
 run('depth-alias',code)
 # Verify the mixed component lookup is actually added, not merely the conversion helpers.
 fmt=(src/'video_core/texture_cache/format_lookup_table.cpp').read_text();assert 'case Hash(TextureFormat::X8Z24, UNORM, UINT, UNORM, UNORM, LINEAR):' in fmt
 audio=method((src/'audio_core/renderer/sink/circular_buffer_sink_info.cpp').read_text(),'void CircularBufferSinkInfo::CleanUp(')
 run('audio',r'''
struct CircularBufferSinkInfo{enum class Type{Invalid,Circular};std::array<unsigned char,128> state,parameter;Type type;void CleanUp();};
'''+audio+r'''
int main(){CircularBufferSinkInfo a;a.state.fill(0xff);a.parameter.fill(0xa5);a.type=CircularBufferSinkInfo::Type::Circular;a.CleanUp();assert(a.type==CircularBufferSinkInfo::Type::Invalid);assert(std::ranges::all_of(a.state,[](auto x){return x==0;}));assert(std::ranges::all_of(a.parameter,[](auto x){return x==0;}));a.CleanUp();puts("PASS audio cleanup with arbitrary prior state, no bogus pointer dereference and repeated cleanup");}
''')
 # Compile/validate the actual two GPU conversion shaders, not only their arithmetic model.
 for name in ['convert_abgr8_to_x8d24','convert_x8d24_to_abgr8']:
  shader=src/'video_core/host_shaders'/(name+'.frag');spv=p/(name+'.spv')
  subprocess.run(['glslangValidator','-V','--target-env','vulkan1.0','-o',str(spv),str(shader)],check=True,stdout=subprocess.DEVNULL)
  subprocess.run(['spirv-val','--target-env','vulkan1.0',str(spv)],check=True)
 print('PASS both X8D24 GPU shaders compile and validate as SPIR-V')
 # Paired serialization and format invalidation are required with the new field.
 env=(src/'video_core/shader_environment.cpp').read_text()
 assert env.count('.write(reinterpret_cast<const char*>(&surface_bound), sizeof(surface_bound))')==1
 assert env.count('.read(reinterpret_cast<char*>(&surface_bound), sizeof(surface_bound))')==1
 assert '40U : 41U' in (src/'shader_recompiler/undef_policy.h').read_text()
 assert 'CACHE_VERSION = 18' in (src/'video_core/renderer_opengl/gl_shader_cache.cpp').read_text()
 print('PASS paired serialized surface field and both renderer cache generations')
