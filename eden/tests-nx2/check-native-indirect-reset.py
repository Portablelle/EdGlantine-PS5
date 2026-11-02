"""Run the production indirect-record reset helper under ASan/UBSan on dedie."""
from pathlib import Path
import platform, subprocess, tempfile, sys
assert platform.system() == 'Linux', 'Run on dedie'
r = Path(__file__).resolve().parents[1]
source = Path((r/'.local/headless-cache').read_text().strip())/'source/src'
if '--generated' in sys.argv:
 generated=source.parent.parent/'native-local/headless/vulkan_rasterizer.cpp'
 text=generated.read_text();start=text.index('// The native raw-global fallback')
 end=text.index('    std::scoped_lock lock{buffer_cache.mutex, texture_cache.mutex};',start)
 block=text[start:end]
 for token in ('NativeIndirectReset::Execute','IsWithinGPUAddressRange(address)',
               'IsWithinGPUAddressRange(address + size - 1)','gpu_memory->ReadBlock(',
               'gpu_memory->WriteBlock(', 'direct_instances == 1'):
  assert token in block,token
 assert '}, instance_count);' in text and 'draw_func();' in text
 assert 'ReadBlockUnsafe' not in block and 'WriteBlockUnsafe' not in block
 print('NATIVE_INDIRECT_RESET_GENERATED_PORT_PASS')
 raise SystemExit(0)
cpp = r'''
#include <cassert>
#include <cstring>
#include <fstream>
#include <iterator>
#include <iostream>
#include "video_core/native_indirect_reset.h"
using namespace VideoCommon::NativeIndirectReset;
struct Memory {
 std::vector<u8> cpu=std::vector<u8>(65536,0xa5), gpu=cpu;
 std::vector<u64> holes, writes;
 size_t reads=0;
 bool Mapped(u64 a,u64 n) { return a>=0x1000 && a<=cpu.size() && n<=cpu.size()-a &&
    std::none_of(holes.begin(),holes.end(),[&](u64 h){return a<=h&&h<a+n;}); }
 void Read(u64 a,void* p,u64 n) { assert(Mapped(a,n)); ++reads; std::memcpy(p,gpu.data()+a,n); }
 void Write(u64 a,const void* p,u64 n) { assert(Mapped(a,n));writes.push_back(a);
    std::memcpy(cpu.data()+a,p,n);std::memcpy(gpu.data()+a,p,n); }
 bool Run(u32 n=96,u64 cbuf=0x1000,u32 size=0x900) {return Execute(cbuf,size,n,
    [&](u64 a,u64 s){return Mapped(a,s);},[&](u64 a,void*p,u64 s){Read(a,p,s);},
    [&](u64 a,const void*p,u64 s){Write(a,p,s);});}
 void Set(u64 a,u64 v){std::memcpy(gpu.data()+a,&v,8);}
 void Setup(u32 n=96){Set(0x1110,0x2000);for(u32 i=0;i<n;++i)Set(0x2000+8*i,0x8000+32*i);}
};
int main(int argc,char**argv){
 assert(Matches(Program));
 // All code/header/map bits participate, including the no-position-output header.
 for(size_t i=0;i<Program.size();++i)for(unsigned bit=0;bit<64;++bit){
  auto x=Program;x[i]^=1ULL<<bit;assert(!Matches(x));
 }
 assert(!Matches(std::span(Program).first(Program.size()-1)));
 if(argc>1){std::ifstream f(argv[1],std::ios::binary);std::vector<char>b((std::istreambuf_iterator<char>(f)),{});
  assert(b.size()%8==0);std::vector<u64>w(b.size()/8);std::memcpy(w.data(),b.data(),b.size());assert(Matches(w));}
 Memory m;m.Setup();assert(m.Run());assert(m.reads==2&&m.writes.size()==96);
 const std::array<u32,5> expected{0,1,0,0,0};
 for(u32 i=0;i<96;++i){assert(!std::memcmp(m.cpu.data()+0x8000+32*i,expected.data(),20));
  for(unsigned j=20;j<32;++j)assert(m.cpu[0x8000+32*i+j]==0xa5);}
 // A second frame must clear a count produced by culling in the previous frame.
 for(u32 i=0;i<96;++i)m.gpu[0x8000+32*i]=77;
 assert(m.Run());for(u32 i=0;i<96;++i)assert(m.cpu[0x8000+32*i]==0);
 // Last invalid pointer: fail before *any* record is touched.
 for(u64 invalid:{0ULL,0xfffffffffffffff8ULL,0xfff8ULL,0x8001ULL,0x2000ULL,0x1110ULL}){
  Memory x;x.Setup();x.Set(0x2000+95*8,invalid);auto before=x.cpu;
  assert(!x.Run()&&x.writes.empty()&&x.cpu==before);
 }
 Memory sparse;sparse.Setup();sparse.holes={0x8000+95*32+19};assert(!sparse.Run()&&sparse.writes.empty());
 Memory partial;partial.Setup();partial.Set(0x2000+8,0x8004);assert(!partial.Run()&&partial.writes.empty());
 Memory duplicate;duplicate.Setup();duplicate.Set(0x2000+8,0x8000);assert(duplicate.Run());
 for(u32 n:{0U,1025U,0xffffffffU}){Memory x;x.Setup();assert(!x.Run(n)&&x.writes.empty());}
 Memory cap;cap.Setup(1024);assert(cap.Run(1024)&&cap.writes.size()==1024);
 Memory shortcb;shortcb.Setup();assert(!shortcb.Run(96,0x1000,0x117)&&shortcb.reads==0);
 Memory cbwrap;cbwrap.Setup();assert(!cbwrap.Run(96,~u64{0}-8)&&cbwrap.reads==0);
 Memory emptytable;emptytable.Setup();emptytable.Set(0x1110,0);assert(!emptytable.Run()&&emptytable.writes.empty());
 // Pointer table in GPU state differs from stale CPU bytes: coherent callbacks win.
 Memory fresh;fresh.Setup();fresh.Set(0x2000,0xc000);assert(fresh.Run());assert(fresh.writes[0]==0xc000);
 // Preserve full-width guest pointers, including records crossing a 4 GiB boundary.
 unsigned high_writes=0;
 assert(Execute(0x100001000ULL,0x900,1,
  [](u64 a,u64 n){return a>0xffffffffULL && n<0x1000;},
  [](u64 a,void*p,u64 n){u64 v=a==0x100001110ULL?0x200002000ULL:0x2fffffff0ULL;
   assert(n==8);std::memcpy(p,&v,8);},
  [&](u64 a,const void*p,u64 n){assert(a==0x2fffffff0ULL&&n==20);
   assert(!std::memcmp(p,expected.data(),20));++high_writes;}));
 assert(high_writes==1);
 std::cout<<"NATIVE_INDIRECT_RESET_ASAN_UBSAN_PASS\n";
}
'''
with tempfile.TemporaryDirectory(prefix='native-indirect-reset-') as td:
 t=Path(td);(t/'check.cpp').write_text(cpp)
 subprocess.run(['c++','-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer','-I'+str(source),str(t/'check.cpp'),'-o',str(t/'check')],check=True)
 subprocess.run([str(t/'check'),*sys.argv[1:]],check=True)
# The real integration must preserve coherent I/O, normal draw/query handling and fail closed.
s=(source/'video_core/renderer_vulkan/vk_rasterizer.cpp').read_text()
a=s.index('// The native raw-global fallback');b=s.index('    std::scoped_lock lock{buffer_cache.mutex, texture_cache.mutex};',a)
part=s[a:b]
assert 'ReadBlockUnsafe' not in part and 'WriteBlockUnsafe' not in part
for guard in ('direct_instances == 1','vertex_buffer.first == 0','!is_indexed','!reset_regs.transform_feedback_enabled','unconditional','IsShaderConfigEnabled(0)','IsShaderConfigEnabled(2)','IsShaderConfigEnabled(3)','IsShaderConfigEnabled(4)'):
 assert guard in part,guard
assert '}, instance_count);' in s
print('NATIVE_INDIRECT_RESET_INTEGRATION_PASS')
