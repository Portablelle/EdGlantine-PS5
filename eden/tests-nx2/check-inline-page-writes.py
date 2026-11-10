"""UB-062: exact CPU uploads on GPU-owned pages, with pre-copy download cancellation.

Extracts production WriteMemory, WriteMemoryAfterWrite, CachedWriteMemory,
InlineMemoryImplementation, SynchronizeBufferPages, ClearDownload, both WriteBlockImpl mapped
lambdas and Vulkan/OpenGL PrepareRegionWrite / InvalidateRegionAfterWrite into a recording C++
fixture. The page tracker is deliberately page-granular;
exact GPU intervals and guest/GPU bytes are recorded separately. Coverage is a page table plus
bounded existing buffers; attempted create/merge is recorded. Direct invalidations never inline,
large/partial/missing-buffer writes fall back, and inline-off retains main's pre-copy order.
Main compiles the same fixture (with default no-op/fallback hooks) and FAILS by behavior:
a qualifying WriteBlock does not upload the new bytes at the exact write size. No compiler is
invoked by --source-only: it replays production mapped-lambda event order with a pending fence
download and checks the source wiring.

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
after_write = []
for backend, short, cls in [('vulkan', 'vk', 'RasterizerVulkan'),
                            ('opengl', 'gl', 'RasterizerOpenGL')]:
    text = (src / f'renderer_{backend}/{short}_rasterizer.cpp').read_text()
    prepare.append(function(text, f'void {cls}::PrepareRegionWrite(', optional=True))
    after_write.append(function(text, f'void {cls}::InvalidateRegionAfterWrite(', optional=True))


def mapped_events(path, inline_writes, unsafe=False):
    """Interpret the mapped lambda's conditional call order, including main's old lambda."""
    path = re.sub(r'//[^\n]*', '', path)
    tokens = re.findall(r'if\s*\((?:inline_writes|!unsafe)\)|else|[{}]|'
                        r'PrepareRegionWrite|InvalidateRegionAfterWrite|InvalidateRegion|'
                        r'memory.WriteBlockUnsafe', path)
    index = 0

    def statement():
        nonlocal index
        token = tokens[index]
        index += 1
        if token == '{':
            result = []
            while tokens[index] != '}':
                result += statement()
            index += 1
            return result
        if token.startswith('if'):
            take = inline_writes if 'inline_writes' in token else not unsafe
            yes = statement()
            no = []
            if index < len(tokens) and tokens[index] == 'else':
                index += 1
                no = statement()
            return yes if take else no
        return [token]

    result = statement()
    assert index == len(tokens)
    return result


def source_checks():
    for path in mapped:
        for enabled in (True, False):
            events = mapped_events(path, enabled)
            guest, uploaded, pending = 0x11, None, True
            for event in events:
                if event == 'PrepareRegionWrite':
                    pending = False
                elif event == 'InvalidateRegion':
                    # Main's WriteMemory cancels downloads and marks CPU-dirty, never uploads.
                    pending = False
                elif event == 'InvalidateRegionAfterWrite':
                    uploaded = guest
                else:
                    guest = 0x33
                    if pending:
                        guest = 0x77
            if enabled:
                assert (guest, uploaded) == (0x33, 0x33), (
                    'WriteBlock behavior: qualifying post-copy write must upload new bytes',
                    guest, uploaded, events)
                assert events == ['PrepareRegionWrite', 'memory.WriteBlockUnsafe',
                                  'InvalidateRegionAfterWrite']
            else:
                assert events == ['InvalidateRegion', 'memory.WriteBlockUnsafe'], events
                assert guest == 0x33 and uploaded is None
        assert mapped_events(path, False, True) == ['memory.WriteBlockUnsafe']
        assert 'GpuWrittenPages::Mark(dev_addr_base, copy_amount)' in path
    # All other callers, including pre-copy NCE invalidations, retain main's exact body.
    main_body = """void BufferCache<P>::WriteMemory(DAddr device_addr, u64 size) {
        if (IsRegionGpuModified(device_addr, size)) {
            ClearDownload(device_addr, size);
            gpu_modified_ranges.Subtract(device_addr, size);
        }
        memory_tracker.MarkRegionAsCpuModified(device_addr, size);
    }"""
    assert re.sub(r'\s+', '', function(cache, 'void BufferCache<P>::WriteMemory(')) == re.sub(r'\s+', '', main_body)
    post = function(cache, 'void BufferCache<P>::WriteMemoryAfterWrite(')
    assert 'size <= DEVICE_PAGESIZE' in post
    assert 'page_table[device_addr >> CACHING_PAGEBITS]' in post
    assert 'buffer_id && slot_buffers[buffer_id].IsInBounds(device_addr, size)' in post
    assert 'IsRegionRegistered' not in post
    assert post.index('IsInBounds') < post.index('InlineMemoryImplementation')
    assert 'WriteMemory(device_addr, size)' in post
    for text in prepare:
        assert text.index('std::scoped_lock lock{buffer_cache.mutex}') < text.index(
            'buffer_cache.ClearDownload(addr, size)')
        assert 'False(which & VideoCommon::CacheType::BufferCache)' in text
    for backend, short, cls, post_hook in zip(
            ['vulkan', 'opengl'], ['vk', 'gl'], ['RasterizerVulkan', 'RasterizerOpenGL'], after_write):
        text = (src / f'renderer_{backend}/{short}_rasterizer.cpp').read_text()
        original = function(text, f'void {cls}::InvalidateRegion(')
        assert post_hook == original.replace('::InvalidateRegion(', '::InvalidateRegionAfterWrite(').replace(
            'buffer_cache.WriteMemory(addr, size)', 'buffer_cache.WriteMemoryAfterWrite(addr, size)')
        # The sole backend entry to buffer inline is the dedicated post-copy hook.
        assert text.count('buffer_cache.WriteMemoryAfterWrite(') == 1
    # The only external caller of the post-copy rasterizer hook is WriteBlockImpl.
    callers = []
    for file in src.rglob('*'):
        if file.suffix in ('.cpp', '.h') and '->InvalidateRegionAfterWrite(' in file.read_text():
            callers.append(file.relative_to(src).as_posix())
    assert callers == ['memory_manager.cpp'], callers
    assert manager.count('->InvalidateRegionAfterWrite(') == 2
    header = (src / 'buffer_cache/buffer_cache_base.h').read_text()
    assert header.index('void ClearDownload(') < header.index('private:')
    interface = (src / 'rasterizer_interface.h').read_text()
    assert 'virtual void PrepareRegionWrite(' in interface
    assert 'virtual void InvalidateRegionAfterWrite(' in interface
    assert 'QueueFenceDownload' in cache and 'ForEachPreflushableRange' in header
    clear = function(cache, 'void BufferCache<P>::ClearDownload(')
    assert 'DropPendingFenceCopies' in clear
    assert 'gpu_modified_ranges.Subtract' not in clear.replace('uncommitted_gpu_modified_ranges.Subtract', '').replace('committed_gpu_modified_ranges.Subtract', '')
    inline = function(cache, 'void BufferCache<P>::InlineMemoryImplementation(')
    assert 'gpu_modified_ranges.Subtract(dest_address, copy_size)' in inline
    assert 'SynchronizeBuffer(buffer, dest_address, static_cast<u32>(copy_size))' in inline


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
constexpr int CACHING_PAGEBITS = 12;
std::vector<int> events;
namespace Common {
u64 AlignDown(u64 a, u64 b) { return a / b * b; }
u64 AlignUp(u64 a, u64 b) { return (a + b - 1) / b * b; }
}
namespace Tegra { std::atomic<bool> g_nx2_ampere{true}; }
namespace VideoCommon {
enum class CacheType { None = 0, BufferCache = 1, TextureCache = 2, QueryCache = 4, ShaderCache = 8, All = 15 };
CacheType operator&(CacheType a, CacheType b) { return CacheType(int(a) & int(b)); }
namespace GpuWrittenPages { int marks = 0; void Mark(u64, u64) { ++marks; } }
}
bool True(VideoCommon::CacheType v) { return int(v) != 0; }
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
        events.push_back(2);
        std::memcpy(guest.data()+a, p, s);
        // Fence at the vulnerable point: after memcpy, before post-copy invalidation.
        for (u64 i = a; i < a+s; ++i)
            if (pending->bits[i] || async->bits[i]) guest[i] = 0x77;
    }
};
struct BufferCopy { u64 src_offset, dst_offset, size; };
struct Buffer {
    std::array<u8, 8192> gpu{};
    u64 cpu_addr_cached = 0, size = 8192, uploaded = 0;
    bool IsInBounds(u64 a, u64 s) { return a >= cpu_addr_cached && a-cpu_addr_cached <= size && s <= size-(a-cpu_addr_cached); }
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
    std::array<Buffer, 3> slot_buffers;
    std::array<BufferId, 2> page_table{1, 1};
    int creations = 0;
    std::vector<BufferCopy> upload_copies;
    bool any_buffer_uploaded = false;
    BufferCache() {
        slot_buffers[2].size = 0;
        device_memory.guest.fill(0x11); slot_buffers[1].gpu.fill(0x11);
        gpu_modified_ranges.Add(512, 512);
        std::fill_n(slot_buffers[1].gpu.begin()+512, 512, 0x77);
        device_memory.pending = &pending_downloads; device_memory.async = &async_downloads;
    }
    bool IsRegionRegistered(u64 a, u64 s) {
        for (size_t i = 1; i < slot_buffers.size(); ++i) {
            auto& b = slot_buffers[i];
            if (b.size && a < b.cpu_addr_cached+b.size && b.cpu_addr_cached < a+s) return true;
        }
        return false;
    }
    bool IsRegionGpuModified(u64 a, u64 s) { return gpu_modified_ranges.Intersects(a, s); }
    BufferId FindBuffer(u64 a, u32 s, bool sparse) {
        assert(!sparse);
        BufferId id = page_table.at(a >> CACHING_PAGEBITS);
        if (id && slot_buffers[id].IsInBounds(a, s)) return id;
        ++creations; // record the create/merge that the production pre-check must prevent
        slot_buffers[2].cpu_addr_cached = a; slot_buffers[2].size = s;
        return 2;
    }
    bool SynchronizeBuffer(Buffer& b, u64 a, u32 s) { return SynchronizeBufferPages(b, a, s); }
    void UploadMemory(Buffer& b, u64, u64, std::span<BufferCopy> copies) {
        for (auto c : copies) b.ImmediateUpload(c.dst_offset,
            std::span<const u8>(device_memory.guest).subspan(c.dst_offset, c.size));
    }
    void WriteMemory(DAddr, u64);
    void WriteMemoryAfterWrite(DAddr, u64);
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
# Main has no dedicated entry: model its existing invalidation with WriteMemory.
post = function(cache, 'void BufferCache<P>::WriteMemoryAfterWrite(', optional=True)
fixture += '\ntemplate<class P>\n' + (post or
    'void BufferCache<P>::WriteMemoryAfterWrite(DAddr a, u64 s) { WriteMemory(a, s); }')
fixture += r'''
struct OtherCache {
    Mutex mutex;
    void WriteMemory(DAddr, u64) {}
    void InvalidateRegion(DAddr, u64) {}
};
void WatchCpuWrite(void*, const char*, DAddr, u64) {}
struct RasterizerVulkan {
    BufferCache<int>& buffer_cache;
    OtherCache texture_cache, query_cache, pipeline_cache, shader_cache;
    void* gpu_memory = nullptr;
    void PrepareRegionWrite(DAddr, u64, VideoCommon::CacheType);
    void InvalidateRegionAfterWrite(DAddr, u64, VideoCommon::CacheType);
    void InvalidateRegion(DAddr a, u64 s, VideoCommon::CacheType which) {
        events.push_back(1);
        if (!False(which & VideoCommon::CacheType::BufferCache)) buffer_cache.WriteMemory(a, s);
    }
};
struct RasterizerOpenGL : RasterizerVulkan {
    void PrepareRegionWrite(DAddr, u64, VideoCommon::CacheType);
    void InvalidateRegionAfterWrite(DAddr, u64, VideoCommon::CacheType);
};
'''
for pre, post, cls in zip(prepare, after_write, ['RasterizerVulkan', 'RasterizerOpenGL']):
    text = pre or f'void {cls}::PrepareRegionWrite(DAddr, u64, VideoCommon::CacheType) {{}}'
    fixture += text.replace('{', '{ events.push_back(3);', 1) + '\n'
    text = post or (f'void {cls}::InvalidateRegionAfterWrite(DAddr a, u64 s, '
                   'VideoCommon::CacheType w) { InvalidateRegion(a, s, w); }')
    fixture += text.replace('{', '{ events.push_back(4);', 1) + '\n'
fixture += r'''
void write_block(BufferCache<int>& cache, bool big, bool unsafe = false, u64 addr = 600, u64 size = 4) {
    auto& memory = cache.device_memory;
    RasterizerVulkan raster{cache}; auto* rasterizer = &raster;
    std::array<u64, 1> page_table{0}, big_page_table_dev{0};
    constexpr int cpu_page_bits = 12;
    auto which = VideoCommon::CacheType::All;
    const std::vector<u8> bytes(size, 0x33);
    const void* src_buffer = bytes.data();
'''
policy = write_block_impl[write_block_impl.index('{')+1:write_block_impl.index('    auto just_advance')]
fixture += policy
fixture += '\n'.join(text + ';' for text in mapped)
fixture += r'''
    events.clear();
    const int marks = VideoCommon::GpuWrittenPages::marks;
    if (big) mapped_big(0, addr, bytes.size()); else mapped_normal(0, addr, bytes.size());
    assert(VideoCommon::GpuWrittenPages::marks == marks+1);
}
int main(int argc, char**) {
    Tegra::g_nx2_ampere.store(std::getenv("UB062_NX2")[0] == '1');
    bool enabled = argc == 2;
    for (bool big : {false, true}) {
        // Both adjacent and overlapping GPU bytes use ONLY the post-copy WriteBlock entry.
        for (u64 addr : {128, 600}) {
            BufferCache<int> cache;
            if (enabled || addr == 600) {
                cache.pending_downloads.Add(addr, 4); cache.async_downloads.Add(addr, 4);
                cache.uncommitted_gpu_modified_ranges.Add(addr, 4);
                cache.committed_gpu_modified_ranges[0].Add(addr, 4);
            }
            cache.pending_downloads.Add(700, 4);
            write_block(cache, big, false, addr);
            assert(cache.device_memory.guest[addr] == 0x33);
            if (enabled) {
                assert((events == std::vector<int>{3, 2, 4}));
                assert(cache.slot_buffers[1].uploaded == 4 && !cache.memory_tracker.cpu);
                assert(cache.slot_buffers[1].gpu[addr] == 0x33);
            } else {
                assert((events == std::vector<int>{1, 2})); // EXACTLY main's off order
                assert(cache.slot_buffers[1].uploaded == 0 && cache.memory_tracker.cpu);
            }
            assert(cache.creations == 0);
            assert(cache.gpu_modified_ranges.bits[700] && cache.slot_buffers[1].gpu[700] == 0x77);
            assert(!cache.gpu_modified_ranges.bits[addr]);
            assert(!cache.pending_downloads.bits[addr] && !cache.async_downloads.bits[addr]);
            assert(cache.pending_downloads.bits[700]);
            assert(!cache.uncommitted_gpu_modified_ranges.bits[addr]);
            assert(!cache.committed_gpu_modified_ranges[0].bits[addr]);
        }
        // Overlap-only (ends inside write), hole (buffer only on next page), none, and large.
        for (int mode : {0, 1, 2, 3}) {
            BufferCache<int> cache;
            u64 addr = 600, size = 4;
            if (mode == 0) cache.slot_buffers[1].size = 602;
            if (mode == 1) { cache.page_table[0] = 0; cache.slot_buffers[1].cpu_addr_cached = 4096; cache.slot_buffers[1].size = 4096; size = 4096; }
            if (mode == 2) { cache.page_table.fill(0); cache.slot_buffers[1].size = 0; }
            if (mode == 3) size = DEVICE_PAGESIZE + 1;
            if (mode == 0 || mode == 1) assert(cache.IsRegionRegistered(addr, size));
            write_block(cache, big, false, addr, size);
            assert(cache.slot_buffers[1].uploaded == 0 && cache.memory_tracker.cpu);
            assert(cache.creations == 0);
        }
        BufferCache<int> boundary;
        write_block(boundary, big, false, 128, DEVICE_PAGESIZE);
        assert(boundary.slot_buffers[1].uploaded == (enabled ? DEVICE_PAGESIZE : 0));
        assert(boundary.creations == 0);
        BufferCache<int> clean;
        clean.gpu_modified_ranges = {}; write_block(clean, big);
        assert(clean.slot_buffers[1].uploaded == 0 && clean.memory_tracker.cpu && clean.creations == 0);
    }
    // Direct invalidations (NCE/Unmap/OnCPUWrite style), including BEFORE the guest copy,
    // never upload, even when enabled. The deferred sync sees the eventual new CPU bytes.
    for (u64 addr : {128, 600}) {
        BufferCache<int> direct;
        direct.WriteMemory(addr, 4);
        assert(direct.slot_buffers[1].uploaded == 0 && direct.memory_tracker.cpu);
        assert(direct.creations == 0 && direct.gpu_modified_ranges.bits[700]);
        std::fill_n(direct.device_memory.guest.begin()+addr, 4, 0x33);
        direct.SynchronizeBufferPages(direct.slot_buffers[1], addr, 4);
        assert(direct.slot_buffers[1].gpu[addr] == 0x33);
        assert(direct.slot_buffers[1].gpu[700] == 0x77);
    }
    // Existing cached writes retain their behavior, independent of the new caller's toggle.
    BufferCache<int> cached;
    cached.CachedWriteMemory(128, 4); assert(cached.slot_buffers[1].uploaded == 4);
    const int marks = VideoCommon::GpuWrittenPages::marks;
    BufferCache<int> unsafe; write_block(unsafe, false, true);
    assert((events == std::vector<int>{2}));
    assert(VideoCommon::GpuWrittenPages::marks == marks+1);
    assert(unsafe.device_memory.guest[600] == 0x33 && unsafe.slot_buffers[1].uploaded == 0);
    BufferCache<int> gl;
    gl.pending_downloads.Add(600, 4);
    RasterizerOpenGL raster{{gl}};
    raster.PrepareRegionWrite(600, 4, VideoCommon::CacheType::None);
    assert(gl.pending_downloads.bits[600]);
    raster.PrepareRegionWrite(600, 4, VideoCommon::CacheType::All);
    assert(!gl.pending_downloads.bits[600] && !gl.mutex.held);
    std::fill_n(gl.device_memory.guest.begin()+600, 4, 0x33);
    raster.InvalidateRegionAfterWrite(600, 4, VideoCommon::CacheType::All);
    assert(gl.slot_buffers[1].uploaded == 4 && gl.slot_buffers[1].gpu[600] == 0x33);

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
                                 ('0', True, False), ('1', False, True),
                                 ('', False, True), ('false', False, True), ('off', False, True)]:
        env = dict(os.environ)
        env.pop('EDEN_NX2_INLINE_PAGE_WRITES', None)
        if forced is not None:
            env['EDEN_NX2_INLINE_PAGE_WRITES'] = forced
        env['UB062_NX2'] = '1' if nx2 else '0'
        subprocess.run([str(out / 'test')] + (['enabled'] if enabled else []), env=env, check=True)

source_checks()
print('Inline page writes: production C++ behavior and source checks PASS')
