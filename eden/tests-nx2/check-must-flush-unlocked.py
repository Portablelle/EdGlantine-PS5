"""UB-087: MustFlushRegion skips buffer_cache.mutex on Switch 2 for pages the GPU never wrote.

Compiles the PRODUCTION RasterizerVulkan::MustFlushRegion body (extracted from the prepared
vk_rasterizer.cpp), the PRODUCTION video_core/gpu_written_pages.h, and the PRODUCTION
MemoryTrackerBase::MarkRegionAsGpuModified body (memory_tracker_base.h) against fake caches whose
mutexes count lock() calls. The fake buffer cache records a GPU write the way MarkWrittenBuffer does
(tracker MarkRegionAsGpuModified, then add to gpu_modified_ranges); IsRegionGpuModified answers from
those ranges like BufferCache::IsRegionGpuModified. Checked:
 - Ampere on, no page marked: the buffer cache lock is not taken; QueryCache and TextureCache are
   still asked (and the texture cache lock still taken when GPU level is high);
 - Ampere on, a page marked (only at its last byte, an overlapping range, an image-only mark), a wrap
   or a range past the 36-bit bitmap: the lock is taken and a buffer GPU write answers true;
 - Ampere off: the lock is taken even with nothing marked;
 - size == 0: Any is false;
 - random writes/queries: whenever the buffer cache would say GPU-modified, MustFlushRegion says true
   (a stale "no flush" fails).
Source checks (the mark-path audit the lock-free answer relies on): MarkRegionAsGpuModified calls
GpuWrittenPages::Mark before setting Type::GPU, and is the only place that sets it; IsRegionGpuModified
reads only gpu_modified_ranges; the only two adds to gpu_modified_ranges (MarkWrittenBuffer and
DMACopy's mirrored ranges) are preceded by a covering MarkRegionAsGpuModified (mark before add, so a
lock-free reader that sees no mark cannot miss a range already added); the skip uses Any (not
AnyNonImage) and is gated on g_nx2_ampere.
Negative control: on main (no layer 99zzzzi) MustFlushRegion locks the buffer cache for an Ampere
never-written page, so the compiled harness fails on behavior; --source-only fails on the gate.
The compiled harness is Linux/dedie-only (needs g++).

Usage: check-must-flush-unlocked.py [--source-only] [SOURCE_DIR]   SOURCE_DIR contains src/
(default: this checkout's prepared build cache).
"""
from pathlib import Path
import platform
import re
import subprocess
import sys

args = [a for a in sys.argv[1:] if not a.startswith('--')]
source_only = '--source-only' in sys.argv[1:]
if not source_only:
    assert platform.system() == 'Linux', 'Run on the Linux build server'
root = Path(__file__).resolve().parents[1]
if args:
    source = Path(args[0]).resolve()
else:
    source = Path((root / '.local/headless-cache').read_text().strip()) / 'source'
vc = source / 'src/video_core'


def function(text, head, close='\n}\n'):
    start = text.index(head)
    return text[start:text.index(close, start) + len(close)]


rasterizer = (vc / 'renderer_vulkan/vk_rasterizer.cpp').read_text()
must_flush = function(rasterizer, 'bool RasterizerVulkan::MustFlushRegion(')
tracker = (vc / 'buffer_cache/memory_tracker_base.h').read_text()
mark_gpu = function(tracker, 'void MarkRegionAsGpuModified(', '\n    }\n')
cache = (vc / 'buffer_cache/buffer_cache.h').read_text()
cache_base = (vc / 'buffer_cache/buffer_cache_base.h').read_text()
pages_h = (vc / 'gpu_written_pages.h').read_text()

# The skip itself.
assert 'GpuWrittenPages::Any(addr, size)' in must_flush, 'buffer cache lock must be skipped via Any'
assert 'AnyNonImage' not in must_flush, 'image marks must count: use Any, not AnyNonImage'
assert 'Tegra::g_nx2_ampere.load(' in must_flush, 'the skip is Switch 2 only (g_nx2_ampere)'
assert must_flush.count('std::scoped_lock lock{buffer_cache.mutex}') == 1
assert must_flush.count('std::scoped_lock lock{texture_cache.mutex}') == 1
assert '#include "video_core/nx2.h"' in rasterizer

# Mark-path audit: a buffer GPU-modified answer implies a marked page.
assert re.search(r'void MarkRegionAsGpuModified\([^)]*\) noexcept \{\s*'
                 r'VideoCommon::GpuWrittenPages::Mark\(dirty_cpu_addr, query_size\);', mark_gpu), \
    'MarkRegionAsGpuModified must mark the GPU-written pages before the tracker state'
assert tracker.count('ChangeRegionState(Type::GPU, true') == 1, 'Type::GPU set outside MarkRegionAsGpuModified'
assert re.search(r'bool BufferCache<P>::IsRegionGpuModified\(DAddr addr, size_t size\) \{'
                 r'(\s*//[^\n]*)*\s*return gpu_modified_ranges\.Intersects\(addr, size\);\s*\}',
                 cache), 'IsRegionGpuModified must answer from gpu_modified_ranges only; re-audit'
adds = re.findall(r'gpu_modified_ranges\.Add\(|Nx2AddRangeOnce\(gpu_modified_ranges', cache)
assert len(adds) == 2, f'new add to gpu_modified_ranges ({len(adds)}): audit its GpuWrittenPages mark'
assert cache.count('Nx2AddRangeOnce(') == 1 and cache_base.count('Nx2AddRangeOnce(') == 1
assert not re.search(r'gpu_modified_ranges\s*=[^=]|swap\([^)]*gpu_modified_ranges', cache + cache_base)
written = function(cache, 'void BufferCache<P>::MarkWrittenBuffer(')
mark_at = written.index('memory_tracker.MarkRegionAsGpuModified(device_addr, size);')
assert mark_at < written.index('Nx2AddRangeOnce(gpu_modified_ranges, device_addr, size);'), \
    'MarkWrittenBuffer must mark the pages before adding the range'
copy_add = cache.index('gpu_modified_ranges.Add(pair.first, pair.second);')
copy_fn = cache[cache.rindex('\ntemplate <class P>', 0, copy_add):cache.index('\n}\n', copy_add)]
assert 'bool BufferCache<P>::DMACopy(' in copy_fn
assert 'const DAddr new_base_address = *cpu_dest_address + diff;' in copy_fn
mirrored = copy_fn.index('gpu_modified_ranges.ForEachInRange(*cpu_src_address, amount, mirror);')
copy_mark = re.search(r'const bool has_new_downloads = tmp_intervals\.size\(\) != 0;\s*'
                      r'if \(has_new_downloads\) \{(\s*//[^\n]*)*\s*'
                      r'memory_tracker\.MarkRegionAsGpuModified\(\*cpu_dest_address, amount\);',
                      copy_fn[mirrored:])
assert copy_mark, 'DMACopy must mark the destination right after collecting the mirrored ranges'
copy_mark_end = mirrored + copy_mark.end()
copy_subtract = copy_fn.index('gpu_modified_ranges.Subtract(*cpu_dest_address, amount);')
assert copy_mark_end < copy_subtract < copy_fn.index('gpu_modified_ranges.Add(pair.first, pair.second);'), \
    'DMACopy must mark before adding the mirrored ranges (Subtract then Add order kept)'
assert copy_fn.count('MarkRegionAsGpuModified(') == 1

# Bitmap rules the skip leans on.
assert 'inline constexpr u64 PageBits = 12;' in pages_h
assert 'if (last >= PageCount || last < first) {\n        return true;' in pages_h

if source_only:
    print('must-flush-unlocked source checks passed')
    sys.exit(0)

harness = r'''
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <mutex>
#include <random>
#include <utility>
#include <vector>
#include "video_core/gpu_written_pages.h"
using DAddr = u64;
using VAddr = u64;
namespace Tegra { std::atomic<bool> g_nx2_ampere{false}; }
namespace Settings { bool gpu_level_high = false; bool IsGPULevelHigh() { return gpu_level_high; } }
namespace VideoCommon {
enum class CacheType : u32 { None = 0, TextureCache = 1, QueryCache = 2, BufferCache = 4, All = 7 };
constexpr CacheType operator&(CacheType a, CacheType b) { return CacheType(u32(a) & u32(b)); }
constexpr bool True(CacheType c) { return u32(c) != 0; }
}
using VideoCommon::True;
struct CountingMutex {
    int locks = 0; bool held = false;
    void lock() { ++locks; held = true; }
    void unlock() { held = false; }
};
static bool Overlap(const std::vector<std::pair<u64, u64>>& r, u64 a, u64 s) {
    for (auto [b, e] : r) if (s && a < e && b < a + s) return true;
    return false;
}
enum class Type { CPU, GPU };
struct Manager {
    u64 cpu_addr = 0; std::vector<std::pair<u64, u64>> gpu;
    void ChangeRegionState(Type t, bool on, u64 addr, size_t size) {
        if (t == Type::GPU && on) gpu.push_back({addr, addr + size});
    }
};
struct Tracker {
    Manager manager;
    template <bool create, typename Func>
    void IteratePages(u64 addr, u64 size, Func&& func) { func(&manager, addr - manager.cpu_addr, size); }
''' + mark_gpu + r'''
};
struct FakeBufferCache {
    CountingMutex mutex; Tracker memory_tracker; std::vector<std::pair<u64, u64>> gpu_modified_ranges;
    // MarkWrittenBuffer: tracker mark, then the range.
    void MarkWritten(DAddr a, u64 s) { memory_tracker.MarkRegionAsGpuModified(a, s); gpu_modified_ranges.push_back({a, a + s}); }
    bool IsRegionGpuModified(DAddr a, u64 s) {
        if (!mutex.held) { std::fprintf(stderr, "buffer cache read without its lock\n"); std::abort(); }
        return Overlap(gpu_modified_ranges, a, s);
    }
};
struct FakeQueryCache { int asks = 0; bool modified = false; bool IsRegionGpuModified(DAddr, u64) { ++asks; return modified; } };
struct FakeTextureCache {
    CountingMutex mutex; bool modified = false;
    bool IsRegionGpuModified(DAddr, u64) { return mutex.held && modified; }
};
struct RasterizerVulkan {
    FakeBufferCache buffer_cache; FakeQueryCache query_cache; FakeTextureCache texture_cache;
    bool MustFlushRegion(DAddr addr, u64 size, VideoCommon::CacheType which);
};
''' + must_flush + r'''
static int fails = 0;
#define EXPECT(c) do { if (!(c)) { std::fprintf(stderr, "line %d: %s\n", __LINE__, #c); ++fails; } } while (0)
using VideoCommon::CacheType;
namespace P = VideoCommon::GpuWrittenPages;
constexpr u64 page = u64{1} << P::PageBits;
// Ask once; returns {answer, buffer cache locks taken}.
static std::pair<bool, int> Ask(RasterizerVulkan& r, u64 a, u64 s, CacheType w = CacheType::All) {
    const int before = r.buffer_cache.mutex.locks;
    const bool answer = r.MustFlushRegion(a, s, w);
    return {answer, r.buffer_cache.mutex.locks - before};
}
int main() {
    RasterizerVulkan r;
    Tegra::g_nx2_ampere = true;
    const u64 base = 0x10000000;
    // Never written: no buffer cache lock, other caches still asked.
    EXPECT(!P::Any(base, 64 * page));
    { int q = r.query_cache.asks; auto [a, l] = Ask(r, base, 64 * page);
      EXPECT(!a); EXPECT(l == 0); EXPECT(r.query_cache.asks == q + 1); }
    { auto [a, l] = Ask(r, base, 0); EXPECT(!a && l == 0); EXPECT(!P::Any(base, 0)); }
    r.query_cache.modified = true;
    { auto [a, l] = Ask(r, base, page); EXPECT(a && l == 0); }
    r.query_cache.modified = false;
    Settings::gpu_level_high = true; r.texture_cache.modified = true;
    { int t = r.texture_cache.mutex.locks; auto [a, l] = Ask(r, base, page);
      EXPECT(a && l == 0 && r.texture_cache.mutex.locks == t + 1); }
    Settings::gpu_level_high = false; r.texture_cache.modified = false;
    // A buffer write on the last byte of page 3 marks page 3 only.
    r.buffer_cache.MarkWritten(base + 4 * page - 1, 1);
    EXPECT(r.buffer_cache.memory_tracker.manager.gpu.size() == 1);
    EXPECT(P::Any(base + 3 * page, 1) && !P::Any(base, 3 * page) && !P::Any(base + 4 * page, page));
    { auto [a, l] = Ask(r, base + 4 * page - 1, 1); EXPECT(a && l == 1); }
    { auto [a, l] = Ask(r, base + 4 * page - 4, 8); EXPECT(a && l == 1); }
    { auto [a, l] = Ask(r, base, 64 * page); EXPECT(a && l == 1); }
    { auto [a, l] = Ask(r, base + 3 * page, 16); EXPECT(!a && l == 1); }  // marked page, not the bytes
    { auto [a, l] = Ask(r, base, 3 * page); EXPECT(!a && l == 0); }
    { auto [a, l] = Ask(r, base + 4 * page, 60 * page); EXPECT(!a && l == 0); }
    // An image-only mark still takes the lock (Any, not AnyNonImage).
    P::MarkImage(base + 100 * page, 1);
    { auto [a, l] = Ask(r, base + 100 * page + 8, 8); EXPECT(!a && l == 1); }
    // Past the bitmap (Mark clamps, nothing marked) and wraps: conservative.
    const u64 bitmap_end = P::PageCount * page;
    r.buffer_cache.MarkWritten(bitmap_end + 2 * page, 64);
    { auto [a, l] = Ask(r, bitmap_end + 2 * page, 8); EXPECT(a && l == 1); }
    { auto [a, l] = Ask(r, bitmap_end - 4, 8); EXPECT(l == 1); }
    { auto [a, l] = Ask(r, ~u64{0} - 3, 8); EXPECT(l == 1); }
    // Ampere off: always locked.
    Tegra::g_nx2_ampere = false;
    { auto [a, l] = Ask(r, base + 200 * page, page); EXPECT(!a && l == 1); }
    { auto [a, l] = Ask(r, base + 200 * page, page, CacheType::QueryCache); EXPECT(l == 0); }
    Tegra::g_nx2_ampere = true;
    // Never a stale "no flush" for a buffer GPU write.
    std::mt19937_64 rng{87};
    const u64 area = u64{1} << 30;
    int skipped = 0;
    for (int i = 0; i < 4000; ++i) {
        const u64 a = area + rng() % (64 << 20), s = rng() % (3 * page) + (i % 7 == 0 ? 0 : 1);
        if (i % 3 == 0) r.buffer_cache.MarkWritten(a, s ? s : 1);
        const bool truth = Overlap(r.buffer_cache.gpu_modified_ranges, a, s);
        auto [ans, l] = Ask(r, a, s);
        if (truth && !ans) { std::fprintf(stderr, "stale no-flush at %llx+%llx\n", (unsigned long long)a, (unsigned long long)s); ++fails; break; }
        EXPECT((l == 0) == !P::Any(a, s));
        skipped += l == 0;
    }
    EXPECT(skipped > 0);
    return fails ? 3 : 0;
}
'''
out = root / 'build/nx2-tests/must-flush-unlocked'
(out / 'shim/common').mkdir(parents=True, exist_ok=True)
(out / 'shim/common/common_types.h').write_text(
    '#pragma once\n#include <cstddef>\n#include <cstdint>\nusing u8 = std::uint8_t;\n'
    'using u32 = std::uint32_t;\nusing u64 = std::uint64_t;\nusing s64 = std::int64_t;\n')
cpp = out / 'harness.cpp'
cpp.write_text(harness)
subprocess.run(['g++', '-std=c++20', '-O1', '-I', str(out / 'shim'), '-I', str(source / 'src'),
                str(cpp), '-o', str(out / 'h')], check=True)
subprocess.run([str(out / 'h')], check=True)
print('must-flush-unlocked checks passed')
