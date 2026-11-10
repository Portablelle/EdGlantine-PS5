"""UB-062: exact CPU uploads on GPU-owned pages, with pre-copy download cancellation.

Extracts production WriteMemory, CachedWriteMemory, InlineMemoryImplementation,
SynchronizeBufferPages, ClearDownload, both WriteBlockImpl mapped lambdas and Vulkan/OpenGL
PrepareRegionWrite into a recording C++ fixture. The page tracker is deliberately page-granular;
exact GPU intervals and guest/GPU bytes are recorded separately. Main compiles the same fixture
(with an empty PrepareRegionWrite) and FAILS by behavior: a small write dirties a whole page,
and WriteBlock invalidation sees old bytes. No compiler is invoked by --source-only: it replays
production mapped-lambda event order with a pending fence download and checks the source wiring.

Linux/dedie: python3 eden/tests-nx2/check-inline-page-writes.py [SOURCE_DIR]
Source checks: add --source-only. SOURCE_DIR contains src/; default is the prepared build cache.
Negative control: run this SAME script against main prepared WITHOUT 99zzzz9 (all 113 earlier
layers). It must fail; do not remove earlier fence filtering or inline-upload layers.
"""
from pathlib import Path
import os
import platform
import re
import subprocess
import sys

args = [a for a in sys.argv[1:] if not a.startswith('--')]
source_only = '--source-only' in sys.argv[1:]
root = Path(__file__).resolve().parents[1]
source = Path(args[0]).resolve() if args else Path(
    (root / '.local/headless-cache').read_text().strip()) / 'source'
src = source / 'src/video_core'
cache = (src / 'buffer_cache/buffer_cache.h').read_text()
manager = (src / 'memory_manager.cpp').read_text()


def function(text, signature, optional=False):
    if optional and signature not in text:
        return ''
    assert text.count(signature) == 1, signature
    start = text.index(signature)
    end = text.index('{', start) + 1
    depth = 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


write_block_impl = function(manager, 'void MemoryManager::WriteBlockImpl(')
mapped = [function(write_block_impl, 'auto mapped_' + kind + ' = [&](', optional=False)
          for kind in ('normal', 'big')]
prepare = []
for backend, short, cls in [('vulkan', 'vk', 'RasterizerVulkan'),
                            ('opengl', 'gl', 'RasterizerOpenGL')]:
    text = (src / f'renderer_{backend}/{short}_rasterizer.cpp').read_text()
    prepare.append(function(text, f'void {cls}::PrepareRegionWrite(', optional=True))


def source_checks():
    # Replay events from the actual mapped lambdas. A fence fires immediately after the guest
    # copy. Pre-copy invalidation samples 0x11; an uncancelled fence replaces 0x33 with 0x77.
    # This runs on main too and fails on the resulting bytes, not on a missing hook name.
    for path in mapped:
        guest, uploaded, pending = 0x11, None, True
        for event in re.findall(r'PrepareRegionWrite|InvalidateRegion|memory.WriteBlockUnsafe', path):
            if event == 'PrepareRegionWrite':
                pending = False
            elif event == 'InvalidateRegion':
                uploaded = guest
            else:
                guest = 0x33
                if pending:
                    guest = 0x77
        assert (guest, uploaded) == (0x33, 0x33), (
            'WriteBlock behavior: new guest bytes lost or invalidate uploaded old bytes', guest, uploaded)
        assert 'GpuWrittenPages::Mark(dev_addr_base, copy_amount)' in path
    for text in prepare:
        assert text.index('std::scoped_lock lock{buffer_cache.mutex}') < text.index(
            'buffer_cache.ClearDownload(addr, size)')
        assert 'False(which & VideoCommon::CacheType::BufferCache)' in text
    header = (src / 'buffer_cache/buffer_cache_base.h').read_text()
    assert header.index('void ClearDownload(') < header.index('private:')
    assert 'virtual void PrepareRegionWrite(' in (src / 'rasterizer_interface.h').read_text()
    for backend, short in [('vulkan', 'vk'), ('opengl', 'gl')]:
        assert 'void PrepareRegionWrite(' in (src / f'renderer_{backend}/{short}_rasterizer.h').read_text()
    # Existing filtering and exact ownership must survive; this layer does not replace them.
    assert 'QueueFenceDownload' in cache and 'ForEachPreflushableRange' in header
    clear = function(cache, 'void BufferCache<P>::ClearDownload(')
    assert 'DropPendingFenceCopies' in clear
    assert 'gpu_modified_ranges.Subtract' not in clear.replace('uncommitted_gpu_modified_ranges.Subtract', '').replace('committed_gpu_modified_ranges.Subtract', '')
    inline = function(cache, 'void BufferCache<P>::InlineMemoryImplementation(')
    assert 'gpu_modified_ranges.Subtract(dest_address, copy_size)' in inline
    assert 'SynchronizeBuffer(buffer, dest_address, static_cast<u32>(copy_size))' in inline
    assert 'DownloadMemory' not in function(cache, 'void BufferCache<P>::WriteMemory(')


if source_only:
    source_checks()
    print('Inline page writes: source checks and WriteBlock ordering replay PASS (C++ not run)')
    sys.exit(0)
assert platform.system() == 'Linux', 'Run C++ fixture on Linux/dedie'
out = root / 'build/nx2-tests/inline-page-writes'
out.mkdir(parents=True, exist_ok=True)

fixture = r'''
#include <algorithm>
#include <array>
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <span>
#include <vector>
using u8 = uint8_t; using u32 = uint32_t; using u64 = uint64_t; using DAddr = u64;
constexpr u64 DEVICE_PAGESIZE = 4096;
namespace Common {
u64 AlignDown(u64 a, u64 b) { return a / b * b; }
u64 AlignUp(u64 a, u64 b) { return (a + b - 1) / b * b; }
}
namespace Tegra { std::atomic<bool> g_nx2_ampere{true}; }
namespace VideoCommon {
enum class CacheType { None = 0, BufferCache = 1, All = 3 };
CacheType operator&(CacheType a, CacheType b) { return CacheType(int(a) & int(b)); }
namespace GpuWrittenPages { int marks = 0; void Mark(u64, u64) { ++marks; } }
}
bool False(VideoCommon::CacheType v) { return int(v) == 0; }
struct Mutex { bool held = false; void lock() { assert(!held); held = true; } void unlock() { assert(held); held = false; } };
struct Ranges {
    std::array<bool, 8192> bits{};
    void Add(u64 a, u64 s) { for (; s; --s) bits.at(a++) = true; }
    void Subtract(u64 a, u64 s) { for (; s; --s) bits.at(a++) = false; }
    bool Intersects(u64 a, u64 s) { for (; s; --s) if (bits.at(a++)) return true; return false; }
    template<class F> void ForEachInRange(u64 a, u64 s, F f) {
        u64 end = a + s;
        while (a < end) { if (!bits.at(a)) { ++a; continue; } u64 b = a++;
            while (a < end && bits.at(a)) ++a; f(b, a); }
    }
};
void DropPendingFenceCopies(u64 a, u64 s, Ranges& pending, Ranges& async) {
    pending.Subtract(a, s); async.Subtract(a, s);
}
struct Tracker {
    bool cpu = false;
    void MarkRegionAsCpuModified(u64, u64) { cpu = true; }
    template<class F> void ForEachUploadRange(u64 a, u64 s, F f) {
        if (cpu) { cpu = false; u64 b = Common::AlignDown(a, DEVICE_PAGESIZE);
            f(b, Common::AlignUp(a+s, DEVICE_PAGESIZE)-b); }
    }
};
struct Bytes : std::vector<u8> { void resize_destructive(size_t n) { resize(n); } };
struct Memory {
    std::array<u8, 8192> guest{};
    Ranges* pending = nullptr; Ranges* async = nullptr;
    void ReadBlockUnsafe(u64 a, void* p, u64 s) { std::memcpy(p, guest.data()+a, s); }
    void WriteBlockUnsafe(u64 a, const void* p, u64 s) {
        std::memcpy(guest.data()+a, p, s);
        // Fence at the vulnerable point: after memcpy, before post-copy invalidation.
        for (u64 i = a; i < a+s; ++i)
            if (pending->bits[i] || async->bits[i]) guest[i] = 0x77;
    }
};
struct BufferCopy { u64 src_offset, dst_offset, size; };
struct Buffer {
    std::array<u8, 8192> gpu{};
    u64 cpu_addr_cached = 0, uploaded = 0;
    u64 Offset(u64 a) { return a; }
    void ImmediateUpload(u64 a, std::span<const u8> b) {
        uploaded += b.size(); std::copy(b.begin(), b.end(), gpu.begin()+a);
    }
};
struct Runtime {
    struct Staging { u64 offset; std::span<u8> mapped_span; Buffer buffer; };
    std::array<u8, 8192> staging{};
    Staging UploadStagingBuffer(u64 s) { return {0, std::span<u8>(staging).first(s), {}}; }
    bool CanReorderUpload(Buffer&, std::span<BufferCopy>) { return false; }
    void CopyBuffer(Buffer& dst, Buffer&, std::span<BufferCopy> copies, bool, bool) {
        for (auto c : copies) dst.ImmediateUpload(c.dst_offset,
            std::span<const u8>(staging).subspan(c.src_offset, c.size));
    }
};
using BufferId = size_t;
template<class P> struct BufferCache {
    using Buffer = ::Buffer;
    static constexpr bool USE_MEMORY_MAPS_FOR_UPLOADS = UB062_MAPPED;
    Mutex mutex;
    Memory device_memory;
    Tracker memory_tracker;
    Ranges gpu_modified_ranges, pending_downloads, async_downloads, uncommitted_gpu_modified_ranges;
    std::vector<Ranges> committed_gpu_modified_ranges{1};
    Bytes tmp_buffer;
    Runtime runtime;
    std::array<Buffer, 1> slot_buffers;
    std::vector<BufferCopy> upload_copies;
    bool registered = true, any_buffer_uploaded = false;
    BufferCache() {
        device_memory.guest.fill(0x11); slot_buffers[0].gpu.fill(0x11);
        gpu_modified_ranges.Add(512, 512);
        std::fill_n(slot_buffers[0].gpu.begin()+512, 512, 0x77);
        device_memory.pending = &pending_downloads; device_memory.async = &async_downloads;
    }
    bool IsRegionRegistered(u64, u64) { return registered; }
    bool IsRegionGpuModified(u64 a, u64 s) { return gpu_modified_ranges.Intersects(a, s); }
    BufferId FindBuffer(u64, u32, bool) { assert(registered); return 0; }
    bool SynchronizeBuffer(Buffer& b, u64 a, u32 s) { return SynchronizeBufferPages(b, a, s); }
    void UploadMemory(Buffer& b, u64, u64, std::span<BufferCopy> copies) {
        for (auto c : copies) b.ImmediateUpload(c.dst_offset,
            std::span<const u8>(device_memory.guest).subspan(c.dst_offset, c.size));
    }
    void WriteMemory(DAddr, u64);
    void CachedWriteMemory(DAddr, u64);
    void InlineMemoryImplementation(DAddr, size_t, std::span<const u8>);
    void ClearDownload(DAddr, u64);
    bool SynchronizeBufferPages(Buffer&, DAddr, u32);
};
'''
for signature in ['void BufferCache<P>::WriteMemory(', 'void BufferCache<P>::CachedWriteMemory(',
                  'void BufferCache<P>::InlineMemoryImplementation(',
                  'void BufferCache<P>::ClearDownload(', 'bool BufferCache<P>::SynchronizeBufferPages(']:
    fixture += '\ntemplate<class P>\n' + function(cache, signature) + '\n'
fixture += r'''
struct RasterizerVulkan {
    BufferCache<int>& buffer_cache;
    void PrepareRegionWrite(DAddr, u64, VideoCommon::CacheType);
    void InvalidateRegion(DAddr a, u64 s, VideoCommon::CacheType which) {
        if (!False(which & VideoCommon::CacheType::BufferCache)) buffer_cache.WriteMemory(a, s);
    }
};
struct RasterizerOpenGL : RasterizerVulkan {
    void PrepareRegionWrite(DAddr, u64, VideoCommon::CacheType);
};
'''
for text, cls in zip(prepare, ['RasterizerVulkan', 'RasterizerOpenGL']):
    fixture += text or f'void {cls}::PrepareRegionWrite(DAddr, u64, VideoCommon::CacheType) {{}}'
    fixture += '\n'
fixture += r'''
void write_block(BufferCache<int>& cache, bool big, bool unsafe) {
    auto& memory = cache.device_memory;
    RasterizerVulkan raster{cache}; auto* rasterizer = &raster;
    std::array<u64, 1> page_table{0}, big_page_table_dev{0};
    constexpr int cpu_page_bits = 12;
    auto which = VideoCommon::CacheType::All;
    const std::array<u8, 4> bytes{0x33, 0x33, 0x33, 0x33};
    const void* src_buffer = bytes.data();
'''
fixture += '\n'.join(text + ';' for text in mapped)
fixture += r'''
    if (big) mapped_big(0, 600, bytes.size()); else mapped_normal(0, 600, bytes.size());
}
int main(int argc, char**) {
    Tegra::g_nx2_ampere.store(std::getenv("UB062_NX2")[0] == '1');
    bool enabled = argc == 2;
    // Same-page adjacent GPU data and a write overlapping GPU data: exact uploads only.
    for (u64 addr : {128, 600}) {
        BufferCache<int> cache;
        std::fill_n(cache.device_memory.guest.begin()+addr, 4, 0x33);
        cache.WriteMemory(addr, 4);
        if (enabled) {
            assert(cache.slot_buffers[0].uploaded == 4);
            assert(!cache.memory_tracker.cpu);
            assert(cache.slot_buffers[0].gpu[addr] == 0x33);
        } else {
            assert(cache.slot_buffers[0].uploaded == 0 && cache.memory_tracker.cpu);
            cache.SynchronizeBufferPages(cache.slot_buffers[0], addr, 4);
            assert(cache.slot_buffers[0].uploaded > 4); // today's page recopy fallback
        }
        assert(cache.gpu_modified_ranges.bits[700]);
        assert(cache.slot_buffers[0].gpu[700] == 0x77);
        assert(!cache.gpu_modified_ranges.bits[addr]);
    }
    BufferCache<int> uncovered;
    uncovered.registered = false; uncovered.WriteMemory(128, 4);
    assert(uncovered.slot_buffers[0].uploaded == 0 && uncovered.memory_tracker.cpu);
    BufferCache<int> clean;
    clean.gpu_modified_ranges = {}; clean.WriteMemory(128, 4);
    assert(clean.slot_buffers[0].uploaded == 0 && clean.memory_tracker.cpu);
    // Existing cached writes stay inline even when the new WriteMemory switch is off.
    BufferCache<int> cached;
    cached.CachedWriteMemory(128, 4); assert(cached.slot_buffers[0].uploaded == 4);
    for (bool big : {false, true}) {
        BufferCache<int> cache;
        cache.pending_downloads.Add(600, 4); cache.async_downloads.Add(600, 4);
        cache.pending_downloads.Add(700, 4);
        cache.uncommitted_gpu_modified_ranges.Add(600, 104);
        cache.committed_gpu_modified_ranges[0].Add(600, 104);
        write_block(cache, big, false);
        assert(cache.device_memory.guest[600] == 0x33);
        if (enabled) assert(cache.slot_buffers[0].gpu[600] == 0x33);
        assert(!cache.pending_downloads.bits[600] && !cache.async_downloads.bits[600]);
        assert(cache.pending_downloads.bits[700] && cache.gpu_modified_ranges.bits[700]);
        assert(!cache.uncommitted_gpu_modified_ranges.bits[600]);
        assert(!cache.committed_gpu_modified_ranges[0].bits[600]);
        assert(cache.uncommitted_gpu_modified_ranges.bits[700]);
        assert(cache.committed_gpu_modified_ranges[0].bits[700]);
        assert(!cache.mutex.held);
    }
    assert(VideoCommon::GpuWrittenPages::marks == 2);
    // Unsafe writes retain the old contract: no prepare/invalidation, but still marked.
    BufferCache<int> unsafe; write_block(unsafe, false, true);
    assert(unsafe.device_memory.guest[600] == 0x33 && unsafe.slot_buffers[0].uploaded == 0);
    BufferCache<int> gl;
    gl.pending_downloads.Add(600, 4);
    RasterizerOpenGL raster{{gl}};
    raster.PrepareRegionWrite(600, 4, VideoCommon::CacheType::None);
    assert(gl.pending_downloads.bits[600]);
    raster.PrepareRegionWrite(600, 4, VideoCommon::CacheType::All);
    assert(!gl.pending_downloads.bits[600] && !gl.mutex.held);
}
'''
(out / 'test.cpp').write_text(fixture)
# Exercise both Vulkan's mapped staging upload and the immediate-upload backend.
for mapped_uploads in [0, 1]:
    subprocess.run(['clang++-18', '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
                    f'-DUB062_MAPPED={mapped_uploads}', str(out / 'test.cpp'),
                    '-o', str(out / 'test')], check=True)
    # Production caches the env override: fresh processes for each setting and title default.
    for forced, nx2, enabled in [(None, True, True), (None, False, False),
                                 ('0', True, False), ('1', False, True)]:
        env = dict(os.environ)
        env.pop('EDEN_NX2_INLINE_PAGE_WRITES', None)
        if forced is not None:
            env['EDEN_NX2_INLINE_PAGE_WRITES'] = forced
        env['UB062_NX2'] = '1' if nx2 else '0'
        subprocess.run([str(out / 'test')] + (['enabled'] if enabled else []), env=env, check=True)

source_checks()
print('Inline page writes: production C++ behavior and source checks PASS')
