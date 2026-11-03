"""Compile the real pre-kernel platform probe with container/VFS shims; dedie only."""
from pathlib import Path
import platform
import re
import subprocess

assert platform.system() == 'Linux', 'Run on dedie'
root = Path(__file__).resolve().parents[1]
source = Path((root / '.local/headless-cache').read_text().strip()) / 'source/src'
out = root / 'build/nx2-tests/nsp-switch2-detect'
out.mkdir(parents=True, exist_ok=True)
text = (source / 'core/core.cpp').read_text()

def function(signature):
    start = text.index(signature)
    brace = text.index('{', start)
    end, depth = brace + 1, 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]

probe = function('bool IsSwitch2Program(')
# Use the real enum so the shim cannot hide unsupported file types (e.g. NSZ).
loader = (source / 'core/loader/loader.h').read_text()
file_type = re.search(r'enum class FileType\s*\{.*?\};', loader, re.S).group()
code = r'''
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <string_view>
using u64 = std::uint64_t;
namespace Loader {
enum class ResultStatus { Success, Error };
''' + file_type + r'''
}
namespace FileSys {
struct Dir;
using VirtualDir = std::shared_ptr<Dir>;
struct File {
    VirtualDir parent;
    Loader::FileType type = Loader::FileType::Unknown;
    Loader::ResultStatus status = Loader::ResultStatus::Success;
    bool switch2 = false;
    VirtualDir GetContainingDirectory() const { return parent; }
};
using VirtualFile = std::shared_ptr<File>;
struct Dir {
    VirtualFile npdm;
    VirtualFile GetFile(std::string_view name) const {
        assert(name == "main.npdm");
        return npdm;
    }
};
struct ProgramMetadata {
    bool switch2 = false;
    Loader::ResultStatus Load(const VirtualFile& file) {
        assert(file);
        switch2 = file->switch2;
        return file->status;
    }
    bool IsSwitch2() const { return switch2; }
};
enum class ContentRecordType { Program };
struct NCA {
    VirtualDir exefs;
    VirtualDir GetExeFS() const { return exefs; }
};
struct NSP {
    inline static Loader::ResultStatus status = Loader::ResultStatus::Success;
    inline static bool extracted = false;
    inline static VirtualDir exefs;
    inline static std::shared_ptr<NCA> program;
    inline static u64 seen_id = 0;
    inline static std::size_t seen_index = 0;
    inline static unsigned opens = 0, nca_reads = 0;
    NSP(const VirtualFile& file, u64 id, std::size_t index) {
        assert(file && file->type == Loader::FileType::NSP);
        seen_id = id; seen_index = index; ++opens;
    }
    Loader::ResultStatus GetStatus() const { return status; }
    bool IsExtractedType() const { return extracted; }
    VirtualDir GetExeFS() const { return exefs; }
    u64 GetProgramTitleID() const { return seen_id + seen_index; }
    std::shared_ptr<NCA> GetNCA(u64 id, ContentRecordType type) const {
        assert(!extracted && id == seen_id + seen_index);
        assert(type == ContentRecordType::Program);
        ++nca_reads;
        return program;
    }
};
}
namespace Loader {
FileType IdentifyFile(const FileSys::VirtualFile& file) {
    assert(file);
    return file->type;
}
}
''' + probe + '\n'
# Keep main's old signature compilable so it fails on behavior, not compilation.
args = 'file, id, index' if 'program_index' in probe.split('{', 1)[0] else 'file'
code += f'''
bool Detect(const FileSys::VirtualFile& file, u64 id = 0, std::size_t index = 0) {{
    return IsSwitch2Program({args});
}}
'''
code += r'''
int main() {
    using namespace FileSys;
    auto switch2 = std::make_shared<Dir>();
    switch2->npdm = std::make_shared<File>();
    switch2->npdm->switch2 = true;
    auto switch1 = std::make_shared<Dir>();
    switch1->npdm = std::make_shared<File>();
    auto file = std::make_shared<File>();
    file->type = Loader::FileType::NSP;
    NSP::program = std::make_shared<NCA>();
    NSP::program->exefs = switch2;
    // Main fails here: the NSP has no neighbouring NPDM.
    assert(Detect(file, 0x0400000012345000ULL, 3));
    assert(NSP::seen_id == 0x0400000012345000ULL && NSP::seen_index == 3);
    assert(NSP::opens == 1 && NSP::nca_reads == 1);
    assert(Detect(file));
    assert(NSP::seen_id == 0 && NSP::seen_index == 0);

    // A non-extracted NSP must use the selected Program NCA, not GetExeFS().
    NSP::exefs = switch2;
    NSP::program->exefs = switch1;
    assert(!Detect(file));
    NSP::program->exefs = switch2;
    NSP::status = Loader::ResultStatus::Error;
    auto reads = NSP::nca_reads;
    assert(!Detect(file) && NSP::nca_reads == reads);
    NSP::status = Loader::ResultStatus::Success;
    NSP::program.reset(); // Missing keys can leave a successful NSP with no Program NCA.
    file->parent = switch2; // Never fall back to a neighbour for an NSP.
    assert(!Detect(file));
    NSP::program = std::make_shared<NCA>();
    assert(!Detect(file)); // No ExeFS.
    NSP::program->exefs = std::make_shared<Dir>();
    assert(!Detect(file)); // No NPDM.
    NSP::program->exefs = switch2;
    switch2->npdm->status = Loader::ResultStatus::Error;
    assert(!Detect(file));
    switch2->npdm->status = Loader::ResultStatus::Success;

    NSP::extracted = true;
    NSP::program.reset();
    reads = NSP::nca_reads;
    assert(Detect(file) && NSP::nca_reads == reads);
    NSP::exefs = switch1;
    assert(!Detect(file));
    NSP::exefs.reset();
    assert(!Detect(file));

    const auto opens = NSP::opens;
    file->type = Loader::FileType::DeconstructedRomDirectory;
    assert(Detect(file));
    file->parent = switch1;
    assert(!Detect(file));
    file->parent = switch2;
    switch2->npdm->status = Loader::ResultStatus::Error;
    assert(!Detect(file));
    switch2->npdm.reset();
    assert(!Detect(file));
    file->parent.reset();
    assert(!Detect(file));
    assert(!Detect(nullptr));
    assert(NSP::opens == opens);
}
'''
path = out / 'test.cpp'
path.write_text(code)
subprocess.run(['clang++-18', '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
                str(path), '-o', str(out / 'test')], check=True)
subprocess.run([str(out / 'test')], check=True)
# Both pre-kernel consumers must share the result and the actual launch parameters.
load = function('    SystemResultStatus Load(')
assert load.count('IsSwitch2Program(') == 1
assert re.search(r'IsSwitch2Program\(GetGameFileFromPath\(virtual_filesystem, filepath\),\s*'
                 r'params.program_id,\s*params.program_index\)', load)
assert 'Settings::SetCurrentProgramIsSwitch2(switch2_program);' in load
assert re.search(r'if \(switch2_program &&\s*Settings::values.memory_layout_mode.GetValue\(\) != '
                 r'Settings::MemoryLayout::Memory_12Gb\)', load)
assert load.index('IsSwitch2Program(') < load.index('InitializeKernel(system);')
assert load.index('SetValue(Settings::MemoryLayout::Memory_12Gb)') < load.index('InitializeKernel(system);')
print('PASS: NSP platform detection, selected program, failure paths, extracted/loose ExeFS '
      'and pre-kernel wiring (ASan/UBSan)')
