"""The staging pool lets idle kept buffers go each frame: 256 MiB at most, none when memory is low.

Issue #20: during a loading burst the pool kept 610 MiB of buffers the GPU was done with (Eden lets
go of 16 per power of two per frame) while the shared pool refused the CPU 361 MiB. Compiles the
rule in headless/staging_buffers.h against a model of the pool's levels, then runs the real
tools/prepare-vulkan-port.py on the prepared source and checks the generated TickFrame applies it.
Fails on main before this change (no TrimIdle).
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
header = (root / 'headless/staging_buffers.h').read_text()
assert 'TrimIdle(' in header and 'IdleAllowance(' in header, 'staging_buffers.h has no idle trim rule'

test = r'''
#include <cassert>
#include <cstdio>
#include <span>
#include <vector>
#include "staging_buffers.h"
using namespace Eden::StagingBuffers;
constexpr std::uint64_t MiB = std::uint64_t{1} << 20;
struct Entry { std::span<unsigned char> mapped_span; unsigned log2_level; bool deferred; bool busy; int id; };
struct Level { std::vector<Entry> entries; std::size_t iterate_index = 0, delete_index = 0; };
using Cache = std::array<Level, 32>;
static unsigned char* const fake = reinterpret_cast<unsigned char*>(std::uintptr_t{1} << 40);
static Entry Make(std::uint64_t bytes, bool mapped, bool deferred, bool busy, int id) {
    unsigned log2 = 0;
    while ((std::uint64_t{1} << log2) < bytes) ++log2;
    return {mapped ? std::span<unsigned char>(fake, bytes) : std::span<unsigned char>{}, log2, deferred, busy, id};
}
static const auto idle = [](const Entry& e) { return !e.deferred && !e.busy; };
static std::uint64_t IdleBytes(const std::array<Cache*, 3>& caches) {
    std::uint64_t total = 0;
    for (auto* cache : caches) for (auto& level : *cache) for (auto& e : level.entries)
        if (idle(e)) total += Holds(e.mapped_span.size(), e.log2_level);
    return total;
}
static bool Has(const std::array<Cache*, 3>& caches, int id) {
    for (auto* cache : caches) for (auto& level : *cache) for (auto& e : level.entries) if (e.id == id) return true;
    return false;
}
static void Put(Cache& cache, Entry e) { cache[e.log2_level].entries.push_back(e); }

int main() {
    static_assert(IdleAllowance(static_cast<std::size_t>(-1)) == 256 * MiB);  // unknown: the cap
    static_assert(IdleAllowance(4096 * MiB) == 256 * MiB);
    static_assert(IdleAllowance(512 * MiB) == 256 * MiB);
    static_assert(IdleAllowance(512 * MiB - 1) == 0);                        // low: keep none
    static_assert(IdleAllowance(84 * MiB) == 0);

    // The console's burst: 105 idle buffers, 610 MiB, beside busy and deferred ones.
    Cache device{}, upload{}, download{};
    std::array<Cache*, 3> caches{&device, &upload, &download};
    int id = 0;
    for (int i = 0; i < 60; ++i) Put(upload, Make(2 * MiB, true, false, false, id++));        // 120 MiB
    for (int i = 0; i < 30; ++i) Put(download, Make(4 * MiB, true, false, false, id++));      // 120 MiB
    for (int i = 0; i < 10; ++i) Put(upload, Make(16 * MiB, true, false, false, id++));       // 160 MiB
    for (int i = 0; i < 3; ++i) Put(upload, Make(48 * MiB, true, false, false, id++));        // 144 MiB, exact sizes
    for (int i = 0; i < 2; ++i) Put(device, Make(32 * MiB, false, false, false, id++));       // 64 MiB, GPU only
    const int busy = id++, deferred = id++;
    Put(upload, Make(128 * MiB, true, false, true, busy));
    Put(download, Make(64 * MiB, true, true, false, deferred));
    upload[21].delete_index = 7; upload[21].iterate_index = 10;
    assert(IdleBytes(caches) == 608 * MiB);

    // Nothing to do under the cap.
    Cache small{}; std::array<Cache*, 3> one{&small, &small, &small};
    Put(small, Make(8 * MiB, true, false, false, 9999));
    assert(TrimIdle(one, idle, 256 * MiB).buffers == 0 && Has(one, 9999));

    const Released capped = TrimIdle(caches, idle, IdleAllowance(4096 * MiB));
    assert(IdleBytes(caches) <= 256 * MiB);
    assert(capped.bytes == 608 * MiB - IdleBytes(caches));
    assert(IdleBytes(caches) > 256 * MiB - 128 * MiB);  // stops near the cap, not everything
    assert(Has(caches, busy) && Has(caches, deferred));    // buffers in use stay
    for (int i = 100; i < 105; ++i) assert(!Has(caches, i));  // the largest idle ones went first
    assert(Has(caches, 0) && Has(caches, 60));                // the small ones stay for reuse
    for (auto* cache : caches) for (auto& level : *cache) {
        assert(level.delete_index < level.entries.size() || level.delete_index == 0);
        assert(level.iterate_index <= level.entries.size());
    }
    // Low memory: every idle buffer goes, busy and deferred stay.
    const Released low = TrimIdle(caches, idle, IdleAllowance(125 * MiB));
    assert(IdleBytes(caches) == 0 && low.bytes > 0);
    assert(Has(caches, busy) && Has(caches, deferred));
    std::printf("PASS: idle staging trim: 608 MiB idle -> %llu MiB (cap 256, largest first), then 0 when the largest free block < 512 MiB; busy/deferred kept\n",
                static_cast<unsigned long long>((608 * MiB - capped.bytes) / MiB));
}
'''

if len(sys.argv) > 1:
    source = Path(sys.argv[1]).resolve()
else:
    source = Path((root / '.local/headless-cache').read_text().strip()) / 'source'
with tempfile.TemporaryDirectory(prefix='eden-staging-trim-') as temp:
    temp = Path(temp)
    compiler = os.environ.get('CXX') or next((c for c in ('clang++-18', 'clang++', 'g++') if shutil.which(c)), None)
    assert compiler, 'No host C++ compiler'
    (temp / 'check.cpp').write_text(test)
    subprocess.run([compiler, '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined', '-D_GLIBCXX_ASSERTIONS',
                    '-I' + str(root / 'headless'), str(temp / 'check.cpp'), '-o', str(temp / 'check')], check=True)
    subprocess.run([str(temp / 'check')], check=True)

    # The generated pool applies it in TickFrame, with the pool's largest free block.
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
    pool = (temp / 'out/vulkan_staging_buffer_pool.cpp').read_text()
    tick = re.search(r'void StagingBufferPool::TickFrame\(\) \{.*?\n\}\n', pool, re.S)
    assert tick, 'No TickFrame in the generated pool'
    body = tick.group(0)
    for needed in ('ReleaseCache(MemoryUsage::Download);', 'TrimIdle(', 'IdleAllowance(largest)',
                   'eden_direct_memory_free(&pool_free, &largest)', '&device_local_cache, &upload_cache, &download_cache',
                   '!entry.deferred && scheduler.IsFree(entry.tick)'):
        assert needed in body, 'Generated TickFrame lacks: ' + needed
print('PASS: generated TickFrame trims idle staging buffers with the pool\'s largest free block')
