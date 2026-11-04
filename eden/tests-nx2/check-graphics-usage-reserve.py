"""The texture cache's marks follow the shared pool: the last 1.25 GiB of it are not room for graphics.

Issue #20, run of #25 (00.065.025, Mario Kart World): the texture cache's marks were expected
4505 MiB and critical 5324 MiB on a 6144 MiB budget, against "usage" = budget - largest free
block of the pool. The CPU held 6.4 GiB of the pool, the largest free block fell from 4384 MiB to
630 MiB in 10 s, and the collector only evicted hard below 820 MiB. Compiles the generated
Device::GetDeviceMemoryUsage (the real tools/prepare-vulkan-port.py on the prepared source) and
checks the collector's mode at the console's numbers: high priority from 2.85 GiB of largest free
block, aggressive from 2.05 GiB. Fails on main (2 GiB free counted as 4096 MiB used: no eviction).
"""
from pathlib import Path
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile

assert platform.system() == 'Linux', 'Run on the Linux build server'
root = Path(__file__).resolve().parents[1]
if len(sys.argv) > 1:
    source = Path(sys.argv[1]).resolve()
else:
    source = Path((root / '.local/headless-cache').read_text().strip()) / 'source'

test = r'''
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#if __has_include("graphics_usage.h")
#include "graphics_usage.h"
#endif
using u64 = std::uint64_t;
constexpr u64 operator""_MiB(unsigned long long v) { return v << 20; }
namespace Eden::Performance {
std::atomic<unsigned long long (*)()> graphics_memory_free{nullptr};
std::atomic<bool> graphics_usage_from_pool{true};
}
struct Device {
    u64 device_access_memory = 6144_MiB;
    u64 GetDeviceMemoryUsage() const;
    u64 Driver() const { std::abort(); }
};
static unsigned long long largest_free = 0;
static unsigned long long Free() { return largest_free; }
GENERATED
// The console's marks (eden_log: "expected 4505, critical 5324" MiB).
constexpr u64 expected = 4505_MiB, critical = 5324_MiB;
static const char* Mode(const Device& device, unsigned long long free_mib) {
    largest_free = free_mib << 20;
    const u64 usage = device.GetDeviceMemoryUsage();
    return usage >= critical ? "aggressive" : usage >= expected ? "high priority" : "normal";
}
static int failures = 0;
static void Expect(const Device& device, unsigned long long free_mib, const char* mode) {
    const char* got = Mode(device, free_mib);
    if (std::string_view(got) != mode) {
        std::fprintf(stderr, "FAIL: largest free block %llu MiB: usage %llu MiB, collector %s, expected %s\n", free_mib,
                     static_cast<unsigned long long>(device.GetDeviceMemoryUsage() >> 20), got, mode);
        ++failures;
    }
}
int main() {
    Eden::Performance::graphics_memory_free = &Free;
    graphics_capacity = 10800_MiB;  // the pool's largest free block when the device was made
    Device device;
    Expect(device, 7832, "normal");          // 78.6 s
    Expect(device, 4384, "normal");          // 88.6 s
    Expect(device, 2900, "high priority");
    Expect(device, 2048, "aggressive");
    Expect(device, 630, "aggressive");       // 98.6 s, the refusal
    Expect(device, 0, "aggressive");
    // A pool that could never give graphics 6.4 GiB: the room left is scaled up, still monotonic.
    graphics_capacity = 4800_MiB;
    u64 last = 0;
    for (unsigned long long free_mib = 8000; free_mib-- > 0;) {
        largest_free = free_mib << 20;
        const u64 usage = device.GetDeviceMemoryUsage();
        assert(usage >= last && usage <= device.device_access_memory);
        last = usage;
    }
    if (failures) return 1;
    std::printf("PASS: texture cache marks against the shared pool: normal at 4384 MiB of largest free block, "
                "high priority at 2900, aggressive at 2048 and 630 (6144 MiB budget, marks 4505/5324 MiB)\n");
}
'''

with tempfile.TemporaryDirectory(prefix='eden-graphics-usage-') as temp:
    temp = Path(temp)
    tools = temp / 'bin'
    tools.mkdir()
    (tools / 'glslangValidator').write_text(
        '#!/bin/sh\nwhile [ $# -gt 0 ]; do [ "$1" = -o ] && printf \'\\003\\002\\043\\007\' > "$2"; shift; done\n')
    (tools / 'spirv-val').write_text('#!/bin/sh\nexit 0\n')
    for tool in tools.iterdir():
        tool.chmod(0o755)
    env = dict(os.environ, PATH=f'{tools}:{os.environ.get("PATH", "/usr/bin:/bin")}')
    subprocess.run([sys.executable, '-B', str(root / 'tools/prepare-vulkan-port.py'), str(source), str(temp / 'out')],
                   env=env, check=True, capture_output=True)
    device = (temp / 'out/vulkan_device.cpp').read_text()
    found = re.search(r'namespace \{\n// The largest block of the shared pool.*?\nu64 Device::GetDeviceMemoryUsage\(\) const \{\n'
                      r'(    if \(const auto free_memory = .*?\n    \}\n)', device, re.S)
    assert found, 'No pool branch in the generated Device::GetDeviceMemoryUsage'
    prefix = found.group(0)[:found.start(1) - found.start(0)]
    generated = prefix + found.group(1) + '    return Driver();\n}\n'
    (temp / 'check.cpp').write_text(test.replace('GENERATED', generated).replace('#include <cstdlib>', '#include <cstdlib>\n#include <string_view>'))
    compiler = os.environ.get('CXX') or next((c for c in ('clang++-18', 'clang++', 'g++') if shutil.which(c)), None)
    assert compiler, 'No host C++ compiler'
    subprocess.run([compiler, '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined', '-I' + str(root / 'headless'),
                    str(temp / 'check.cpp'), '-o', str(temp / 'check')], check=True)
    sys.exit(subprocess.run([str(temp / 'check')]).returncode)
