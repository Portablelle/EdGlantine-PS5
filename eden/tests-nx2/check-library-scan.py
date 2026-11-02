"""Exercise the actual provider recursion on a payload-heavy mock VFS on dedie."""
from pathlib import Path
import importlib.util,platform,subprocess,tempfile
assert platform.system()=='Linux','Run on dedie'
r=Path(__file__).resolve().parents[1];cache=Path((r/'.local/headless-cache').read_text().strip())
spec=importlib.util.spec_from_file_location('prepare',r/'tools/prepare-library-scan.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
s=(cache/'source/src/core/file_sys/registered_cache.cpp').read_text()
def method(s):
 start=s.index('void ExternalContentProvider::ScanDirectory(');at=s.index('{',start);depth=1;end=at+1
 while depth:depth+=(s[end]=='{')-(s[end]=='}');end+=1
 return s[start:end]
prefix=r'''
#include <algorithm>
#include <cassert>
#include <cctype>
#include <cstdio>
#include <memory>
#include <set>
#include <string>
#include <vector>
namespace Common{std::string ToLower(std::string s){for(auto& c:s)c=std::tolower((unsigned char)c);return s;}}
struct File{std::string name;auto GetName()const{return name;}};
size_t file_visits=0,dir_visits=0;
struct Dir{std::string name;bool dump=false;std::vector<std::shared_ptr<File>> files;std::vector<std::shared_ptr<Dir>> dirs;
 auto GetName(){return name;}auto GetFiles(){file_visits+=files.size();return files;}auto GetSubdirectories(){++dir_visits;return dirs;}
 std::shared_ptr<File> GetFileRelative(const char* path){assert(std::string(path)=="exefs/main");return dump?std::make_shared<File>(File{"main"}):nullptr;}
};
using VirtualDir=std::shared_ptr<Dir>;
struct ExternalContentProvider{std::set<std::string> packages;void ScanDirectory(const VirtualDir&);
 void ProcessNSP(const std::shared_ptr<File>& f){packages.insert(f->name);}void ProcessXCI(const std::shared_ptr<File>& f){packages.insert(f->name);}};
'''
main=r'''
int main(){
 auto library=std::make_shared<Dir>(Dir{"roms"});auto dump=std::make_shared<Dir>(Dir{"Bananza",true});library->dirs.push_back(dump);
 for(const char* name:{"romfs","exefs"}){auto payload=std::make_shared<Dir>(Dir{name});dump->dirs.push_back(payload);
  for(int i=0;i<256;++i){auto child=std::make_shared<Dir>(Dir{std::to_string(i)});payload->dirs.push_back(child);
   for(int j=0;j<512;++j)child->files.push_back(std::make_shared<File>(File{"asset.bin"}));}}
 auto addons=std::make_shared<Dir>(Dir{"updates"});dump->dirs.push_back(addons);addons->files.push_back(std::make_shared<File>(File{"update.NSP"}));
 auto nested=std::make_shared<Dir>(Dir{"dlc"});addons->dirs.push_back(nested);nested->files.push_back(std::make_shared<File>(File{"dlc.xci"}));
 dump->files.push_back(std::make_shared<File>(File{"sibling.nsp"}));
 auto staging=std::make_shared<Dir>(Dir{".mario-kart-upload"});library->dirs.push_back(staging);staging->files.push_back(std::make_shared<File>(File{"incomplete.nsp"}));
 // A normal package folder called romfs stays searchable without exefs/main.
 auto normal=std::make_shared<Dir>(Dir{"Other game"});library->dirs.push_back(normal);
 auto romfs=std::make_shared<Dir>(Dir{"romfs"});normal->dirs.push_back(romfs);romfs->files.push_back(std::make_shared<File>(File{"normal.nsp"}));
 ExternalContentProvider provider;provider.ScanDirectory(library);
 if(OLD){assert(file_visits>262144);assert(provider.packages.count("incomplete.nsp"));puts("BASELINE visited 262144 payload assets and unpublished staging");}
 else{assert(file_visits==4);assert(dir_visits==6);assert((provider.packages==std::set<std::string>{"update.NSP","dlc.xci","sibling.nsp","normal.nsp"}));puts("PASS 262144 payload assets skipped, staging excluded, sibling/nested/case-insensitive add-ons retained, non-dump folder unchanged");}
}
'''
with tempfile.TemporaryDirectory(prefix='library-scan-') as tmp:
 p=Path(tmp)
 for old in [1,0]:
  cpp=p/('old.cpp' if old else 'fixed.cpp');exe=cpp.with_suffix('');cpp.write_text(prefix+method(s if old else m.prepare(s))+main)
  subprocess.run(['c++','-std=c++20','-O1','-g','-fsanitize=address,undefined','-DOLD='+str(old),str(cpp),'-o',str(exe)],check=True)
  subprocess.run([str(exe)],check=True)
