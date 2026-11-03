"""Production DMA admission and readback cache contracts; compile only on dedie."""
from pathlib import Path
import os,platform,subprocess,tempfile
assert platform.system()=='Linux','Compile on dedie'
r=Path(__file__).resolve().parents[1];src=Path((r/'.local/headless-cache').read_text().strip())/'source/src'
cpp=r'''
#include <cassert>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include "video_core/native_dma_snapshot.h"
using namespace VideoCommon;
struct Memory {
 static constexpr u64 Base=0x100000;
 std::array<u8,65536> cpu{},gpu{};std::array<bool,65536> dirty{};
 ReadbackWindowCache<u64> cache;
 unsigned waits=0,coherent=0,unsafe=0;bool continuous=true,mapped=true,throw_read=false,seen_scope=false;
 std::optional<u64> GpuToCpuAddress(u64 a){return mapped&&a<cpu.size()?std::optional{a+Base}:std::nullopt;}
 bool IsContinuousRange(u64,size_t){return continuous;}
 bool IsMemoryDirty(u64 a,size_t n){for(size_t i=a;i<a+n;++i)if(dirty[i])return true;return false;}
 void GpuWrite(u64 a,size_t n,u8 value){cache.Invalidate(a+Base,n);for(size_t i=a;i<a+n;++i){gpu[i]=value;dirty[i]=true;}}
 void CpuWrite(u64 a,u8 value){cpu[a]=value;dirty[a]=false;}
 void ReadBlockUnsafe(u64 a,void*p,size_t n){++unsafe;std::memcpy(p,cpu.data()+a,n);}
 void ReadBlock(u64 a,void*p,size_t n){
  ++coherent;seen_scope=IsParameterReadback(a+Base,n);
  if(throw_read)throw std::runtime_error("reader");
  if(IsMemoryDirty(a,n)){
   auto view=seen_scope?cache.Find(a+Base,n):std::nullopt;
   u64 window=ReadbackWindowBytes(),begin=a/window*window;
   if(!view){++waits;if(seen_scope&&a+n<=begin+window){
      assert(window<=4096);assert(cache.Store(begin+Base,std::span(gpu).subspan(begin,window)));
      view=cache.Find(a+Base,n,false);
   }}
   for(size_t i=a;i<a+n;++i)if(dirty[i]){cpu[i]=view?view->bytes[i+Base-view->address]:gpu[i];dirty[i]=false;}
  }
  std::memcpy(p,cpu.data()+a,n);
 }
};
int main(){
 // Same producer, many small owned command snapshots: original boundary never admitted caching.
 Memory old,now;old.cpu.fill(0xaa);now.cpu.fill(0xaa);
 old.GpuWrite(0,4096,0x55);now.GpuWrite(0,4096,0x55);
 std::array<u8,16> a{},b{};
 for(unsigned i=0;i<64;++i){old.ReadBlock(i*32,a.data(),a.size());
  Tegra::ReadNativeDmaCommandSnapshot(now,i*32,b.data(),b.size(),true);assert(a==b);
  assert(!IsParameterReadback(Memory::Base,1));}
 assert(old.waits==64&&now.waits==1);assert(now.coherent==64&&now.unsafe==0);
 // Never publish speculative neighboring GPU bytes to CPU memory.
 assert(now.cpu[16]==0xaa);now.CpuWrite(3000,0x77);
 Tegra::ReadNativeDmaCommandSnapshot(now,3000,b.data(),1,true);assert(b[0]==0x77&&now.waits==1);
 // A fresh GPU producer invalidates the real cache, including future owned snapshots.
 auto retained=b;now.GpuWrite(0,16,0x33);
 Tegra::ReadNativeDmaCommandSnapshot(now,0,b.data(),16,true);assert(b[0]==0x33&&now.waits==2);
 // An owned parser copy is immutable after later producers overwrite its source.
 auto owned=b;now.GpuWrite(0,16,0x44);assert(owned[0]==0x33);
 Tegra::ReadNativeDmaCommandSnapshot(now,0,b.data(),16,true);assert(b[0]==0x44&&owned[0]==0x33);
 // Disabled/large/sparse mappings retain the ordinary coherent loader and no cache scope.
 for(unsigned mode=0;mode<3;++mode){Memory m;m.GpuWrite(0,8192,0x22);m.continuous=mode!=0;m.mapped=mode!=1;
  std::array<u8,8192> out{};size_t bytes=mode==2?8192:16;
  Tegra::ReadNativeDmaCommandSnapshot(m,0,out.data(),bytes,true);assert(!m.seen_scope&&m.waits==1&&out[0]==0x22);}
 // A contiguous request straddling a cache window falls back, not a truncated snapshot.
 Memory cross;cross.GpuWrite(4090,16,0x66);Tegra::ReadNativeDmaCommandSnapshot(cross,4090,b.data(),16,true);
 assert(b.front()==0x66&&b.back()==0x66&&cross.waits==1&&cross.cache.RetainedBytes()==0);
 // Unsafe policy is untouched; split-owned dirty snapshots still use coherent I/O.
 Memory m;m.GpuWrite(0,16,0x99);Tegra::ReadNativeDmaCommandSnapshot(m,0,b.data(),16,false);
 assert(m.unsafe==1&&m.coherent==0&&b[0]==0);
 Tegra::ReadOwnedNativeDmaSnapshot(m,0,b.data(),16,false);assert(m.coherent==1&&b[0]==0x99);
 Tegra::ReadOwnedNativeDmaSnapshot(m,0,b.data(),16,false);assert(m.unsafe==2);
 // Reproduce Low+Default's old stale CPU snapshot and exercise the real new policy.
 Memory low_old,low_fixed;low_old.GpuWrite(0,16,0x88);low_fixed.GpuWrite(0,16,0x88);
 Tegra::ReadNativeDmaCommandSnapshot(low_old,0,a.data(),16,false);assert(a[0]==0);
 Tegra::ReadNativeDmaSoloSnapshot(low_fixed,0,b.data(),16,false,true);
 assert(b[0]==0x88&&low_fixed.coherent==1&&low_fixed.unsafe==0);
 Memory clean;clean.CpuWrite(0,0x77);
 Tegra::ReadNativeDmaSoloSnapshot(clean,0,b.data(),16,false,true);
 assert(b[0]==0x77&&clean.unsafe==1&&clean.coherent==0);
 Memory explicit_unsafe;explicit_unsafe.GpuWrite(0,16,0x99);
 Tegra::ReadNativeDmaSoloSnapshot(explicit_unsafe,0,b.data(),16,false,false);
 assert(b[0]==0&&explicit_unsafe.unsafe==1&&explicit_unsafe.coherent==0);
 for(bool default_dma:{false,true}){Memory high;high.GpuWrite(0,16,0x66);
  Tegra::ReadNativeDmaSoloSnapshot(high,0,b.data(),16,true,default_dma);
  assert(b[0]==0x66&&high.coherent==1&&high.unsafe==0);}
 std::cout<<"LOW_DEFAULT_STALE_SNAPSHOT_REPRODUCED_AND_FIXED\n";
 // Scope state unwinds on exceptions and preserves an enclosing parameter boundary.
 {ParameterReadbackScope outer{Memory::Base,65536,true};assert(ReadbackWindowBytes()==65536);
  Memory fail;fail.throw_read=true;
  try{Tegra::ReadNativeDmaCommandSnapshot(fail,0,b.data(),16,true);assert(false);}catch(const std::runtime_error&){}
  assert(IsParameterReadback(Memory::Base+60000,4)&&ReadbackWindowBytes()==65536);}
 assert(!IsParameterReadback(Memory::Base,1));
 std::cout<<"NATIVE_DMA_READBACK_CONTRACT_PASS old_waits=64 cached_waits=1\n";
}
'''
with tempfile.TemporaryDirectory(prefix='native-command-readback-') as td:
 t=Path(td);(t/'test.cpp').write_text(cpp)
 subprocess.run(['clang++-18','-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer','-DEDEN_NX2_PS5_PROTO','-I'+str(src),str(t/'test.cpp'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True)
# Both production parser paths retain ownership; cache admission never spans command execution.
s=(src/'video_core/dma_pusher.cpp').read_text();assert 'ReadNativeDmaSoloSnapshot(memory_manager, dma_state.dma_get,' in s
assert 'Settings::IsDMALevelDefault());' in s
assert 'ReadOwnedNativeDmaSnapshot(*memory' in s and 'command_resume_offset == 0' in s
b=(src/'video_core/buffer_cache/buffer_cache.h').read_text();assert 'ReadbackWindowBytes()' in b
print('NATIVE_DMA_READBACK_INTEGRATION_PASS')
# Compile real ProcessMacro + RefreshParametersImpl, including their storage/lifetime interaction.
text=(src/'video_core/engines/maxwell_3d.cpp').read_text()
def extract(signature):
 a=text.index(signature);end=text.index('{',a)+1;depth=1
 while depth:
  depth+=(text[end]=='{')-(text[end]=='}');end+=1
 return text[a:end]
refresh=extract('void Maxwell3D::RefreshParametersImpl()')
process=extract('void Maxwell3D::ProcessMacro(')
# Reproduce the intermediate bug Cubic found: new refresh with the previous stack admission.
broken=process.replace('void Maxwell3D::ProcessMacro(', 'void Maxwell3D::ProcessMacroBroken(',1)
guard='!Settings::IsGPULevelHigh() &&\n        !(GetNativeMacroEngine().native_turing && Settings::IsDMALevelDefault())) {'
assert guard in broken
broken=broken.replace(guard,'!Settings::IsGPULevelHigh()) {',1)
code=r'''
#include <cassert>
#include <cstdlib>
#include <cstring>
#include <vector>
#include "video_core/native_dma_snapshot.h"
#define ASSERT assert
namespace Core {struct System {};}
namespace Settings {inline bool high=true,dma_default=true;
inline bool IsGPULevelHigh(){return high;}inline bool IsDMALevelDefault(){return dma_default;}}
struct Memory {
 unsigned reads{};
 std::optional<u64> GpuToCpuAddress(u64 a){return a;}
 bool IsContinuousRange(u64,size_t){return true;}
 void ReadBlock(u64 a,void* p,size_t n){assert(a>=0x2000&&a+n<=0x3000&&n%4==0);
  assert(VideoCommon::IsParameterReadback(a,n));assert(VideoCommon::ReadbackWindowBytes()==65536);
  for(size_t i=0;i<n/4;++i){u32 value=77+(a-0x2000)/4+i;std::memcpy(static_cast<u8*>(p)+i*4,&value,4);}++reads;}
};
struct Maxwell3D {
 struct {bool native_turing{};} native;
 auto& GetNativeMacroEngine(){return native;}
 Memory memory_manager;
 std::vector<std::pair<u64,size_t>> macro_segments;
 std::vector<u32> macro_params,observed;
 u32 executing_macro{};u64 current_dma_segment{};bool current_dirty{},current_macro_dirty{},bad_storage{},vector_call{};
 void RefreshParametersImpl();
 void ProcessMacro(Core::System&,u32,const u32*,u32,bool);
 void ProcessMacroBroken(Core::System&,u32,const u32*,u32,bool);
 void ConsumeSink(Core::System&){}
 void CallMacroMethod(Core::System&,u32,std::span<const u32> args){
  const bool needs_refresh=Settings::high||(native.native_turing&&Settings::dma_default);
  vector_call=!macro_params.empty()&&args.data()==macro_params.data();
  if(current_macro_dirty&&needs_refresh){
   // Detect the invalid storage without performing the out-of-bounds store.
   if(!vector_call){bad_storage=true;return;}
   RefreshParametersImpl();
  }
  observed.assign(args.begin(),args.end());executing_macro=0;
 }
};
'''+refresh+'\n'+process+'\n'+broken+r'''
int main(){
 unsetenv("EDEN_NX2_MACRO_COPY");Core::System system;
 Settings::high=false;Settings::dma_default=true;
 Maxwell3D intermediate;intermediate.native.native_turing=true;intermediate.current_dirty=true;
 intermediate.current_dma_segment=0x2000;u32 arg=22;
 intermediate.ProcessMacroBroken(system,2,&arg,1,true);assert(intermediate.bad_storage);
 std::puts("INTERMEDIATE_LOW_STACK_STORAGE_BUG_REPRODUCED");
 for(bool high:{false,true})for(bool native:{false,true})for(bool default_dma:{false,true}){
  Settings::high=high;Settings::dma_default=default_dma;bool required=high||(native&&default_dma);
  // Actual refresh method with one immediate and one GPU-backed segment.
  Maxwell3D direct;direct.native.native_turing=native;direct.macro_segments={{0,1},{0x2000,1}};
  direct.macro_params={11,22};direct.RefreshParametersImpl();
  assert(direct.memory_manager.reads==unsigned(required));
  assert(direct.macro_params[0]==11&&direct.macro_params[1]==(required?77U:22U));
  // Complete scalar, stack boundary, and larger-than-stack calls.
  for(u32 count:{1U,64U,65U}){
   Maxwell3D engine;engine.native.native_turing=native;engine.current_dma_segment=0x2000;engine.current_dirty=true;
   std::vector<u32> input(count,22);engine.ProcessMacro(system,2,input.data(),count,true);
   assert(!engine.bad_storage&&engine.observed.size()==count);
   assert(engine.vector_call==(required||count>64));
   for(u32 i=0;i<count;++i)assert(engine.observed[i]==(required?77+i:22));
   assert(engine.macro_params.empty()&&engine.macro_segments.empty()&&!engine.current_macro_dirty);
  }
  // Split arrival must keep the same mutable vector and refresh both recorded sources.
  Maxwell3D split;split.native.native_turing=native;std::array<u32,5> input{22,22,22,22,22};
  split.current_dma_segment=0x2000;split.current_dirty=true;split.ProcessMacro(system,2,input.data(),2,false);
  assert(split.observed.empty()&&split.macro_params.size()==2);
  split.current_dma_segment=0x2008;split.current_dirty=true;split.ProcessMacro(system,3,input.data()+2,3,true);
  assert(!split.bad_storage&&split.vector_call&&split.observed.size()==5);
  for(u32 i=0;i<5;++i)assert(split.observed[i]==(required?77+i:22));
  assert(split.macro_params.empty()&&split.macro_segments.empty());
  assert(!VideoCommon::IsParameterReadback(0x2000,4));
 }
 std::puts("NATIVE_LOW_PARAMETER_STORAGE_AND_REFRESH_PASS");
}
'''
with tempfile.TemporaryDirectory(prefix='native-low-parameter-refresh-') as td:
 t=Path(td);(t/'check.cpp').write_text(code)
 subprocess.run(['clang++-18','-std=c++20','-O1','-g','-fsanitize=address,undefined','-DEDEN_NX2_PS5_PROTO','-I'+str(src),str(t/'check.cpp'),'-o',str(t/'check')],check=True)
 subprocess.run([str(t/'check')],check=True)
# Compile the actual history storage/inline writer and diagnostic in both build modes.
header=(src/'video_core/engines/maxwell_3d.h').read_text()
assert '#include <cstdlib>' in header
history=header[header.index('    struct RecentWrite {'):header.index('    void DumpRecentWrites(')]
code=r'''
#include <array>
#include <cstdlib>
#include <cstdint>
#include <string>
#include <vector>
using u32=uint32_t;
std::vector<std::string> logs;
#define LOG_ERROR(category,message,...) logs.emplace_back(message)
#define CHECK(x) do {if(!(x)) std::abort();} while(false)
struct Maxwell3D {
 u32 executing_macro=7;std::vector<u32> macro_params{1,2};
 void DumpRecentWrites(u32);
'''+history+'};\n'+extract('void Maxwell3D::DumpRecentWrites(')+r'''
int main(int argc,char**argv){
 const bool enabled=std::string(argv[1])=="enabled";
 // Match PS5 dev-settings: set the environment after startup, before construction.
 if(argc>2)CHECK(setenv("EDEN_NX2_3D_HISTORY",argv[2],1)==0);
 Maxwell3D engine;
 for(u32 i=1;i<=50;++i)engine.RecordWrite(i,i+100,1,i+200);
 CHECK(engine.recent_write_index==(enabled?50U:0U));
 if(enabled){
  for(size_t i=0;i<engine.recent_writes.size();++i){
   const auto& w=engine.recent_writes[(engine.recent_write_index+i)%engine.recent_writes.size()];
   CHECK(w.method==i+3&&w.argument==i+103&&w.amount==1&&w.pending==i+203);
  }
 }else for(const auto& w:engine.recent_writes)CHECK(w.amount==0);
 engine.DumpRecentWrites(9);
 CHECK(logs.size()==(enabled?49U:2U));
 CHECK(logs[0].find("collects parameters")!=std::string::npos);
 if(!enabled)CHECK(logs[1]=="Register write history disabled; EDEN_NX2_3D_HISTORY=1 enables it");
 // Preserve the existing diagnostic rate limit.
 for(unsigned i=0;i<3;++i)engine.DumpRecentWrites(9);
 const auto count=logs.size();engine.DumpRecentWrites(9);CHECK(logs.size()==count);
}
'''
with tempfile.TemporaryDirectory(prefix='gpu-write-history-') as td:
 t=Path(td);(t/'check.cpp').write_text(code)
 env=dict(os.environ);env.pop('EDEN_NX2_3D_HISTORY',None)
 for release in (False,True):
  subprocess.run(['clang++-18','-std=c++20','-O1','-g','-fsanitize=address,undefined',
                  *(['-DNDEBUG'] if release else []),str(t/'check.cpp'),'-o',str(t/'check')],check=True)
  subprocess.run([str(t/'check'),'disabled' if release else 'enabled'],env=env,check=True)
  for value in ('1','0',''):
   subprocess.run([str(t/'check'),'enabled',value],env=env,check=True)
print('GPU_WRITE_HISTORY_DEBUG_RELEASE_AND_OPT_IN_PASS')
