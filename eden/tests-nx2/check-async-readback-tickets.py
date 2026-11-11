"""UB-153 (layer 99zzzzs3): a guest read's buffer download waits for the host GPU without the
buffer cache's lock; CPU writes into it go after it lands, invalidated bytes are not overwritten.

RasterizerVulkan::FlushRegion (the GPU-thread side of GPU::OnCPURead and every other synchronous
flush) used to hold buffer_cache.mutex across DownloadMemory -> DownloadBufferMemory ->
runtime.Finish(): every guest core that touched a cached page (OnCPUWrite, GetFlushArea,
invalidations) spun for the whole host GPU round trip. Now:
 - under the lock, DownloadMemoryForRead records and submits the copies (one staging buffer for
   all buffers in the range) and returns the tick; the ranges stay GPU-modified. A throw while
   recording cancels it (SCOPE_EXIT), so no read download stays active;
 - without the lock, WaitReadDownload waits for that tick (BufferCacheRuntime::Wait, no new
   scheduler Wait/Finish site in vk_buffer_cache.cpp; runtimes without Wait never get a tick);
 - under the lock again, FinishReadDownload writes the copied bytes that are still GPU-modified
   (WriteMemory takes invalidated bytes out), then clears the GPU-modified state as
   DownloadBufferMemory did;
 - RasterizerVulkan::OnCPUWrite yields while a waiting read download copies the written bytes
   (BufferCache::ReadDownloadOverlaps): core/memory.cpp stores after OnCPUWrite returns and an
   exclusive store (WriteExclusive) may fail, so the store goes after the landing, as when the
   download held the lock, and a failed one leaves the GPU's bytes;
 - an exception during the wait (device loss, shutdown) cancels the read download: nothing is
   written, the ranges stay GPU-modified, the staging pointer is dropped.

The compiled harness (dedie: g++/clang++ with ASan/UBSan) extracts the PRODUCTION FlushRegion
from vk_rasterizer.cpp and the PRODUCTION BufferCache bodies (WriteMemory, OnCPUWrite,
OnCPUWriteAhead, DownloadMemory, DownloadBufferMemory and, where present, DownloadMemoryForRead,
WaitReadDownload, FinishReadDownload, CancelReadDownload, ReadDownloadOverlaps and the ReadDownload
state) from buffer_cache.h / buffer_cache_base.h, with EDEN_NX2_PS5_PROTO defined, and runs them
against a fake runtime. Its copies complete only when Wait/Finish is given their tick or a later
one, and Wait must be given the tick the copies were recorded at. Its host GPU wait plays a second
guest core:
 - a write through the OnCPUWrite path (handler, then bytes), an exclusive write whose
   compare-and-swap fails (handler, no store) and a write through the invalidation path (bytes,
   then WriteMemory) happen during the wait. A writer blocks until FlushRegion returns when the
   lock is held (the spin lock) or when ReadDownloadOverlaps says so (OnCPUWrite's yield loop);
 - no host GPU wait may run with buffer_cache.mutex held; the stored writes survive; the failed
   exclusive write's bytes hold the GPU's; every other downloaded byte equals the GPU's (the
   synchronous flush's result), across two buffers; nothing stays GPU-modified;
 - a wait that throws leaves guest memory untouched and the range GPU-modified; the staging
   allocation is then recycled (freed) and a second flush must not touch it (ASan);
 - a CopyBuffer that throws while recording leaves the range GPU-modified, and the next flush
   still records and waits without the lock (no read download left active).
Negative control: on main 94ddc02 (no 99zzzzs3) FlushRegion waits in runtime.Finish() with the
lock held, the invalidation-path write is overwritten by the late landing and a cancelled range is
no longer GPU-modified: the harness fails on behavior. --source-only on main fails the lock-scope
analysis (a host GPU wait reachable from a call made under buffer_cache.mutex in FlushRegion).

Usage: check-async-readback-tickets.py [--source-only] [SOURCE_DIR]   SOURCE_DIR contains src/
(default: this checkout's prepared build cache).
"""
from pathlib import Path
import os
import platform
import re
import shutil
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


def block(text, start):
    """Text from start to the brace that closes the first '{' at or after it."""
    open_at = text.index('{', start)
    depth = 0
    for i in range(open_at, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise AssertionError('unbalanced braces')


MEMBER = r'template <class P>\n[^\n]*?\bBufferCache<P>::'


def member(text, name, args=''):
    """The out-of-line definition 'template <class P>\\nRET BufferCache<P>::name(args...) {...}' of
    the first overload whose parameters start with args, or None."""
    m = re.search(MEMBER + name + r'\(' + re.escape(args), text)
    return block(text, m.start()) + '\n' if m else None


def overloads(text, name):
    """Every out-of-line definition of BufferCache::name, joined."""
    return ''.join(block(text, m.start()) + '\n' for m in re.finditer(MEMBER + name + r'\(', text))


rasterizer = (vc / 'renderer_vulkan/vk_rasterizer.cpp').read_text()
cache = (vc / 'buffer_cache/buffer_cache.h').read_text()
cache_base = (vc / 'buffer_cache/buffer_cache_base.h').read_text()
flush_at = rasterizer.index('void RasterizerVulkan::FlushRegion(DAddr addr, u64 size, VideoCommon::CacheType which) {')
flush = block(rasterizer, flush_at) + '\n'
buffer_branch = block(flush, flush.index('if ((True(which & VideoCommon::CacheType::BufferCache))) {'))

# --- Lock-scope analysis of FlushRegion's buffer branch ------------------------------------
LOCK = 'std::scoped_lock lock{buffer_cache.mutex};'
calls = []  # (name, locked)
depth, lock_depths = 0, []
i = 0
while i < len(buffer_branch):
    c = buffer_branch[i]
    if buffer_branch.startswith(LOCK, i):
        lock_depths.append(depth)
        i += len(LOCK)
        continue
    m = re.match(r'buffer_cache\.(\w+)\(', buffer_branch[i:])
    if m:
        calls.append((m.group(1), bool(lock_depths)))
        i += m.end()
        continue
    if c == '{':
        depth += 1
    elif c == '}':
        depth -= 1
        while lock_depths and lock_depths[-1] > depth:
            lock_depths.pop()
    i += 1

definitions = {n: overloads(cache, n) for n in re.findall(MEMBER + r'(\w+)\(', cache)}
HOST_WAIT = re.compile(r'runtime\.(Finish|Wait)\(')


def wait_chain(name, seen=()):
    """A call chain from BufferCache::name (any overload) to a host GPU wait, following member
    calls."""
    body = definitions.get(name)
    if body is None or name in seen:
        return None
    if (m := HOST_WAIT.search(body)):
        return [name, f'runtime.{m.group(1)}()']
    for callee in dict.fromkeys(re.findall(r'(?<![\w.>])(\w+)\(', body)):
        if callee in definitions and callee != name:
            chain = wait_chain(callee, seen + (name,))
            if chain:
                return [name] + chain
    return None


def source_checks():
    """The split around the wait, the recording path and the CPU writes into the copies."""
    if 'DownloadMemoryForRead' not in [n for n, _ in calls]:
        for name, locked in calls:
            chain = wait_chain(name) if locked else None
            assert not chain, ('FlushRegion waits for the host GPU holding buffer_cache.mutex: '
                               + ' -> '.join(['FlushRegion'] + chain))
        raise AssertionError('FlushRegion has no read download split around the host GPU wait')

    locked = {n: l for n, l in calls}
    assert locked.get('DownloadMemoryForRead') is True, 'DownloadMemoryForRead must run under the lock'
    assert locked.get('WaitReadDownload') is False, 'WaitReadDownload must run without the lock'
    assert locked.get('FinishReadDownload') is True and locked.get('CancelReadDownload') is True
    assert [n for n, _ in calls] == ['DownloadMemoryForRead', 'CancelReadDownload', 'WaitReadDownload',
                                     'FinishReadDownload'], calls
    assert flush.count(LOCK) == 3 and 'SCOPE_EXIT' in buffer_branch
    for name, is_locked in calls:
        if is_locked and name != 'DownloadMemoryForRead':
            assert not wait_chain(name), f'{name} waits for the host GPU under the lock'

    for name in ('DownloadMemoryForRead', 'WaitReadDownload', 'FinishReadDownload', 'CancelReadDownload'):
        assert definitions.get(name), f'BufferCache::{name} missing'
    record = definitions['DownloadMemoryForRead']
    record_path = block(record, record.index('if (!read_download.active && !IsParameterReadback(device_addr, size)) {'))
    assert not HOST_WAIT.search(record_path), 'the recording path must not wait for the host GPU'
    assert 'DownloadMemory(' not in record_path and 'DownloadBufferMemory(' not in record_path
    assert 'return runtime.CurrentTick();' in record_path
    guard = record_path.index('SCOPE_EXIT {')
    assert record_path.index('read_download.active = true;') < guard < record_path.index('small_vector'), \
        'the cancel guard must be installed before anything that can throw'
    assert 'if (!recorded) {\n                    CancelReadDownload();' in record_path[guard:]
    assert record_path.index('recorded = true;\n            return runtime.CurrentTick();') > \
        record_path.index('runtime.CopyBuffer('), 'recorded only once every copy is recorded'
    assert 'gpu_modified_ranges.Subtract' not in record_path, 'ranges must stay GPU-modified until landed'
    assert 'ClearDownload(range_addr, range_size);' in record_path
    assert re.search(r'#ifdef EDEN_NX2_PS5_PROTO\n    if constexpr \(USE_MEMORY_MAPS && requires', record)
    assert definitions['WaitReadDownload'].count('runtime.Wait(tick);') == 1
    finish = definitions['FinishReadDownload']
    land = finish.index('gpu_modified_ranges.ForEachInRange(copy.device_addr, copy.size')
    assert land < finish.index('device_memory.WriteBlockUnsafe') < finish.index('gpu_modified_ranges.Subtract'), \
        'only bytes still GPU-modified land, before their GPU-modified state is cleared'
    # A CPU write into the copies waits until they land (RasterizerVulkan::OnCPUWrite): the
    # caller stores after it returns and an exclusive store may fail.
    on_write = block(rasterizer, rasterizer.index('bool RasterizerVulkan::OnCPUWrite(DAddr addr, u64 size) {'))
    # The wait comes before the block prepare-vulkan-port.py replaces (from DEBUG_ASSERT on), which
    # stays verbatim, so the PS5 adaptation keeps it.
    wait = block(on_write, on_write.index('while (buffer_cache.ReadDownloadPending()) {'))
    assert wait.index('std::scoped_lock lock{buffer_cache.mutex};') < \
        wait.index('if (!buffer_cache.ReadDownloadOverlaps(addr, size)) {\n                break;') < \
        wait.index('std::this_thread::yield();'), 'OnCPUWrite must wait for an overlapping read download'
    assert on_write.index(wait) < on_write.index(
        '    DEBUG_ASSERT(addr != 0 || size != 0);\n    {\n        std::scoped_lock lock{buffer_cache.mutex};\n'
        '        if (buffer_cache.OnCPUWrite(addr, size)) {\n            return true;\n        }\n    }\n')
    assert on_write.count('buffer_cache.OnCPUWrite(') == 1 and '#include <thread>' in rasterizer
    overlaps = block(cache_base, cache_base.index('[[nodiscard]] bool ReadDownloadOverlaps(DAddr device_addr, u64 size) const {'))
    assert 'read_download.active &&' in overlaps and 'read_download.copies' in overlaps
    assert 'return read_download.active.load(std::memory_order_acquire);' in cache_base
    assert 'NoteReadDownloadWrite' not in cache + cache_base and 'cpu_written' not in cache + cache_base
    # prepare-vulkan-port.py pins two scheduler Wait/Finish sites in vk_buffer_cache.cpp.
    vk_buffer_cache = (vc / 'renderer_vulkan/vk_buffer_cache.cpp').read_text()
    assert len(re.findall(r'(?m)^( +)(scheduler\.(?:Wait|Finish)\([^\n]*\);)$', vk_buffer_cache)) == 2


if source_only:
    source_checks()
    print('async-readback-tickets source checks passed')
    sys.exit(0)

# --- Compiled harness ------------------------------------------------------------------------
names = ['WriteMemory', 'OnCPUWrite', 'OnCPUWriteAhead', 'DownloadMemory', 'DownloadBufferMemory',
         'DownloadMemoryForRead', 'WaitReadDownload', 'FinishReadDownload', 'CancelReadDownload']
bodies, declarations = [], []
for name in names:
    body = member(cache, name, 'Buffer& buffer, DAddr' if name == 'DownloadBufferMemory' else '')
    if body is None:
        continue
    bodies.append(body)
    signature = re.search(r'template <class P>\n(.*?)\bBufferCache<P>::' + name + r'(\([^)]*\))', body)
    declarations.append(f'    {signature.group(1)}{name}{signature.group(2)};')
state = ''
if 'struct ReadDownload {' in cache_base:
    state = block(cache_base, cache_base.index('    struct ReadDownload {')) + ';\n'
    state += '    ReadDownload read_download;\n'
    for head in ('    [[nodiscard]] bool ReadDownloadPending(', '    [[nodiscard]] bool ReadDownloadOverlaps('):
        if (at := cache_base.find(head)) >= 0:
            state += block(cache_base, at) + '\n'

harness = r'''
#include <algorithm>
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <span>
#include <stdexcept>
#include <utility>
#include <vector>
#define EDEN_NX2_PS5_PROTO 1
using u8 = std::uint8_t; using u32 = std::uint32_t; using u64 = std::uint64_t;
using DAddr = u64; using VAddr = u64;
namespace boost::container { template <class T, std::size_t N> using small_vector = std::vector<T>; }
template <class F> struct ScopeExitT { F f; ~ScopeExitT() { f(); } };
struct ScopeExitHelper { template <class F> ScopeExitT<F> operator+(F&& f) { return {std::forward<F>(f)}; } };
#define SCOPE_CAT2(a, b) a##b
#define SCOPE_CAT(a, b) SCOPE_CAT2(a, b)
#define SCOPE_EXIT auto SCOPE_CAT(scope_exit_, __COUNTER__) = ScopeExitHelper{} + [&]()
namespace Core { constexpr std::size_t DEVICE_PAGESIZE = 4096; }
namespace Common {
template <class T> constexpr T AlignUp(T v, std::size_t a) { return T((v + a - 1) / a * a); }
template <class T> constexpr T AlignDown(T v, std::size_t a) { return T(v / a * a); }
/// Disjoint sorted [begin, end) intervals, as boost::icl::interval_set joins them.
template <class A> class RangeSet {
public:
    void Add(A a, std::size_t s) {
        if (!s) return;
        A b = a, e = a + s;
        for (auto it = r.begin(); it != r.end();) {
            if (it->second >= b && it->first <= e) { b = std::min(b, it->first); e = std::max(e, it->second); it = r.erase(it); }
            else ++it;
        }
        r[b] = e;
    }
    void Subtract(A a, std::size_t s) {
        if (!s) return;
        const A b = a, e = a + s;
        std::map<A, A> out;
        for (auto [x, y] : r) {
            if (y <= b || x >= e) { out[x] = y; continue; }
            if (x < b) out[x] = b;
            if (y > e) out[e] = y;
        }
        r = out;
    }
    void Clear() { r.clear(); }
    template <class F> void ForEach(F&& f) const { for (auto [x, y] : r) f(x, y); }
    template <class F> void ForEachInRange(A a, std::size_t s, F&& f) const {
        const A b = a, e = a + s;
        for (auto [x, y] : r) if (x < e && y > b) f(std::max(x, b), std::min(y, e));
    }
    bool Intersects(A a, std::size_t s) const { bool hit = false; ForEachInRange(a, s, [&](A, A) { hit = true; }); return hit; }
    std::map<A, A> r;
};
}
namespace VideoCommon {
using Core::DEVICE_PAGESIZE;
struct BufferCopy { u64 src_offset; u64 dst_offset; std::size_t size; };
struct BufferId { u32 index; bool operator==(const BufferId&) const = default; };
inline bool IsParameterReadback(u64, std::size_t) { return false; }
inline std::size_t ReadbackWindowBytes() { return 65536; }
struct WindowView { DAddr address; std::vector<u8> bytes; };
template <class A> struct ReadbackWindowCache {
    static constexpr std::size_t WindowBytes = 65536;
    const WindowView* Find(A, std::size_t, bool = true) { return nullptr; }
    bool Store(A, std::span<u8>) { return false; }
};
template <class A> struct ReadbackRangeSet : Common::RangeSet<A> {
    ReadbackWindowCache<A>& ReadbackCache() { return cache; }
    ReadbackWindowCache<A> cache;
};
template <class Copies, class Counts> void DropPendingFenceCopies(u64, u64, Copies&, Counts&) {}

constexpr u64 Page = 4096;
struct Tracker {
    std::map<u64, bool> gpu; // page -> GPU-modified
    void MarkRegionAsGpuModified(u64 a, u64 s) { for (u64 p = a / Page; p < (a + s + Page - 1) / Page; ++p) gpu[p] = true; }
    void UnmarkRegionAsGpuModified(u64 a, u64 s) { for (u64 p = a / Page; p < (a + s + Page - 1) / Page; ++p) gpu.erase(p); }
    void MarkRegionAsCpuModified(u64 a, u64 s) { UnmarkRegionAsGpuModified(a, s); }
    bool IsRegionGpuModified(u64 a, u64 s) { for (u64 p = a / Page; p < (a + s + Page - 1) / Page; ++p) if (gpu.count(p)) return true; return false; }
    // WordManager::ForEachModifiedRange: page-granular runs of GPU-modified pages.
    template <class F> void ForEachDownloadRange(u64 a, u64 s, bool clear, F&& f) {
        u64 run = 0, len = 0;
        for (u64 p = a / Page; p < (a + s + Page - 1) / Page; ++p) {
            if (gpu.count(p)) { if (!len) run = p; ++len; if (clear) gpu.erase(p); continue; }
            if (len) { f(run * Page, len * Page); len = 0; }
        }
        if (len) f(run * Page, len * Page);
    }
};
struct DeviceMemory {
    std::map<u64, u8> bytes;
    u8 At(u64 a) const { auto it = bytes.find(a); return it == bytes.end() ? 0x11 : it->second; }
    void WriteBlockUnsafe(u64 a, const void* p, std::size_t s) { for (std::size_t i = 0; i < s; ++i) bytes[a + i] = static_cast<const u8*>(p)[i]; }
};
struct Buffer {
    DAddr cpu; u64 size; std::vector<u8> gpu;
    DAddr CpuAddr() const { return cpu; }
    u64 SizeBytes() const { return size; }
    void MarkUsage(u64, u64) {}
    void ImmediateDownload(u64, std::span<u8>) { std::abort(); }
};
struct Mutex {
    int depth = 0;
    void lock() { ++depth; }
    void unlock() { --depth; }
};
struct Staging { int buffer; u64 offset; std::span<u8> mapped_span; };
struct PendingCopy { Buffer* src; u8* dst; BufferCopy copy; u64 tick; };
struct Runtime {
    Mutex* mutex{};
    u64 tick = 1;
    int locked_waits = 0, waits = 0, early_waits = 0;
    u64 last_copy_tick = 0, last_wait_tick = 0;
    bool throw_in_wait = false, throw_in_copy = false;
    std::vector<std::unique_ptr<std::vector<u8>>> stagings;
    std::vector<PendingCopy> pending;
    std::function<void()> during_wait;
    Staging DownloadStagingBuffer(std::size_t size, bool = false) {
        stagings.push_back(std::make_unique<std::vector<u8>>(size + 64, u8{0xEE}));
        // As StagingBufferRef: offset is where the allocation starts in the buffer, mapped_span its bytes.
        return Staging{int(stagings.size()), 64, std::span<u8>(stagings.back()->data() + 64, size)};
    }
    void CopyBuffer(int dst, Buffer& src, std::span<const BufferCopy> copies, bool) {
        if (throw_in_copy) throw std::bad_alloc();
        for (const auto& c : copies) pending.push_back({&src, stagings[dst - 1]->data(), c, tick});
        last_copy_tick = tick;
    }
    // Scheduler::Wait: submits the current tick if asked for it, then waits for that tick only.
    void HostWait(u64 wanted) {
        ++waits;
        last_wait_tick = wanted;
        if (mutex->depth > 0) ++locked_waits;
        std::erase_if(pending, [&](const PendingCopy& p) {
            if (p.tick > wanted) return false;
            std::memcpy(p.dst + p.copy.dst_offset, p.src->gpu.data() + p.copy.src_offset, p.copy.size);
            return true;
        });
        if (!pending.empty()) ++early_waits; // copies recorded before the wait are still running
        if (wanted >= tick) ++tick;
        if (during_wait) { auto f = std::move(during_wait); during_wait = nullptr; f(); }
        if (throw_in_wait) throw std::runtime_error("device lost during the wait");
    }
    u64 CurrentTick() { return tick; }
    void Wait(u64 wanted) { HostWait(wanted); }
    void Finish() { HostWait(tick); }
    void Recycle() { for (auto& s : stagings) { s.reset(); } }
};
struct FakeParams { static constexpr bool USE_MEMORY_MAPS = true; };
template <class T>
struct BufferCache {
    static constexpr bool USE_MEMORY_MAPS = T::USE_MEMORY_MAPS;
    Mutex mutex;
    Runtime runtime;
    Tracker memory_tracker;
    DeviceMemory device_memory;
    ReadbackRangeSet<DAddr> gpu_modified_ranges;
    std::vector<Buffer> buffers;
    int pending_downloads{}, async_downloads{};
    struct Slots { std::vector<Buffer>* v; Buffer& operator[](BufferId id) { return (*v)[id.index]; } } slot_buffers{&buffers};
    BufferCache() { runtime.mutex = &mutex; }
    bool IsRegionGpuModified(DAddr a, u64 s) { return gpu_modified_ranges.Intersects(a, s); }
    bool IsRegionRegistered(DAddr, u64) { return true; }
    void ClearDownload(DAddr, u64) {}
    std::span<u8> ImmediateBuffer(std::size_t) { std::abort(); }
    template <class F> void ForEachBufferInRange(DAddr a, u64 s, F&& f) {
        for (u32 i = 0; i < buffers.size(); ++i)
            if (buffers[i].cpu < a + s && a < buffers[i].cpu + buffers[i].size) f(BufferId{i}, buffers[i]);
    }
    // GPU work wrote these bytes (MarkWrittenBuffer).
    void MarkWritten(DAddr a, u64 s) { memory_tracker.MarkRegionAsGpuModified(a, s); gpu_modified_ranges.Add(a, s); }
''' + '\n'.join(declarations) + '\n' + state + r'''
};
''' + '\n'.join(bodies) + r'''
enum class CacheType : u32 { None = 0, TextureCache = 1, QueryCache = 2, BufferCache = 4, All = 7 };
constexpr CacheType operator&(CacheType a, CacheType b) { return CacheType(u32(a) & u32(b)); }
constexpr bool True(CacheType c) { return u32(c) != 0; }
namespace NativeWaitProfile { enum class Kind { FlushRegion }; struct Scope { Scope(Kind, void*, u64 = 0) {} }; }
} // namespace VideoCommon
namespace Vulkan {
struct FakeTextureCache { std::mutex mutex; void DownloadMemory(DAddr, u64) {} };
struct FakeQueryCache { void FlushRegion(DAddr, u64) {} };
struct RasterizerVulkan {
    VideoCommon::BufferCache<VideoCommon::FakeParams> buffer_cache;
    FakeTextureCache texture_cache;
    FakeQueryCache query_cache;
    void FlushRegion(DAddr addr, u64 size, VideoCommon::CacheType which);
};
''' + flush + r'''
} // namespace Vulkan
static int fails = 0;
#define EXPECT(c) do { if (!(c)) { std::fprintf(stderr, "line %d: %s\n", __LINE__, #c); ++fails; } } while (0)
using VideoCommon::CacheType;
constexpr u64 base = 0x100000;
static u8 GpuByte(u64 a) { return u8(0xA0 + (a & 0x0f)); }
static void Setup(Vulkan::RasterizerVulkan& r) {
    auto& c = r.buffer_cache;
    c.buffers = {{base, 0x4000, {}}, {base + 0x4000, 0x2000, {}}};
    for (auto& b : c.buffers) { b.gpu.resize(b.size); for (u64 i = 0; i < b.size; ++i) b.gpu[i] = GpuByte(b.cpu + i); }
    c.MarkWritten(base + 0x100, 0x2000);   // pages 0-2 of the first buffer
    c.MarkWritten(base + 0x3f00, 0x200);   // across both buffers
}
static bool StillGpuModified(Vulkan::RasterizerVulkan& r, u64 a, u64 s) { return r.buffer_cache.gpu_modified_ranges.Intersects(a, s); }
// Whether a guest core writing these bytes is held until FlushRegion returns: by the spin lock
// (held across the wait), or by RasterizerVulkan::OnCPUWrite's yield loop (ReadDownloadPending,
// then ReadDownloadOverlaps under the lock) before it calls BufferCache::OnCPUWrite.
template <class Cache>
static bool WriterWaits(Cache& c, u64 a, u64 s) {
    if (c.mutex.depth > 0) return true;
    if constexpr (requires { c.ReadDownloadOverlaps(a, s); }) {
        if (!c.ReadDownloadPending()) return false;
        std::scoped_lock lock{c.mutex};
        return c.ReadDownloadOverlaps(a, s);
    }
    return false;
}
int main() {
    { // A read download alone: the synchronous flush's bytes and state.
        Vulkan::RasterizerVulkan r; Setup(r); auto& c = r.buffer_cache;
        r.FlushRegion(base, 0x6000, CacheType::BufferCache);
        EXPECT(c.runtime.waits >= 1);
        EXPECT(c.runtime.locked_waits == 0); // main: runtime.Finish() under buffer_cache.mutex
        EXPECT(c.runtime.early_waits == 0 && c.runtime.pending.empty());
        EXPECT(c.runtime.last_wait_tick == c.runtime.last_copy_tick); // the tick returned at record
        for (u64 a = base; a < base + 0x6000; ++a) {
            const bool written = (a >= base + 0x100 && a < base + 0x2100) || (a >= base + 0x3f00 && a < base + 0x4100);
            if (c.device_memory.At(a) != (written ? GpuByte(a) : 0x11)) { std::fprintf(stderr, "byte %llx\n", (unsigned long long)a); ++fails; break; }
        }
        EXPECT(!StillGpuModified(r, base, 0x6000));
        EXPECT(!c.memory_tracker.IsRegionGpuModified(base, 0x6000));
        EXPECT(c.mutex.depth == 0);
    }
    { // A second guest core writes during the host GPU wait.
        Vulkan::RasterizerVulkan r; Setup(r); auto& c = r.buffer_cache;
        std::vector<std::function<void()>> after; // what a blocked writer does once the lock is free
        const u8 x[4] = {0x5A, 0x5A, 0x5A, 0x5A};
        const u8 y[8] = {0x6B, 0x6B, 0x6B, 0x6B, 0x6B, 0x6B, 0x6B, 0x6B};
        c.runtime.during_wait = [&] {
            // OnCPUWrite path (core/memory.cpp HandleRasterizerWrite): handler, then the bytes.
            auto on_cpu_write = [&] {
                std::scoped_lock lock{c.mutex};
                (void)c.OnCPUWrite(base + 0x200, 4);
            };
            auto write_x = [&] { c.device_memory.WriteBlockUnsafe(base + 0x200, x, 4); };
            // Invalidation path (ThreadManager::InvalidateRegion): the bytes, then WriteMemory.
            c.device_memory.WriteBlockUnsafe(base + 0x1800, y, 8);
            auto invalidate_y = [&] { std::scoped_lock lock{c.mutex}; c.WriteMemory(base + 0x1800, 8); };
            // WriteExclusive whose compare-and-swap fails: the handler runs, nothing is stored.
            auto failed_cas = [&] { std::scoped_lock lock{c.mutex}; (void)c.OnCPUWrite(base + 0x300, 4); };
            if (WriterWaits(c, base + 0x200, 4)) after.push_back([=] { on_cpu_write(); write_x(); });
            else { on_cpu_write(); write_x(); }
            if (WriterWaits(c, base + 0x300, 4)) after.push_back(failed_cas);
            else failed_cas();
            if (c.mutex.depth > 0) after.push_back(invalidate_y); // the spin lock
            else invalidate_y();
        };
        r.FlushRegion(base, 0x6000, CacheType::BufferCache);
        for (auto& f : after) f();
        { std::scoped_lock lock{c.mutex}; c.WriteMemory(base + 0x200, 4); } // the collected write applied
        EXPECT(c.runtime.locked_waits == 0);
        for (u64 i = 0; i < 4; ++i) EXPECT(c.device_memory.At(base + 0x200 + i) == 0x5A);
        for (u64 i = 0; i < 8; ++i) EXPECT(c.device_memory.At(base + 0x1800 + i) == 0x6B); // main: clobbered
        EXPECT(c.device_memory.At(base + 0x1ff) == GpuByte(base + 0x1ff));
        EXPECT(c.device_memory.At(base + 0x204) == GpuByte(base + 0x204));
        for (u64 i = 0; i < 4; ++i) EXPECT(c.device_memory.At(base + 0x300 + i) == GpuByte(base + 0x300 + i));
        EXPECT(c.runtime.early_waits == 0 && c.runtime.pending.empty());
        EXPECT(c.device_memory.At(base + 0x17ff) == GpuByte(base + 0x17ff));
        EXPECT(c.device_memory.At(base + 0x1808) == GpuByte(base + 0x1808));
        EXPECT(c.device_memory.At(base + 0x40ff) == GpuByte(base + 0x40ff));
        EXPECT(!StillGpuModified(r, base, 0x6000));
    }
    { // The wait fails (device lost, shutdown): nothing lands, the range stays GPU-modified.
        Vulkan::RasterizerVulkan r; Setup(r); auto& c = r.buffer_cache;
        c.runtime.throw_in_wait = true;
        bool threw = false;
        try { r.FlushRegion(base, 0x6000, CacheType::BufferCache); } catch (const std::runtime_error&) { threw = true; }
        EXPECT(threw);
        EXPECT(c.mutex.depth == 0);
        for (u64 a = base + 0x100; a < base + 0x2100; a += 0x100) EXPECT(c.device_memory.At(a) == 0x11);
        EXPECT(StillGpuModified(r, base + 0x100, 0x2000)); // main: cleared before the wait, never written
        EXPECT(c.memory_tracker.IsRegionGpuModified(base + 0x100, 0x2000));
        c.runtime.throw_in_wait = false;
        c.runtime.Recycle(); // the pool reuses the staging memory: nothing may still point at it
        r.FlushRegion(base, 0x6000, CacheType::BufferCache);
        EXPECT(c.device_memory.At(base + 0x100) == GpuByte(base + 0x100));
        EXPECT(c.device_memory.At(base + 0x4000) == GpuByte(base + 0x4000));
        EXPECT(!StillGpuModified(r, base, 0x6000));
    }
    { // Recording throws (allocation, CopyBuffer): no read download stays active.
        Vulkan::RasterizerVulkan r; Setup(r); auto& c = r.buffer_cache;
        c.runtime.throw_in_copy = true;
        bool threw = false;
        try { r.FlushRegion(base, 0x6000, CacheType::BufferCache); } catch (const std::bad_alloc&) { threw = true; }
        EXPECT(threw);
        EXPECT(c.mutex.depth == 0);
        EXPECT(c.device_memory.At(base + 0x100) == 0x11);
        EXPECT(StillGpuModified(r, base + 0x100, 0x2000) && StillGpuModified(r, base + 0x3f00, 0x200));
        c.runtime.throw_in_copy = false;
        r.FlushRegion(base, 0x6000, CacheType::BufferCache); // still a read download, not DownloadMemory
        EXPECT(c.runtime.locked_waits == 0);
        EXPECT(c.device_memory.At(base + 0x100) == GpuByte(base + 0x100));
        EXPECT(c.device_memory.At(base + 0x40ff) == GpuByte(base + 0x40ff));
        EXPECT(!StillGpuModified(r, base, 0x6000));
    }
    return fails ? 3 : 0;
}
'''
out = root / 'build/nx2-tests/async-readback-tickets'
out.mkdir(parents=True, exist_ok=True)
cpp = out / 'harness.cpp'
cpp.write_text(harness)
compiler = os.environ.get('CXX') or next((c for c in ('clang++-18', 'clang++', 'g++') if shutil.which(c)), None)
assert compiler, 'no C++ compiler'
subprocess.run([compiler, '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined', str(cpp),
                '-o', str(out / 'h')], check=True)
subprocess.run([str(out / 'h')], check=True)
source_checks()
print('async-readback-tickets checks passed')
