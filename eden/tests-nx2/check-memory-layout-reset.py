"""Compile real core initialization/layout decisions with recording shims; dedie only."""
from pathlib import Path
import platform
import re
import subprocess
import tempfile

assert platform.system() == 'Linux', 'Compile on dedie'
root = Path(__file__).resolve().parents[1]
src = Path((root / '.local/headless-cache').read_text().strip()) / 'source/src'
text = (src / 'core/core.cpp').read_text()


def function(signature):
    start = text.index(signature)
    end = text.index('{', start) + 1
    depth = 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


# Use the production state declarations too, including the old boolean on main.
members = []
for pattern in (r'bool is_multicore\s*:[^;]+;',
                r'(?:bool extended_memory_layout\s*:[^;]+;|'
                r'Settings::MemoryLayout memory_layout\s*\{[^;]+;)'):
    matches = re.findall(pattern, text)
    assert len(matches) == 1, (pattern, matches)
    members.append(matches[0])

cpp = r'''
#include <cassert>
#include <iostream>
#include <memory>
#include <optional>
#include <string>
#define LOG_DEBUG(...) ((void)0)
namespace Settings {
enum class MemoryLayout { Memory_4Gb, Memory_6Gb, Memory_12Gb };
template<class T> struct Setting {
 T value{};
 T GetValue() const { return value; }
};
inline struct {
 Setting<MemoryLayout> memory_layout_mode;
 Setting<bool> use_multi_core, use_asynchronous_gpu_emulation;
} values;
}
namespace FileSys {
struct RealVfsFilesystem {};
struct ContentProviderUnion {};
}
struct System { void RegisterHostThread() {} };
struct DeviceMemory {
 inline static unsigned created{}, destroyed{};
 Settings::MemoryLayout layout = Settings::values.memory_layout_mode.GetValue();
 DeviceMemory() { ++created; }
 ~DeviceMemory() { ++destroyed; }
};
struct Impl {
 std::optional<DeviceMemory> device_memory;
 std::shared_ptr<FileSys::RealVfsFilesystem> virtual_filesystem;
 std::unique_ptr<FileSys::ContentProviderUnion> content_provider;
 struct Timing {
  void SetMulticore(bool) {}
  template<class F> void Initialize(F callback) { callback(); }
 } core_timing;
 struct Applets { void SetDefaultAppletsIfMissing() {} } frontend_applets;
 struct Manager {
  void SetMulticore(bool) {}
  void SetAsyncGpu(bool) {}
 } kernel, cpu_manager;
'''
cpp += '\n'.join(members) + '\n'
cpp += function('void Initialize(System& system)') + '\n'
cpp += function('void ReinitializeIfNecessary(System& system)') + '\n};\n'
cpp += r'''
Settings::MemoryLayout Layout(const std::string& value) {
 if (value == "4") return Settings::MemoryLayout::Memory_4Gb;
 if (value == "6") return Settings::MemoryLayout::Memory_6Gb;
 assert(value == "12");
 return Settings::MemoryLayout::Memory_12Gb;
}
int main(int argc, char** argv) {
 assert(argc == 3);
 System system;
 Impl impl;
 const std::string before = argv[1], after = argv[2];
 Settings::values.memory_layout_mode.value = Layout(before);
 impl.Initialize(system);
 assert(DeviceMemory::created == 1 && DeviceMemory::destroyed == 0);
 assert(impl.device_memory->layout == Layout(before));
 const bool missing = after == "missing", multicore = after == "multicore";
 const auto target = (missing || multicore) ? Layout(before) : Layout(after);
 if (missing) impl.device_memory.reset();
 if (multicore) Settings::values.use_multi_core.value = true;
 Settings::values.memory_layout_mode.value = target;
 const bool reset = missing || multicore || Layout(before) != target;
 impl.ReinitializeIfNecessary(system);
 assert(DeviceMemory::created == (reset ? 2u : 1u) && "layout change must recreate memory");
 assert(DeviceMemory::destroyed == (reset ? 1u : 0u));
 assert(impl.device_memory->layout == target && "backing must match selected layout");
 // The newly selected layout is remembered: a second call must retain the backing.
 impl.ReinitializeIfNecessary(system);
 assert(DeviceMemory::created == (reset ? 2u : 1u));
 assert(DeviceMemory::destroyed == (reset ? 1u : 0u));
 std::cout << before << "->" << after << " PASS\n";
}
'''

with tempfile.TemporaryDirectory(prefix='memory-layout-reset-') as td:
    out = Path(td)
    (out / 'test.cpp').write_text(cpp)
    subprocess.run(['clang++-18', '-std=c++20', '-O1', '-g',
                    '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                    str(out / 'test.cpp'), '-o', str(out / 'test')], check=True)
    failures = []
    for before, after in [('4', '12'), ('6', '12'), ('12', '6'),
                          ('6', '6'), ('12', '12'), ('4', '4'),
                          ('12', '4'), ('6', 'missing'), ('6', 'multicore')]:
        result = subprocess.run([str(out / 'test'), before, after], check=False)
        if result.returncode:
            failures.append(f'{before}->{after}')
    assert not failures, f'Memory layout reset failed: {failures}'
print('MEMORY_LAYOUT_RESET_PASS (ASan/UBSan)')
