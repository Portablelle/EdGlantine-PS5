"""Run the actual pinned VFS read/LRU and descriptor table on dedie with sanitizers."""
from pathlib import Path
import importlib.util, platform, subprocess, tempfile
assert platform.system()=='Linux', 'Run on dedie'
r=Path(__file__).resolve().parents[1]
cache=Path((r/'.local/headless-cache').read_text().strip())
src=cache/'source'
spec=importlib.util.spec_from_file_location('adapter',r/'tools/prepare-host-memory.py')
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
original=(src/'src/core/file_sys/vfs/vfs_real.cpp').read_text()
def method(s,cls,name):
 at=s.index(cls+'::'+name+'(');start=s.rfind('\n',0,at)+1
 if name=='RefreshReference':start=s.rfind('std::unique_lock<std::mutex>',0,at)
 pos=s.index('{',at);end=pos+1;depth=1
 while depth:depth+=(s[end]=='{')-(s[end]=='}');end+=1
 return s[start:end]
prefix=(r/'tests-nx2/check-vfs-file-budget.py').read_text().split("code=r'''",1)[1].split("'''+methods",1)[0]
prefix=prefix.replace('#include <vector>', '#include <vector>\n#include <span>\n#include <optional>\n#include <cstring>\n#include <unistd.h>\n#include <sys/stat.h>\n#include "host_memory_budget.h"\nnamespace ReadCacheMemory=FileSys::ReadCacheMemory;\nusing u8=unsigned char; using u64=unsigned long long; using s64=long long;')
prefix=prefix.replace('enum class OpenMode{Read};','enum class OpenMode{Read,Write};\nbool True(bool b){return b;} bool operator&(OpenMode a,OpenMode b){return a==b;}')
prefix=prefix.replace('FILE* f{};explicit IOFile', '''FILE* f{};
 size_t ReadAt(void* data,size_t bytes,s64 offset){auto n=pread(fileno(f),data,bytes,offset);return n<0?0:size_t(n);}
 bool Seek(s64 offset){return fseeko(f,offset,SEEK_SET)==0;}
 size_t ReadSpan(std::span<u8> data){return fread(data.data(),1,data.size(),f);}
 size_t GetSize(){struct stat st{};assert(fstat(fileno(f),&st)==0);return st.st_size;}
 explicit IOFile''')
prefix=prefix.replace('struct FileReference{std::shared_ptr<FS::IOFile> file;std::vector<int> blocks;};', '''struct FileReference{std::shared_ptr<FS::IOFile> file;
 struct Block{u64 index;u64 used;std::conditional_t<OLD_POLICY,std::vector<u8>,Eden::HostMemory::ReadBytes> data;};std::vector<Block> blocks;u64 block_clock{};};''')
common=r'''
struct RealVfsFile {
 RealVfsFilesystem& base; std::unique_ptr<FileReference> reference=std::make_unique<FileReference>();
 std::string path; OpenMode perms=OpenMode::Read; std::optional<u64> size;
 RealVfsFile(RealVfsFilesystem& fs,std::string p):base(fs),path(std::move(p)){base.InsertReferenceIntoListLocked(*reference);}
 ~RealVfsFile(){base.DropReference(std::move(reference));}
 size_t Read(u8*,size_t,size_t)const;
};
constexpr size_t ReadBlockSize=1024*1024,ReadBlocksPerFile=8;
'''
main=r'''
int main(int argc,char**argv){
 assert(argc==2);std::filesystem::path root=argv[1];
 RealVfsFilesystem fs;std::vector<std::unique_ptr<RealVfsFile>> files;
 for(unsigned i=0;i<256;++i){auto path=root/std::to_string(i);{std::ofstream f(path);f<<"asset-"<<i;}
  files.push_back(std::make_unique<RealVfsFile>(fs,path.string()));char out[32]{};
  auto n=files.back()->Read(reinterpret_cast<u8*>(out),sizeof(out),0);assert(std::string(out,n)=="asset-"+std::to_string(i));}
 size_t retained=0;for(auto& f:files)for(auto& b:f->reference->blocks)retained+=b.data.capacity();
 if(OLD_POLICY){assert(retained==256*ReadBlockSize);printf("BASELINE tiny assets retain %zu bytes (256 files)\n",retained);}
 else{assert(retained<1024);assert(Eden::HostMemory::read_live==retained);}
 for(unsigned i=0;i<256;++i){char out[32]{};auto n=files[i]->Read(reinterpret_cast<u8*>(out),sizeof(out),0);
  assert(std::string(out,n)=="asset-"+std::to_string(i));assert(files[i]->Read(reinterpret_cast<u8*>(out),3,100)==0);}
 files.clear();assert(Eden::HostMemory::read_live==0);
 if(OLD_POLICY)return 0;
 std::vector<u8> content(3*ReadBlockSize+17);for(size_t i=0;i<content.size();++i)content[i]=u8(i*17+i/991);
 auto big=root/"big";{std::ofstream f(big,std::ios::binary);f.write(reinterpret_cast<char*>(content.data()),content.size());}
 {
 RealVfsFile f(fs,big.string());std::vector<u8> out(ReadBlockSize/2);
 for(size_t offset:{size_t(0),ReadBlockSize-97,2*ReadBlockSize-31,3*ReadBlockSize,size_t(0)}){
  auto n=f.Read(out.data(),out.size(),offset);assert(n==std::min(out.size(),content.size()-offset));
  assert(std::equal(out.begin(),out.begin()+n,content.begin()+offset));}
 }
 assert(Eden::HostMemory::read_live==0);
 // Force global budget saturation: fallback must still return correct bytes,
 // then allow caching again after reclamation; no phantom entry or stale index.
 std::vector<Eden::HostMemory::ReadBytes> held(64);
 for(auto& b:held)assert(Eden::HostMemory::Prepare(b,ReadBlockSize));
 assert(Eden::HostMemory::read_live==Eden::HostMemory::ReadCacheLimit);
 {RealVfsFile f(fs,big.string());u8 out[99];
 for(int i=0;i<2;++i){assert(f.Read(out,sizeof(out),17)==sizeof(out));assert(std::equal(out,out+sizeof(out),content.begin()+17));}
 struct Block{Eden::HostMemory::ReadBytes data;};std::vector<Block> release;
 for(auto& b:held)release.push_back({std::move(b)});Eden::HostMemory::Release(release);
 assert(f.Read(out,sizeof(out),31)==sizeof(out));assert(std::equal(out,out+sizeof(out),content.begin()+31));}
 assert(Eden::HostMemory::read_live==0);assert(Eden::HostMemory::read_peak<=Eden::HostMemory::ReadCacheLimit);
 {Eden::HostMemory::ReadBytes a,b;assert(Eden::HostMemory::Prepare(a,4096));assert(Eden::HostMemory::Prepare(b,8192));
  auto c=std::move(a);assert(Eden::HostMemory::read_live==12288);b=std::move(c);assert(Eden::HostMemory::read_live==4096);
  Eden::HostMemory::ReadBytes d;d.swap(b);assert(Eden::HostMemory::read_live==4096);
  try {Eden::HostMemory::ReadBytes temporary;assert(Eden::HostMemory::Prepare(temporary,2048));throw 7;}catch(int){}
  assert(Eden::HostMemory::read_live==4096);
 }assert(Eden::HostMemory::read_live==0);

 printf("PASS VFS small files, reopen, EOF, cross-block reads, global budget fallback and reclamation\n");
}
'''
with tempfile.TemporaryDirectory(prefix='host-memory-') as tmp:
 p=Path(tmp)
 for old in [0]:
  s=original
  methods='\n'.join(method(s,'RealVfsFilesystem',n) for n in ['RefreshReference','DropReference','EvictSingleReferenceLocked','InsertReferenceIntoListLocked','RemoveReferenceFromListLocked'])
  text=prefix+methods+common+method(s,'RealVfsFile','Read')+main
  path=p/('old.cpp' if old else 'fixed.cpp');path.write_text(text);exe=path.with_suffix('');assets=p/(path.stem+"-assets");assets.mkdir()
  subprocess.run(['c++','-std=c++20','-O1','-g','-fsanitize=address,undefined','-DOLD_POLICY='+str(old),'-I'+str(r/'headless'),'-I'+str(src/'src'),str(path),'-o',str(exe)],check=True)
  subprocess.run([str(exe),str(assets)],check=True)
 # Compile the actual derived DescriptorTable with a controlled GPU-memory shim.
 header=a.adapt_descriptors((src/'src/video_core/texture_cache/descriptor_table.h').read_text())
 for line in header.splitlines():
  if line.startswith('#include "') and 'descriptor_memory' not in line:header=header.replace(line,'')
 fixture='''#include <cassert>\n#include <cstdint>\n#include <utility>\n#include <cstring>\n#include <memory>\nusing GPUVAddr=uint64_t;using u32=uint32_t;using u64=uint64_t;\n#define DEBUG_ASSERT assert\nnamespace Common{template<class A,class B> auto DivCeil(A a,B b){return (a+b-1)/b;}}\nnamespace Tegra{struct MemoryManager{void ReadBlockUnsafe(GPUVAddr addr,void* out,size_t n)const{std::memset(out,int(addr%251),n);}};}\n'''
 test=r'''
struct Entry{unsigned char bytes[32];bool operator==(const Entry&)const=default;};
int main(){Tegra::MemoryManager memory;
 {VideoCommon::DescriptorTable<Entry> t;size_t maximum=64;
 for(u32 limit:{0U,63U,64U,511U,0x80ffU,0x80000U,31U}){
  assert(t.Synchronize(0x1000,limit));auto a=t.Read(memory,limit);assert(a.second);assert(!t.Read(memory,limit).second);
  t.Invalidate();assert(t.Read(memory,limit).second);assert(t.descriptors.size()>=size_t(limit)+1);
  maximum=std::max(maximum,size_t(limit)+1);
  assert(t.descriptors.size()<=2*maximum);
  assert(t.bound_ids.size()==t.descriptors.size());
  t.bound_ids[limit]=limit+17;assert(!t.Read(memory,limit).second&&t.bound_ids[limit]==limit+17);
  const auto bits=t.read_descriptors;t.Invalidate();t.Invalidate();assert(t.read_descriptors==bits);
  assert(t.Read(memory,limit).second);t.bound_ids[limit]=limit+19;
  assert(!t.Read(memory,limit).second&&t.bound_ids[limit]==limit+19);
  const auto bytes=t.descriptors.capacity()*sizeof(Entry)+t.bound_ids.capacity()*sizeof(u32)+t.read_descriptors.capacity()*sizeof(u64);
  assert(Eden::HostMemory::descriptor_live==bytes);
 }
 assert(Eden::HostMemory::descriptor_live>0);
 auto moved=std::move(t);assert(!moved.Read(memory,31).second);
 }assert(Eden::HostMemory::descriptor_live==0);
 puts("PASS descriptor inclusive limits, high TIC index, shrink/regrowth, invalidation, move and memory accounting");}
'''
 cpp=p/'descriptors.cpp';cpp.write_text(fixture+header+test)
 subprocess.run(['c++','-std=c++20','-O1','-g','-fsanitize=address,undefined','-I'+str(r/'headless'),'-I'+str(src/'src'),str(cpp),'-o',str(p/'descriptors')],check=True)
 subprocess.run([str(p/'descriptors')],check=True)
