"""Compile real loose-dump loader helpers against a case-sensitive VFS; dedie only."""
from pathlib import Path
import platform
import subprocess

assert platform.system() == 'Linux', 'Run on dedie'
root = Path(__file__).resolve().parents[1]
source = Path((root / '.local/headless-cache').read_text().strip()) / 'source/src'
out = root / 'build/nx2-tests/loose-dump-metadata'
out.mkdir(parents=True, exist_ok=True)
text = (source / 'core/loader/deconstructed_rom_directory.cpp').read_text()

def function(signature):
    start = text.index(signature)
    brace = text.index('{', start)
    end, depth = brace + 1, 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end] + '\n'

code = r'''
#include <algorithm>
#include <cassert>
#include <cctype>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>
namespace fmt {
std::string format(const char*, char a, char b, char c) { return {a, '.', b, '.', c}; }
}
namespace Eden::LoadTrace { void Step(const char*) {} }
namespace FileSys {
struct Dir;
using VirtualDir = std::shared_ptr<Dir>;
struct File {
    std::string name;
    std::weak_ptr<Dir> parent;
    VirtualDir built_from;
    auto GetName() const { return name; }
    auto GetExtension() const { return name.substr(name.find_last_of('.') + 1); }
    auto GetContainingDirectory() const { return parent.lock(); }
};
using VirtualFile = std::shared_ptr<File>;
struct Dir {
    std::string name;
    std::weak_ptr<Dir> parent;
    std::vector<VirtualDir> dirs;
    std::vector<VirtualFile> files;
    auto GetName() const { return name; }
    auto GetParentDirectory() const { return parent.lock(); }
    auto GetSubdirectories() const { return dirs; }
    auto GetFiles() const { return files; }
    VirtualDir GetSubdirectory(std::string_view name) const {
        for (const auto& dir : dirs) if (dir->name == name) return dir;
        return {};
    }
};
VirtualFile CreateRomFS(VirtualDir dir) {
    auto file = std::make_shared<File>(); file->built_from = std::move(dir); return file;
}
VirtualDir directory(const VirtualDir& parent, std::string name) {
    auto dir = std::make_shared<Dir>(); dir->name = name; dir->parent = parent;
    if (parent) parent->dirs.push_back(dir);
    return dir;
}
VirtualFile file(const VirtualDir& parent, std::string name) {
    auto file = std::make_shared<File>(); file->name = name; file->parent = parent;
    parent->files.push_back(file); return file;
}
}
using namespace FileSys;
enum class ResultStatus { Success, ErrorNoRomFS, ErrorNoControl };
struct Control {
    std::string version;
    auto GetVersionString() const { return version; }
};
struct AppLoader_DeconstructedRomDirectory {
    VirtualFile file, romfs;
    bool standalone = true;
    std::optional<Control> control;
    std::string romfs_version;
    ResultStatus ReadRomFS(VirtualFile&);
    ResultStatus ReadDisplayVersion(std::string&);
};
'''
# Optional extraction lets main's older source compile and fail a behavior assertion.
for signature in ('FileSys::VirtualDir FindLooseRomFSDirectory(',
                  'std::string NewestProductTag('):
    if signature in text:
        code += function(signature)
code += function('std::string RomFSProductVersion(')
code += function('ResultStatus AppLoader_DeconstructedRomDirectory::ReadRomFS(')
code += function('ResultStatus AppLoader_DeconstructedRomDirectory::ReadDisplayVersion(')
code += r'''
int main() {
    for (const char* name : {"RomFS", "Romfs", "romfs"}) {
        auto title = directory({}, "Game");
        auto exefs = directory(title, "exefs");
        auto romfs = directory(title, name);
        AppLoader_DeconstructedRomDirectory loader;
        loader.file = file(exefs, "main");
        VirtualFile result;
        assert(loader.ReadRomFS(result) == ResultStatus::Success);
        assert(result->built_from == romfs);
        // The other loose lookup supports a directory inside the executable folder.
        exefs->dirs.push_back(romfs);
        loader.romfs.reset();
        assert(loader.ReadRomFS(result) == ResultStatus::Success);
        assert(result->built_from == romfs);
        auto exact = directory(exefs, "romfs");
        loader.romfs.reset();
        assert(loader.ReadRomFS(result) == ResultStatus::Success);
        assert(result->built_from == (std::string{name} == "romfs" ? romfs : exact));
        // A packed .romfs still takes precedence over loose directories.
        auto packed = file(exefs, "game.romfs");
        loader.romfs.reset();
        assert(loader.ReadRomFS(result) == ResultStatus::Success && result == packed);
    }
    assert(RomFSProductVersion({}).empty());
    auto romfs = directory({}, "RomFS");
    assert(RomFSProductVersion(romfs).empty());
    auto data = directory(romfs, "GameData");
    file(data, "GameDataList.Product.320.byml.zs");
    assert(RomFSProductVersion(romfs) == "3.2.0");
    auto resource = directory(directory(romfs, "System"), "Resource");
    file(resource, "ResourceSizeTable.Product.rsizetable.zs");
    file(resource, "ResourceSizeTable.Product.180.rsizetable.zs");
    file(data, "GameDataList.Product.100.byml.zs");
    file(data, "GameDataList.Product.320.revision.txt");
    for (const char* bad : {"GameDataList.Product.9999.x", "GameDataList.Product.99.x",
                            "GameDataList.Product.9x9.x", "GameDataList.Product.999"})
        file(data, bad);
    assert(RomFSProductVersion(romfs) == "3.2.0");
    file(resource, "ResourceSizeTable.Product.410.rsizetable.zs");
    assert(RomFSProductVersion(romfs) == "4.1.0");
    data->files.clear();
    assert(RomFSProductVersion(romfs) == "4.1.0");
    AppLoader_DeconstructedRomDirectory loader;
    std::string version;
    assert(loader.ReadDisplayVersion(version) == ResultStatus::ErrorNoControl);
    loader.romfs_version = RomFSProductVersion(romfs);
    assert(loader.ReadDisplayVersion(version) == ResultStatus::Success && version == "4.1.0");
    loader.control = Control{"9.8.7"};
    assert(loader.ReadDisplayVersion(version) == ResultStatus::Success && version == "9.8.7");
    loader.control = Control{""};
    assert(loader.ReadDisplayVersion(version) == ResultStatus::Success && version == "4.1.0");
}
'''
path = out / 'test.cpp'
path.write_text(code)
subprocess.run(['clang++-18', '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
                str(path), '-o', str(out / 'test')], check=True)
subprocess.run([str(out / 'test')], check=True)
# Check constructor wiring as well as the compiled helpers and ReadRomFS call sites.
assert 'romfs_version = RomFSProductVersion(FindLooseRomFSDirectory(parent));' in text
print('PASS: mixed-case loose RomFS, newest product tags, packed RomFS and NACP precedence (ASan/UBSan)')
