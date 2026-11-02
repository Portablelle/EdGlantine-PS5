"""Run actual graphics/compute binding methods against GPU-written uniform data."""
from pathlib import Path
import platform,subprocess,resource,tempfile
assert platform.system()=='Linux','Run on dedie'
r=Path(__file__).resolve().parents[1]
scratch=Path((r/'.local/headless-cache').read_text().strip())
fixed=(scratch/'source/src/video_core/buffer_cache/buffer_cache.h').read_text()
with tempfile.TemporaryDirectory(prefix='uniform-baseline-') as temp:
    baseline=Path(temp);header=baseline/'src/video_core/buffer_cache/buffer_cache.h'
    header.parent.mkdir(parents=True);header.write_text(fixed)
    subprocess.run(['patch','-R','-s','-p1','-d',str(baseline)],input=(r/'tools/eden-patches/97-nx2-unaligned-uniform-readback.diff').read_bytes(),check=True)
    original=header.read_text()
def function(s,name):
 a=s.index('template <class P>\nvoid BufferCache<P>::'+name+'(');b=s.index('{',a);depth=1;end=b+1
 while depth:depth+=(s[end]=='{')-(s[end]=='}');end+=1
 return s[a:end]
scaffold=r'''
#include <array>
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <span>
#include <stdexcept>
#include <string>
#include <vector>
#include <algorithm>
using u8=uint8_t;using u32=uint32_t;using u64=uint64_t;using DAddr=u64;
constexpr u32 NULL_BUFFER_ID=0;
namespace Shader {using NotImplementedException=std::runtime_error;}
namespace Tegra {struct NativeRootTables{static bool IsBank(u32){return false;}};}
std::vector<std::string> events;
struct Binding{DAddr device_addr=0x1040;u32 size=64,buffer_id=1;};
struct Buffer{u32 Offset(DAddr a){return u32(a-0x1000);}void MarkUsage(u32,u32){}};
struct Memory{
 std::array<u8,4096> cpu{},gpu{};
 void ReadBlockUnsafe(DAddr a,u8* p,size_t n){events.push_back("read");std::memcpy(p,cpu.data()+a-0x1000,n);}
};
struct Tracker{bool dirty=true;bool IsRegionGpuModified(DAddr,u32){return dirty;}};
struct Runtime{
 std::array<u8,64> mapped{};bool cached=false;
 u32 GetUniformBufferAlignment(){return 256;}
 std::span<u8> BindMappedUniformBuffer(size_t,u32,u32 size){assert(size==mapped.size());events.push_back("map");return mapped;}
 bool HasFastBufferSubData(){return false;}
 bool SupportsNonZeroUniformOffset(){return true;}
 void BindFastUniformBuffer(size_t,u32,u32){}
 void PushFastUniformBuffer(size_t,u32,std::span<const u8>){}
 void BindUniformBuffer(Buffer&,u32,u32){cached=true;events.push_back("cached");}
 void BindUniformBuffer(size_t,u32,Buffer& b,u32 o,u32 n){BindUniformBuffer(b,o,n);}
 void BindComputeUniformBuffer(u32,Buffer& b,u32 o,u32 n){BindUniformBuffer(b,o,n);}
};
struct Channel{
 using Sizes=std::array<std::array<u32,18>,6>;
 Sizes sizes{};Sizes* uniform_buffer_sizes=&sizes;
 std::array<u32,18> compute_sizes{};std::array<u32,18>* compute_uniform_buffer_sizes=&compute_sizes;
 std::array<std::array<Binding,18>,6> uniform_buffers{};
 std::array<Binding,18> compute_uniform_buffers{};
 std::array<u32,6> fast_bound_uniform_buffers{},dirty_uniform_buffers{};
 std::array<std::array<u32,18>,6> uniform_buffer_binding_sizes{};
 std::array<u32,1> uniform_cache_shots{},uniform_cache_hits{};
 u32 uniform_buffer_skip_cache_size=512,enabled_compute_uniform_buffer_mask=1;
 Channel(){for(auto& a:sizes)a.fill(64);compute_sizes.fill(64);}
};
struct Maxwell{
 struct {bool native_turing=false;} macro;
 auto& GetNativeMacroEngine(){return macro;}
 struct {std::array<u32,4> words{};auto& Data(u32){return words;}} native_root_tables;
};
struct Policy{};
template<class P> struct BufferCache{
 static constexpr bool IS_OPENGL=false,HAS_PERSISTENT_UNIFORM_BUFFER_BINDINGS=false,NEEDS_BIND_UNIFORM_INDEX=false;
 Channel state;Channel* channel_state=&state;std::array<Buffer,2> slot_buffers;
 Memory device_memory;Tracker memory_tracker;Runtime runtime;Maxwell maxwell;Maxwell* maxwell3d=&maxwell;
 void TouchBuffer(Buffer&,u32){}
 bool HasFastUniformBufferBound(size_t,u32){return false;}
 std::span<const u8> ImmediateBufferWithData(DAddr a,u32 n){return {device_memory.cpu.data()+a-0x1000,n};}
 bool SynchronizeBuffer(Buffer&,DAddr a,u32 n){assert(a==state.uniform_buffers[0][0].device_addr&&n==64);events.push_back("sync");return true;}
 void DownloadBufferMemory(Buffer&,DAddr a,u32 n){
  assert(a==state.uniform_buffers[0][0].device_addr&&n==64);events.push_back("download");
  std::memcpy(device_memory.cpu.data()+a-0x1000,device_memory.gpu.data()+a-0x1000,n);
  runtime.mapped.fill(0xdd); // readback may retire/recycle earlier staging contents
  memory_tracker.dirty=false;
 }
 void BindHostGraphicsUniformBuffer(size_t,u32,u32,bool);
 void BindHostComputeUniformBuffers();
};
template<class F>void ForEachEnabledBit(u32 mask,F&& f){for(u32 i=0;i<32;++i)if(mask&(1u<<i))f(i);}
'''
checks=r'''
int main(){
 for(bool compute:{false,true})for(bool aligned:{false,true})for(bool dirty:{false,true}){
  BufferCache<Policy> c;events.clear();c.memory_tracker.dirty=dirty;
  const DAddr address=aligned?0x1100:0x1040;
  c.state.uniform_buffers[0][0].device_addr=address;c.state.compute_uniform_buffers[0].device_addr=address;
  c.device_memory.cpu.fill(0x21);c.device_memory.gpu.fill(0x73);
  if(compute)c.BindHostComputeUniformBuffers();else c.BindHostGraphicsUniformBuffer(0,0,0,true);
  if(!aligned&&dirty){
   if(c.runtime.mapped[0]!=0x73)return 1; // original bug: stale CPU transforms copied
   assert((events==std::vector<std::string>{"sync","download","map","read"}));
   assert(c.device_memory.cpu[size_t(address-0x1000)-1]==0x21);
   assert(c.device_memory.cpu[size_t(address-0x1000)+64]==0x21);
  }else if(!dirty){
   assert(c.runtime.mapped[0]==0x21);
   assert((events==std::vector<std::string>{"map","read"}));
  }else{
   assert(c.runtime.cached);assert((events==std::vector<std::string>{"sync","cached"}));
  }
 }
}
'''
out=r/'build/uniform-alignment-check';out.mkdir(parents=True,exist_ok=True)
resource.setrlimit(resource.RLIMIT_CORE,(0,0))
for label,text in [('original',original),('fixed',fixed)]:
 source=scaffold+'\n'+function(text,'BindHostGraphicsUniformBuffer')+'\n'+function(text,'BindHostComputeUniformBuffers')+'\n'+checks
 p=out/(label+'.cpp');p.write_text(source);exe=out/label
 subprocess.run(['c++','-std=c++20','-O1','-g','-fsanitize=address,undefined',str(p),'-o',str(exe)],check=True)
 result=subprocess.run([str(exe)],capture_output=True,text=True)
 (out/(label+'.log')).write_text(result.stdout+result.stderr)
 assert result.returncode==(1 if label=='original' else 0),(label,result.returncode,result.stderr)
print('PASS: original stale-transform read reproduced; actual graphics/compute bindings synchronize GPU-written unaligned uniforms before staging allocation; clean/aligned paths and neighboring CPU bytes preserved (ASan/UBSan).')
