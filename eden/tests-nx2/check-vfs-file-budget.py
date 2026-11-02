"""Exercise the real VFS LRU methods under an actual low descriptor limit on dedie."""
from pathlib import Path
import platform,subprocess,tempfile
assert platform.system()=='Linux','Run on dedie'
r=Path(__file__).resolve().parents[1];scratch=Path((r/'.local/headless-cache').read_text().strip())
s=(scratch/'source/src/core/file_sys/vfs/vfs_real.cpp').read_text()
def method(name):
 at=s.index('RealVfsFilesystem::'+name+'(');start=s.rfind('\n',0,at)+1
 # RefreshReference has its return type on the previous line only when formatted differently.
 if name=='RefreshReference':start=s.rfind('std::unique_lock<std::mutex>',0,at)
 at=s.index('{',at);depth=1;end=at+1
 while depth:depth+=(s[end]=='{')-(s[end]=='}');end+=1
 return s[start:end]
methods='\n'.join(method(n) for n in ['RefreshReference','DropReference','EvictSingleReferenceLocked','InsertReferenceIntoListLocked','RemoveReferenceFromListLocked'])
code=r'''
#include <algorithm>
#include <cassert>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <list>
#include <memory>
#include <mutex>
#include <string>
#include <vector>
#include <sys/resource.h>
#include "host_file_pressure.h"
using std::size_t;
constexpr size_t MaxOpenFiles=OLD_POLICY?512:Eden::HostFiles::MaxCachedOpenFiles;
enum class OpenMode{Read};int ModeFlagsToFileAccessMode(OpenMode){return 0;}
namespace FS{
enum class FileType{BinaryFile};
struct IOFile{FILE* f{};explicit IOFile(FILE* p):f(p){}~IOFile(){if(f)std::fclose(f);}};
std::shared_ptr<IOFile> FileOpen(const std::string& path,int,FileType){
 FILE* f=std::fopen(path.c_str(),"rb");
 if(!f){Eden::HostFiles::ObserveOpenError(errno);return {};}
 return std::make_shared<IOFile>(f);
}
}
struct FileReference{std::shared_ptr<FS::IOFile> file;std::vector<int> blocks;};
struct RefList{
 std::list<FileReference*> entries;
 bool empty(){return entries.empty();}auto& back(){return *entries.back();}
 void push_front(FileReference& r){entries.push_front(&r);}
 auto iterator_to(FileReference& r){return std::find(entries.begin(),entries.end(),&r);}
 void erase(std::list<FileReference*>::iterator i){assert(i!=entries.end());entries.erase(i);}
};
struct RealVfsFilesystem{
 RefList open_references,closed_references;std::mutex list_lock;size_t num_open_files{};bool in_dtor=false;
 std::unique_lock<std::mutex> RefreshReference(const std::string&,OpenMode,FileReference&);
 void DropReference(std::unique_ptr<FileReference>&&);
 void EvictSingleReferenceLocked();void InsertReferenceIntoListLocked(FileReference&);void RemoveReferenceFromListLocked(FileReference&);
};
'''+methods+r'''
int main(int argc,char**argv){
 assert(argc==2);const std::filesystem::path root=argv[1];
 for(unsigned i=0;i<256;++i){std::ofstream f(root/std::to_string(i));f<<"asset-"<<i;}
 rlimit limit{};assert(getrlimit(RLIMIT_NOFILE,&limit)==0);limit.rlim_cur=96;assert(setrlimit(RLIMIT_NOFILE,&limit)==0);
 Eden::HostFiles::Reset();Eden::HostFiles::ObserveOpenError(ENOENT);Eden::HostFiles::ObserveOpenError(EACCES);assert(!Eden::HostFiles::Exhausted());
 RealVfsFilesystem fs;std::vector<std::unique_ptr<FileReference>> references;
 for(unsigned i=0;i<256;++i){auto r=std::make_unique<FileReference>();fs.InsertReferenceIntoListLocked(*r);references.push_back(std::move(r));}
 for(unsigned round=0;round<2;++round)for(unsigned j=0;j<256;++j){
  const unsigned i=round?(j*73)%256:j;
  auto lk=fs.RefreshReference((root/std::to_string(i)).string(),OpenMode::Read,*references[i]);
  if(!references[i]->file){assert(OLD_POLICY);assert(Eden::HostFiles::Exhausted());std::puts("BASELINE_EMFILE_REPRODUCED");return 1;}
  std::rewind(references[i]->file->f);char data[32]{};const auto n=std::fread(data,1,sizeof(data),references[i]->file->f);
  assert(std::string(data,n)=="asset-"+std::to_string(i));
  assert(fs.num_open_files<=MaxOpenFiles);
 }
 assert(!OLD_POLICY&&!Eden::HostFiles::Exhausted());
 for(auto& r:references)fs.DropReference(std::move(r));assert(fs.num_open_files==0);
 Eden::HostFiles::ObserveOpenError(EMFILE);assert(Eden::HostFiles::Exhausted());Eden::HostFiles::Reset();assert(!Eden::HostFiles::Exhausted());
 Eden::HostFiles::ObserveOpenError(ENFILE);assert(Eden::HostFiles::Exhausted());Eden::HostFiles::Reset();
 std::puts("PASS 512 reads/reopens, 256 assets, RLIMIT_NOFILE=96, LRU<=64, complete descriptor release and error classification");
}
'''
with tempfile.TemporaryDirectory(prefix='vfs-budget-') as tmp:
 p=Path(tmp);(p/'check.cpp').write_text(code)
 for old in [1,0]:
  exe=p/('old' if old else 'fixed');assets=p/('old-assets' if old else 'fixed-assets');assets.mkdir()
  # ASan itself needs a pipe when fopen hits EMFILE; keep the intentionally
  # exhausting baseline unsanitized and sanitize the bounded corrected path.
  sanitizers=[] if old else ['-fsanitize=address,undefined']
  subprocess.run(['c++','-std=c++20','-O1','-g',*sanitizers,'-DOLD_POLICY='+str(old),'-I'+str(r/'headless'),str(p/'check.cpp'),'-o',str(exe)],check=True)
  result=subprocess.run([str(exe),str(assets)])
  assert result.returncode==(1 if old else 0),result.returncode
