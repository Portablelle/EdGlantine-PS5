"""dedie only: production constant-pool, viewport and VP9 snapshot regressions."""
from pathlib import Path
import platform
import subprocess

assert platform.system() == 'Linux', 'Run on dedie only'
root = Path(__file__).resolve().parents[1]
scratch = Path((root / '.local/headless-cache').read_text().strip())
source = scratch / 'source/src'
out = root / 'build/nx2-tests/nightly-backports'
out.mkdir(parents=True, exist_ok=True)


def function(text, signature):
    start = text.index(signature)
    end = text.index('{', start) + 1
    depth = 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end] + '\n'


def run(name, code, includes=()):
    path = out / (name + '.cpp')
    path.write_text(code)
    result = subprocess.run(['c++', '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
                    '-fno-omit-frame-pointer', *['-I' + str(i) for i in includes],
                    str(path), '-o', str(out / name)], stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True)
    if result.returncode:
        print(result.stdout)
        raise SystemExit(result.returncode)
    subprocess.run([str(out / name)], check=True)


unadapted_pool = (source / 'dynarmic/src/dynarmic/backend/x64/constant_pool.cpp').read_text()
derive = out / 'derive-pool.cmake'
derive.write_text(f'''set(PROJECT_SOURCE_DIR "{scratch / 'source'}")
set(PORT_BUILD_DIR "{out / 'derived'}")
function(write_derived path content)
    file(WRITE "${{path}}" "${{content}}")
endfunction()
include("{root / 'headless/jit-constant-pool.cmake'}")
''')
subprocess.run(['cmake', '-P', str(derive)], check=True)
pool = (out / 'derived/constant_pool.cpp').read_text()
# Source drift must fail configuration rather than leave a direct RX store.
store = '    if (inserted) pool[it->second] = u128{lower, upper};'
for case, content in [('unknown', unadapted_pool.replace(store, '    /* changed store */')),
                      ('duplicate', unadapted_pool.replace(store, store + '\n' + store))]:
    fixture = out / ('source-' + case)
    path = fixture / 'src/dynarmic/src/dynarmic/backend/x64/constant_pool.cpp'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    script = out / (case + '.cmake')
    script.write_text(derive.read_text().replace(str(scratch / 'source'), str(fixture)))
    result = subprocess.run(['cmake', '-P', str(script)], capture_output=True, text=True)
    assert result.returncode != 0 and 'constant-pool store' in result.stderr
pool_header = (source / 'dynarmic/src/dynarmic/backend/x64/constant_pool.h').read_text()
pool_class = function(pool_header, 'class ConstantPool final {') + ';\n'
code = r'''
#include <array>
#include <bit>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <csignal>
#include <cstring>
#include <memory>
#include <span>
#include <stdexcept>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>
#include <boost/functional/hash.hpp>
#include <sys/mman.h>
#include <sys/prctl.h>
#include <sys/wait.h>
#include <unistd.h>
using u32=uint32_t;using u64=uint64_t;using u128=std::array<u64,2>;
#define ASSERT(x) ((void)(x)) // Soft assertion may return; exhaustion must still throw.
namespace Common{template<class K,class V,class H>using unordered_map=std::unordered_map<K,V,H>;}
namespace Xbyak{using Address=const u128*;struct AddressFrame{
 Address operator[](Address p)const{return p;}};}
struct RIP{};const u128* operator+(RIP,const u128* p){return p;}
struct BlockOfCode{size_t page=size_t(sysconf(_SC_PAGESIZE));int fd=memfd_create("jit-pool",MFD_CLOEXEC);
 unsigned char* rx;unsigned char* rw;RIP rip;
 BlockOfCode(){assert(fd>=0&&ftruncate(fd,page)==0);
  rx=(unsigned char*)mmap(nullptr,page,PROT_READ|PROT_EXEC,MAP_SHARED,fd,0);
  rw=(unsigned char*)mmap(nullptr,page,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);
  assert(rx!=MAP_FAILED&&rw!=MAP_FAILED&&rx!=rw);}
 ~BlockOfCode(){munmap(rx,page);munmap(rw,page);close(fd);}
 unsigned char* writableAddress(const void* p){return rw+((const unsigned char*)p-rx);}
 void EnsureMemoryCommitted(size_t){}void int3(){}void align(size_t){}
 void* AllocateFromCodeSpace(size_t n){assert(n<=page);return rx;}};
'''+pool_class+function(pool, 'ConstantPool::ConstantPool(')+function(pool, 'Xbyak::Address ConstantPool::GetConstant(')
code += pool_class.replace('ConstantPool', 'UnadaptedPool')
code += function(unadapted_pool, 'ConstantPool::ConstantPool(').replace('ConstantPool', 'UnadaptedPool')
code += function(unadapted_pool, 'Xbyak::Address ConstantPool::GetConstant(').replace('ConstantPool', 'UnadaptedPool')
code += r'''
int main(){
 prctl(PR_SET_DUMPABLE,0);
 // Reproduce the exact installed failure: the unadapted store writes RX.
 auto child=fork();assert(child>=0);
 if(!child){std::signal(SIGSEGV,SIG_DFL);BlockOfCode c;UnadaptedPool p(c,128);
  p.GetConstant(c,Xbyak::AddressFrame{},0x7fc00000);_exit(0);}
 int status;assert(waitpid(child,&status,0)==child);
 assert(WIFSIGNALED(status)&&WTERMSIG(status)==SIGSEGV);
 BlockOfCode code;ConstantPool pool(code,8*sizeof(u128));Xbyak::AddressFrame frame;
 std::vector<const u128*> addresses;
 for(u64 i=0;i<8;++i){auto p=pool.GetConstant(code,frame,i,i*17);addresses.push_back(p);
  assert((*p==u128{i,i*17}));assert(pool.GetConstant(code,frame,i,i*17)==p);}
 assert(addresses[0]==reinterpret_cast<const u128*>(code.rx));
 assert(std::memcmp(code.rx,code.rw,8*sizeof(u128))==0);
 // The fix must not weaken RX protections to make the bad store pass.
 child=fork();assert(child>=0);
 if(!child){std::signal(SIGSEGV,SIG_DFL);*(volatile unsigned char*)code.rx=0;_exit(0);}
 assert(waitpid(child,&status,0)==child&&WIFSIGNALED(status)&&WTERMSIG(status)==SIGSEGV);
 // A full pool still accepts duplicates and rejects new entries before a store.
 for(u64 i=0;i<8;++i)assert(pool.GetConstant(code,frame,i,i*17)==addresses[i]);
 for(int attempt=0;attempt<2;++attempt){bool rejected=false;
  try{pool.GetConstant(code,frame,99,100);}catch(const std::length_error&){rejected=true;}assert(rejected);}
 for(u64 i=0;i<8;++i)assert((*addresses[i]==u128{i,i*17}));
 BlockOfCode empty_code;ConstantPool empty(empty_code,0);bool rejected=false;
 try{empty.GetConstant(empty_code,frame,1);}catch(const std::length_error&){rejected=true;}assert(rejected);
 // These distinct constants all collide under the original xor/rotate hash.
 std::unordered_set<size_t> old_hashes,new_hashes;boost::hash<std::pair<u64,u64>> hash;
 for(u64 i=0;i<4096;++i){u64 lo=std::rotl(i,1),hi=i;
  old_hashes.insert(lo^std::rotl(hi,1));new_hashes.insert(hash({lo,hi}));}
 assert(old_hashes.size()==1&&new_hashes.size()>4000);
 printf("Constant pool: RX-store crash reproduced; generated RW alias, RX addresses/protection, capacity and %zu/4096 hashes: PASS\n",new_hashes.size());
}
'''
boost_dirs = list((scratch / 'source/.cache/cpm/boost').glob('*/libs/*/include'))
assert boost_dirs, 'Pinned Boost headers missing'
run('constant-pool', code, boost_dirs)

raster = (source / 'video_core/renderer_vulkan/vk_rasterizer.cpp').read_text()
viewport = function(raster, 'VkViewport GetViewportState(')
code = r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <cmath>
#include <cstdio>
using f32=float;
struct VkViewport{float x,y,width,height,minDepth,maxDepth;};
struct Device{bool swizzle=false,unrestricted=false;
 bool IsNvViewportSwizzleSupported()const{return swizzle;}
 bool IsExtDepthRangeUnrestrictedSupported()const{return unrestricted;}};
struct Maxwell{
 enum class ViewportSwizzle{PositiveY,NegativeY};enum class DepthMode{MinusOneToOne,ZeroToOne};
 struct WindowOrigin{enum class Mode{UpperLeft,LowerLeft};Mode mode=Mode::UpperLeft;}window_origin;
 struct Transform{float translate_x=100,translate_y=50,translate_z=.5f,scale_x=100,scale_y=50,scale_z=.5f;
 struct{ViewportSwizzle y=ViewportSwizzle::PositiveY;}swizzle;};
 std::array<Transform,1> viewport_transform;struct{int height=100;}surface_clip;
 DepthMode depth_mode=DepthMode::MinusOneToOne;
};
'''+viewport+r'''
int main(){
 Device d;Maxwell r;auto& t=r.viewport_transform[0];
 auto v=GetViewportState(d,r,0,1);assert(v.y==0&&v.height==100&&v.minDepth==0&&v.maxDepth==1);
 r.window_origin.mode=Maxwell::WindowOrigin::Mode::LowerLeft;
 v=GetViewportState(d,r,0,1);assert(v.y==100&&v.height==-100);
 t.scale_y=-50;v=GetViewportState(d,r,0,1);assert(v.y==200&&v.height==100); // Preserve the existing transform.
 v=GetViewportState(d,r,0,.5f);assert(v.y==100&&v.height==50);
 v=GetViewportState(d,r,0,2);assert(v.y==400&&v.height==200);
 t.swizzle.y=Maxwell::ViewportSwizzle::NegativeY;
 v=GetViewportState(d,r,0,1);assert(v.y==300&&v.height==-100);
 d.swizzle=true;v=GetViewportState(d,r,0,1);assert(v.y==200&&v.height==100);
 t.translate_y=-25;t.scale_y=-25;v=GetViewportState(d,r,0,1);assert(v.y==100&&v.height==50);
 t.scale_z=2;v=GetViewportState(d,r,0,1);assert(v.minDepth==0&&v.maxDepth==1);
 d.unrestricted=true;v=GetViewportState(d,r,0,1);assert(v.minDepth==-1.5f&&v.maxDepth==2.5f);
 // The proposed upstream branch jumps from y=199 to y=0 here. Do not
 // import it without a platform-specific derivation and rendering evidence.
 t.scale_y=-25;t.translate_y=74;auto before=GetViewportState(d,r,0,1);
 t.translate_y=75;auto after=GetViewportState(d,r,0,1);
 assert(before.y==199&&after.y==200&&after.y-before.y==1);
 puts("Viewport: baseline boundary continuity; discontinuous upstream backport excluded: PASS");
}
'''
run('viewport', code)

buffer_header = (source / 'video_core/renderer_vulkan/vk_buffer_cache.h').read_text()
binding = function(buffer_header, '    void BindTextureBuffer(')
binding = binding.replace('void BindTextureBuffer(', 'void Runtime::BindTextureBuffer(', 1)
code = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
using u32=uint32_t;using VkDeviceAddress=uint64_t;using VkFormat=int;
constexpr int VK_NULL_HANDLE=0,VK_FORMAT_UNDEFINED=0;
namespace VideoCore::Surface{enum class PixelFormat{Valid,Invalid=255};}
int view_calls=0,format_calls=0;
int TexelBufferFormat(VideoCore::Surface::PixelFormat f){++format_calls;
 assert(f==VideoCore::Surface::PixelFormat::Valid);return 17;}
struct Buffer{uint64_t address=4096;
 uint64_t DeviceAddress()const{return address;}
 int View(u32,u32,VideoCore::Surface::PixelFormat){++view_calls;return address?42:0;}};
struct Runtime{
 struct Queue{bool descriptor_buffer=false;int view=-1,format=-1;uint64_t address=1;
 bool UsesDescriptorBuffer()const{return descriptor_buffer;}
 void AddTexelBuffer(int v){view=v;}
 void AddTexelBuffer(int v,uint64_t a,u32,u32,int f){view=v;address=a;format=f;}
 }guest_descriptor_queue;
 void BindTextureBuffer(Buffer&,u32,u32,VideoCore::Surface::PixelFormat);
};
'''+binding+r'''
int main(){using F=VideoCore::Surface::PixelFormat;Runtime r;Buffer b;
 r.BindTextureBuffer(b,0,32,F::Valid);assert(view_calls==1&&format_calls==0&&r.guest_descriptor_queue.view==42);
 r.guest_descriptor_queue.descriptor_buffer=true;
 r.BindTextureBuffer(b,0,32,F::Valid);assert(view_calls==1&&format_calls==1);
 assert(r.guest_descriptor_queue.view==0&&r.guest_descriptor_queue.address==4096&&r.guest_descriptor_queue.format==17);
 b.address=0;r.BindTextureBuffer(b,0,0,F::Invalid);assert(view_calls==1&&format_calls==1);
 assert(r.guest_descriptor_queue.address==0&&r.guest_descriptor_queue.format==VK_FORMAT_UNDEFINED);
 r.guest_descriptor_queue.descriptor_buffer=false;r.BindTextureBuffer(b,0,0,F::Invalid);
 assert(view_calls==2&&format_calls==1&&r.guest_descriptor_queue.view==0);
 puts("Texel buffers: descriptor/set paths, no redundant views/format conversion, null format 255: PASS");
}
'''
run('texel-buffer', code)

# Record the actual VP9 segmentation writer's output, then overwrite guest
# picture/probability memory with a future frame before the current one encodes.
vp9 = (source / 'video_core/host1x/codecs/vp9.cpp').read_text()
code = r'''
#include <array>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <vector>
using u8=uint8_t;using u32=uint32_t;using u64=uint64_t;using s32=int32_t;
struct Segmentation{u32 enabled=0,update_map=0,temporal_update=0,abs_delta=0;
 std::array<std::array<u8,4>,8> feature_enabled{};std::array<std::array<s32,4>,8> feature_data{};
 bool operator==(const Segmentation&)const=default;};
struct EntropyProbs{std::array<u8,7> mb_segment_tree_probs{};std::array<u8,3> segment_pred_probs{};
 void Convert(int& dst)const{dst=mb_segment_tree_probs[0];}};
struct Vp9PictureInfo{Segmentation segmentation;std::array<u8,7> seg_tree_probs{};
 std::array<u8,3> seg_pred_probs{};int entropy{};std::array<u64,4> frame_offsets{};};
struct PictureInfo{Segmentation segmentation;Vp9PictureInfo Convert()const{return {.segmentation=segmentation};}};
struct Offset{u64 value=0;u64 Address()const{return value;}};
struct VpxBitStreamWriter{std::vector<int> bits;
 void WriteBit(bool b){bits.push_back(b);}void WriteU(u32 v,int n){for(int i=n-1;i>=0;--i)WriteBit((v>>i)&1);}
 void WriteS(s32 v,int n){WriteU(v<0?-v:v,n);WriteBit(v<0);}};
struct VP9{
 struct Memory{PictureInfo picture;EntropyProbs probs;int reads=0;
 void ReadBlock(u64,PictureInfo* dst,size_t){*dst=picture;++reads;}
 void ReadBlock(u64,EntropyProbs* dst,size_t){*dst=probs;++reads;}};
 struct{Memory gmmu_manager;}host1x;
 struct{Offset picture_info_offset,vp9_prob_tab_buffer_offset;std::array<Offset,4> surface_luma_offsets;}regs;
 Vp9PictureInfo current_frame_info;PictureInfo current_picture_info;Segmentation last_segmentation;
 void WriteSegmentation(VpxBitStreamWriter&);Vp9PictureInfo GetVp9PictureInfo();
};
'''+function(vp9, 'void VP9::WriteSegmentation(')+function(vp9, 'Vp9PictureInfo VP9::GetVp9PictureInfo()')+r'''
int main(){
 for(int mode=0;mode<8;++mode){VP9 a;auto& memory=a.host1x.gmmu_manager;
  memory.picture.segmentation.enabled=1;memory.picture.segmentation.update_map=mode&1;
  memory.picture.segmentation.temporal_update=(mode>>1)&1;memory.picture.segmentation.abs_delta=(mode>>2)&1;
  for(int i=0;i<8;++i)for(int j=0;j<4;++j){memory.picture.segmentation.feature_enabled[i][j]=1;
   memory.picture.segmentation.feature_data[i][j]=j==0?-17:j==1?11:2;}
  memory.probs.mb_segment_tree_probs={1,2,255,4,5,6,7};memory.probs.segment_pred_probs={9,255,11};
  a.current_frame_info=a.GetVp9PictureInfo();assert(memory.reads==2);
  assert(a.current_frame_info.entropy==1&&a.current_frame_info.seg_tree_probs[2]==255);
  VP9 reference=a;VpxBitStreamWriter expected,actual;reference.WriteSegmentation(expected);
  memory.picture={};memory.probs={};a.current_picture_info={};
  a.WriteSegmentation(actual);assert(expected.bits==actual.bits);assert(memory.reads==2);
  VpxBitStreamWriter repeated;a.WriteSegmentation(repeated);assert(repeated.bits.back()==0);
 }
 VP9 disabled;VpxBitStreamWriter writer;disabled.WriteSegmentation(writer);assert(writer.bits==std::vector<int>{0});
 puts("VP9: delayed frame metadata/probability snapshot, all segmentation flags, reuse and disabled path: PASS");
}
'''
run('vp9-snapshot', code)
