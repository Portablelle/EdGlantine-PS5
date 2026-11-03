"""Targeted controller-library discovery/path/NPDM checks; dedicated host only."""
from pathlib import Path
import platform,subprocess
assert platform.system()=='Linux','Run on dedie'
r=Path(__file__).resolve().parents[1];out=r/'build/dump-library-check';out.mkdir(parents=True,exist_ok=True)
source=Path((r/'.local/headless-cache').read_text().strip())/'source/src'
def function(text,signature):
 start=text.index(signature);brace=text.index('{',start);end=brace+1;depth=1
 while depth:
  depth+=(text[end]=='{')-(text[end]=='}');end+=1
 return text[start:end]+'\n'
ui=r/'headless/prosperoeden/pe/ui'

metadata=(source/'core/file_sys/program_metadata.cpp').read_text()
loader=(source/'core/loader/loader.h').read_text()
fixtures=(source/'tests/core/program_metadata.cpp').read_text()
# Compile the canonical ProgramMetadata header and Load body, using only a
# bounded in-memory file shim for its reads. No second NPDM implementation.
canonical=r'''
#include <memory>
#include <cstring>
#include <fstream>
#include <iterator>
#include "core/file_sys/program_metadata.h"
namespace Loader {
'''+function(loader,'enum class FileType')+';\n'+function(loader,'enum class ResultStatus')+';\n'+r'''
struct AppLoader_NSO{static FileType IdentifyType(const FileSys::VirtualFile&);};
}
namespace FileSys {
struct VfsFile{std::vector<u8> bytes;
 size_t GetSize()const{return bytes.size();}
 size_t ReadBytes(void* out,size_t n,size_t at=0)const{if(at>bytes.size())return 0;n=std::min(n,bytes.size()-at);if(n)std::memcpy(out,bytes.data()+at,n);return n;}
 template<class T>size_t ReadObject(T* out,size_t at=0)const{return ReadBytes(out,sizeof(T),at);}
};
enum class OpenMode{Read};
struct RealVfsFilesystem{VirtualFile OpenFile(const std::string& path,OpenMode){std::ifstream in(path,std::ios::binary);if(!in)return {};auto file=std::make_shared<VfsFile>();file->bytes.assign(std::istreambuf_iterator<char>(in),{});return file;}};
ProgramMetadata::ProgramMetadata()=default;
ProgramMetadata::~ProgramMetadata()=default;
'''+function(metadata,'Loader::ResultStatus ProgramMetadata::Load(')+function(metadata,'u64 ProgramMetadata::GetTitleID(')+'}\n'+function((source/'core/loader/nso.cpp').read_text(),'FileType AppLoader_NSO::IdentifyType(').replace('FileType AppLoader_NSO::','Loader::FileType Loader::AppLoader_NSO::')
bridge=(r/'headless/metadata_bridge.cpp').read_text()
# Keep the harness runnable against main too: the mixed-case Ready assertion must fail there.
romfs_helper=function(bridge,'std::filesystem::path FindLooseRomFSDirectory(') if 'std::filesystem::path FindLooseRomFSDirectory(' in bridge else ''
canonical+='\n'+romfs_helper+function(bridge,'bool LoadDumpMetadata(')+'namespace Eden::DumpMetadata {\n'+function(bridge,'std::uint64_t ProgramId(')+function(bridge,'bool Ready(')+'}\n'
preference_check=r'''
 fs::create_directory(base/"RomFS");
 assert(FindLooseRomFSDirectory(base)==base/"romfs");
 fs::remove(base/"RomFS");
''' if romfs_helper else ''
put=fixtures[fixtures.index('template <typename T>'):fixtures.index('std::vector<u8> MakeMetadata(')]
fixture=put+function(fixtures,'std::vector<u8> MakeMetadata(').replace('MakeMetadata(bool extended)','npdm(bool extended=true)').replace('0x0100123456780000','0x0400a3a01ee4c000ULL')

launcher_check=r'''
#include <future>
struct Game { bool standalone=false; };
'''+function((ui/'services.hpp').read_text(),'inline bool GameReady(')+r'''
struct Launcher {
 struct { bool setup_ready=false; } home_;
 struct { std::vector<int> games(){return {1,2};} } services_;
 std::future<std::vector<int>> scan_;
 void start_scan();
};
'''+function((ui/'library.cpp').read_text(),'void Launcher::start_scan()')+r'''
void check_launcher(){
 Launcher launcher;launcher.start_scan();assert(launcher.scan_.valid());assert(launcher.scan_.get().size()==2);
 Game container;assert(!GameReady(false,container));assert(GameReady(true,container));
 Game dump;dump.standalone=true;assert(GameReady(false,dump));assert(GameReady(true,dump));
}
'''
code=r'''
#include "dump_paths.h"
#include "dump_metadata.h"
#include <algorithm>
#include <cassert>
#include <cctype>
#include <set>
#include <string>
#include <vector>
namespace fs=std::filesystem;
namespace Eden {
inline std::string test_root;
inline std::string AssetsPath(const char* name){return test_root+"/"+name;}
'''+function((r/'headless/settings_store.h').read_text(),'inline bool ValidRomPath(')+r'''
}
std::string JoinPath(const std::string& a,const std::string& b){return a+"/"+b;}
std::vector<std::string> ListEntries(const std::string& root,bool directories,bool& ok){
 std::vector<std::string> result;std::error_code ec;
 for(const auto& entry:fs::directory_iterator(root,ec))
  if(directories?entry.is_directory():entry.is_regular_file())result.push_back(entry.path().filename().string());
 ok=!ec;return result;
}
bool AddOnInGameFolder(const std::string& p){return fs::path(p).filename()=="addon.nsp";}
'''+function((r/'headless/prosperoeden/eden_services.cpp').read_text(),'std::vector<std::string> GameFiles() {')+r'''
'''+launcher_check+canonical+r'''
void write(const fs::path& p,const std::vector<unsigned char>& bytes){fs::create_directories(p.parent_path());std::ofstream f(p,std::ios::binary);f.write((const char*)bytes.data(),bytes.size());assert(f);}
'''+fixture+r'''
int main(){
 check_launcher();
 const auto root=fs::temp_directory_path()/"eden-dump-library-fixture";assert(!fs::exists(root));fs::create_directories(root/"roms");Eden::test_root=root.string();
 for(const auto& name:{"Pokopia/exefs/main","Welcome Tour/exefs/main","Game.nsp","Game/Game.xci"})assert(Eden::ValidRomPath(name));
 for(const auto& name:{"../exefs/main",".upload/exefs/main","/Game/exefs/main","Game/../exefs/main","Game/exefs/../main","Game/exefs/main.extra","Game//exefs/main","Game\\exefs/main","exefs/main"})assert(!Eden::ValidRomPath(name));
 assert(!Eden::ValidRomPath(std::string("Game\0/exefs/main",16)));
 for(const auto& name:{"Pokopia","Welcome Tour",".upload"}){
  const auto base=root/"roms"/name;write(base/"exefs/main",{'N','S','O','0'});write(base/"exefs/main.npdm",npdm());fs::create_directory(base/"romfs");
 }
 write(root/"roms/Loose.nsp",{1});write(root/"roms/Container/Game.xci",{1});write(root/"roms/Container/addon.nsp",{1});
 write(root/"roms/Incomplete/exefs/main",{'N','S','O','0'});write(root/"roms/Incomplete/exefs/main.npdm",npdm());
 const auto entry=root/"roms/Pokopia/exefs/main";
 assert(Eden::DumpMetadata::Ready(entry));assert(Eden::DumpMetadata::ProgramId(entry)==0x0400a3a01ee4c000ULL);
 const auto base=entry.parent_path().parent_path();
 for(const auto& name:{"RomFS","ROMFS"}){
  fs::rename(base/"romfs",base/name);assert(Eden::DumpMetadata::Ready(entry));
  fs::rename(base/name,base/"romfs");
 }
 fs::remove(base/"romfs");assert(!Eden::DumpMetadata::Ready(entry));
 write(base/"ROMFS",{1});assert(!Eden::DumpMetadata::Ready(entry));fs::remove(base/"ROMFS");
 fs::create_directory(base/"romfs");
'''+preference_check+r'''
 assert(!Eden::DumpMetadata::Ready(root/"roms/Incomplete/exefs/main"));
 auto files=GameFiles();assert((std::set<std::string>(files.begin(),files.end())==std::set<std::string>{"Pokopia/exefs/main","Welcome Tour/exefs/main","Loose.nsp","Container/Game.xci"}));
 auto b=npdm();b[0x70]=0xff;b[0x71]=0xff;write(entry.parent_path()/"main.npdm",b);assert(!Eden::DumpMetadata::Ready(entry));
 b=npdm();b[0x74]=0xff;b[0x75]=0xff;write(entry.parent_path()/"main.npdm",b);assert(!Eden::DumpMetadata::Ready(entry));
 b=npdm();b.resize(0x95);write(entry.parent_path()/"main.npdm",b);assert(!Eden::DumpMetadata::Ready(entry));
 b=npdm();b[0x500]='X';write(entry.parent_path()/"main.npdm",b);assert(!Eden::DumpMetadata::Ready(entry));
 b=npdm();b.resize(65537);write(entry.parent_path()/"main.npdm",b);assert(Eden::DumpMetadata::Ready(entry));
 write(entry.parent_path()/"main.npdm",npdm());write(entry,{'B','A','D','0'});assert(!Eden::DumpMetadata::Ready(entry));
 fs::remove_all(root);
}
'''
p=out/'test.cpp';p.write_text(code)
subprocess.run(['c++','-std=c++20','-O1','-g','-fsanitize=address,undefined','-pthread','-I'+str(r/'headless'),'-I'+str(source),str(p),'-o',str(out/'test')],check=True)
subprocess.run([str(out/'test')],check=True)
main=(r/'headless/main.cpp').read_text();assert 'const std::string nx2_main' not in main;assert 'selected_game = SelectProsperoEdenGame(rooms, launch_error)' in main
print('PASS: actual path validation/library enumeration, mixed-case RomFS directories and lowercase preference, missing/file RomFS rejection, containers, hidden/incomplete folders, canonical NPDM parsing, explicit library startup (ASan/UBSan)')
