"""UB-042: batched Vulkan submissions on the split GPU thread, with their correctness companions.

Compiles the production GpuSplit (gpu_split.cpp/.h from SOURCE_DIR, desktop and
EDEN_NX2_PS5_PROTO builds, split-observer-stubs for its dependencies) with production
Scheduler::Flush / DeferFlush / FlushDeferred / WaitSubmitted, InnerFence::Queue / Wait,
RasterizerVulkan::FlushCommands and its SetSubmitHook statement, FenceManager::SubmitDeferredWork,
the WaitPendingFences statements between SignalFence and the wait, Maxwell3D::FrontDmaRead and the
Maxwell3D / KeplerCompute handback (first statement of ConsumeSinkImpl / CallMethod /
CallMultiMethod, ReleaseFront) into a recording fixture. SubmitExecution aborts if two threads are
in it at once and records which thread submitted each tick; the fake GPU completes a tick when it is
submitted. On the real back thread it checks:
- fences and FlushCommands inside the window make no submission, and Drain returns only after the
  back submitted them together; nothing is submitted after Drain returns (back_quiet);
- EDEN_NX2_FENCE_FLUSH_US=0 submits at every fence and FlushCommands; the default window defers;
- a deferred fence is submitted before the back sleeps, without anyone asking;
- InnerFence::Wait on another thread does not return before its tick is submitted while the back
  runs a 2.5 s entry (55274de: no 2 s give-up), and never submits itself;
- WaitPendingFences on the back does not deadlock behind its own deferred flush (79f284e part);
- FrontDmaRead's buffer/query flush runs on the back, not the front (9960298);
- an engine method off the back hands the macros and shadow RAM back, before ConsumeSinkImpl
  applies sunk writes, and not on the back (d1de145);
- stopping the split leaves nothing deferred.
Main compiles the same fixture (absent pieces fall back to main's code: no hook, no deferral)
and FAILS by behavior: every fence and FlushCommands still submits inside the entry.

Linux/dedie: python3 eden/tests-nx2/check-batched-vulkan-submissions.py [SOURCE_DIR]
Source checks only (no compiler): add --source-only. SOURCE_DIR contains src/; default is the
prepared build cache.
Negative control: run this SAME script against main prepared WITHOUT 99zzzzc (the 115 earlier
layers, af9e7e3). The C++ fixture must exit 1 with "UB-042 FAIL: fences and FlushCommands in one
window each submitted" and --source-only must fail on the missing DeferFlush.
"""
from pathlib import Path
import os
import platform
import shutil
import subprocess
import sys
import tempfile

args = [a for a in sys.argv[1:] if not a.startswith('--')]
source_only = '--source-only' in sys.argv[1:]
root = Path(__file__).resolve().parents[1]
source = Path(args[0]).resolve() if args else Path(
    (root / '.local/headless-cache').read_text().strip()) / 'source'
src = source / 'src/video_core'
split_cpp = (src / 'gpu_split.cpp').read_text()
split_h = (src / 'gpu_split.h').read_text()
scheduler_cpp = (src / 'renderer_vulkan/vk_scheduler.cpp').read_text()
scheduler_h = (src / 'renderer_vulkan/vk_scheduler.h').read_text()
fence_cpp = (src / 'renderer_vulkan/vk_fence_manager.cpp').read_text()
fence_h = (src / 'fence_manager.h').read_text()
raster_cpp = (src / 'renderer_vulkan/vk_rasterizer.cpp').read_text()
maxwell_cpp = (src / 'engines/maxwell_3d.cpp').read_text()
kepler_cpp = (src / 'engines/kepler_compute.cpp').read_text()
dma_cpp = (src / 'dma_pusher.cpp').read_text()


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


def body(fn):
    return fn[fn.index('{') + 1:fn.rindex('}')]


HANDBACK = 'if (front_macros && !VideoCommon::GpuSplit::OnBackThread())'


def prologue(fn):
    """The handback block when it is the function's first statement (comments may precede)."""
    text = body(fn)
    at = text.find(HANDBACK)
    if at < 0 or any(line.strip() and not line.strip().startswith('//')
                     for line in text[:at].splitlines()):
        return ''
    return function(text[at:], HANDBACK)


fence_queue = function(fence_cpp, 'void InnerFence::Queue()')
fence_wait = function(fence_cpp, 'void InnerFence::Wait()')
submit_deferred = function(fence_cpp, 'void FenceManager::SubmitDeferredWork()', optional=True)
flush = function(scheduler_cpp, 'u64 Scheduler::Flush(')
defer = function(scheduler_cpp, 'bool Scheduler::DeferFlush()', optional=True)
flush_deferred = function(scheduler_cpp, 'void Scheduler::FlushDeferred()', optional=True)
wait_submitted = function(scheduler_cpp, 'bool Scheduler::WaitSubmitted(', optional=True)
flush_commands = function(raster_cpp, 'void RasterizerVulkan::FlushCommands()')
pending = function(fence_h, 'void WaitPendingFences(')
after_signal = pending.split('SignalFence(std::move(func));', 1)[1].split(
    'std::unique_lock lk(wait_mutex);', 1)[0]
hook_at = raster_cpp.find('VideoCommon::GpuSplit::Get().SetSubmitHook(\n')
hook_install = raster_cpp[hook_at:raster_cpp.index(';\n', hook_at) + 1] if hook_at >= 0 else ''
front_dma = function(maxwell_cpp, 'void Maxwell3D::FrontDmaRead(')
maxwell_release = function(maxwell_cpp, 'void Maxwell3D::ReleaseFront()', optional=True)
kepler_release = function(kepler_cpp, 'void KeplerCompute::ReleaseFront()', optional=True)
maxwell_sink = prologue(function(maxwell_cpp, 'void Maxwell3D::ConsumeSinkImpl('))
maxwell_call = prologue(function(maxwell_cpp, 'void Maxwell3D::CallMethod('))
maxwell_multi = prologue(function(maxwell_cpp, 'void Maxwell3D::CallMultiMethod('))
kepler_call = prologue(function(kepler_cpp, 'void KeplerCompute::CallMethod('))


def source_checks():
    # Scheduler: the window, its env override and who may defer.
    assert defer and flush_deferred and wait_submitted, 'DeferFlush/FlushDeferred/WaitSubmitted'
    assert 'std::getenv("EDEN_NX2_FENCE_FLUSH_US")' in defer and 's64{500}' in defer
    assert 'interval_us <= 0 || !VideoCommon::GpuSplit::OnBackThread()' in defer
    assert 'flush_pending = true;' in defer and 'flush_pending = false;' in flush
    assert 'return tick < master_semaphore->CurrentTick();' in scheduler_h
    # 55274de: the only early exit is a stopped back; no deadline.
    assert 'deadline' not in wait_submitted and 'return false' not in wait_submitted
    assert 'if (!split.BackRunning()) {\n            return IsSubmitted(tick);' in wait_submitted
    assert 'split.RequestSubmitHook();' in wait_submitted
    # Fences, FlushCommands, the fencing thread's wait.
    assert 'if (!scheduler.DeferFlush()) {\n        scheduler.Flush();' in fence_queue
    assert 'if (!scheduler.DeferFlush()) {\n        scheduler.Flush();' in flush_commands
    assert '!VideoCommon::GpuSplit::OnBackThread()' in fence_wait and 'WaitSubmitted' in fence_wait
    assert 'SubmitDeferredWork();' in after_signal
    assert 'virtual void SubmitDeferredWork() {}' in fence_h
    assert 'scheduler.FlushDeferred();' in submit_deferred
    assert 'FlushDeferred(); }, &scheduler);' in hook_install
    assert raster_cpp.index(hook_install) < raster_cpp.index('SetSubmitHook(nullptr, nullptr);')
    # GpuSplit: quiet protocol.
    back = function(split_cpp, 'void GpuSplit::BackLoop(')
    assert back.index('on_back_thread = true;') < back.index('back_ready.store(true')
    assert back.index('back_quiet.store(false') < back.index('Execute(&ring[index])')
    assert back.index('QuietBack();') < back.index('back_waiting.store(true')
    assert back.rstrip()[:-1].rstrip().endswith('QuietBack();'), 'QuietBack on exit'
    assert back.count('hook_requested.load(') >= 4  # spin, PS5 sleep, desktop sleep, entries
    quiet = function(split_cpp, 'void GpuSplit::QuietBack()')
    assert quiet.index('submit_hook(submit_context)') < quiet.index('back_quiet.store(true')
    drain = function(split_cpp, 'void GpuSplit::Drain()')
    assert 'if (consumed_cache == write_position && BackQuiet()) {' in drain
    assert '== write_position && BackQuiet());' in drain  # PS5 progress predicate
    entry = function(split_cpp, 'void GpuSplit::BackEntry(')
    assert entry.index('catch') < entry.index('back_running.store(false')
    # 9960298: the front's DMA read flushes on the back.
    assert 'split.Drain();' not in front_dma
    sync = front_dma.index('split.Synchronize(')
    assert sync < front_dma.index('memory_manager.FlushRegion(') and \
        sync < front_dma.index('QueryDma::FlushPending(')
    # d1de145.
    assert maxwell_sink and maxwell_call and maxwell_multi and kepler_call, 'handback first'
    for field in ['executing_macro = front->executing_macro;', 'macro_params = std::move(',
                  'shadow_state.reg_array.data(), front->shadow.data()',
                  'shadow_state.shadow_ram_control = front->control;', 'front.reset();',
                  'front_macros = false;']:
        assert field in maxwell_release, field
    for field in ['native_executing_macro = front->executing_macro;', 'native_parameters =',
                  'native_compute_uploaded =', 'native_bind_pointer =', 'native_macro =',
                  'front.reset();', 'front_macros = false;']:
        assert field in kepler_release, field
    # 9479d8f has no target here: Step never drains before an entry (99zzzt1/t2 reads stay).
    assert '.Drain()' not in function(dma_cpp, 'bool DmaPusher::Step()')
    assert 'EDEN_NX2_FETCH_DRAIN' not in dma_cpp
    # Wiring.
    run = (root / 'tests-nx2/run.sh').read_text().splitlines()
    at = run.index('python3 tests-nx2/check-converted-upload-chunks.py')
    assert run[at + 1] == 'python3 tests-nx2/check-batched-vulkan-submissions.py'


if source_only:
    source_checks()
    print('Batched Vulkan submissions: source checks PASS (C++ not run)')
    sys.exit(0)
assert platform.system() == 'Linux', 'Run C++ fixture on Linux/dedie'


def define(fn, old, new):
    return fn.replace(old, new, 1) if fn else ''


fixture = r'''
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <vector>
#include "common/common_types.h"
#include "common/logging.h"
#include "common/settings.h"
#include "core/core.h"
#include "video_core/gpu_split.h"
#include "video_core/nx2_profile.h"
using s64 = int64_t;
using VkSemaphore = u64;
#define CHECK(cond, message) do { if (!(cond)) { \
    std::fprintf(stderr, "UB-042 FAIL: %s (%s)\n", message, #cond); std::exit(1); } } while (0)
using Clock = std::chrono::steady_clock;

namespace VideoCommon::Nx2Profile {
enum class Counter { DmaReadBytes };
inline bool Enabled() { return false; }
inline void Add(Counter, u64) {}
}
namespace VideoCommon {
enum class CacheType : u32 { None = 0, BufferCache = 1, QueryCache = 2 };
constexpr CacheType operator|(CacheType a, CacheType b) { return CacheType(u32(a) | u32(b)); }
}

std::thread::id g_back_id;
std::mutex g_mutex;
std::map<u64, bool> g_on_back; // tick -> submitted on the back
std::atomic<int> g_in_submit{};
std::atomic<unsigned> g_submits{};

struct MasterSemaphore {
    std::atomic<u64> current_tick{1}, gpu_tick{0};
    u64 CurrentTick() const { return current_tick.load(); }
    u64 NextTick() { return current_tick.fetch_add(1); }
    void Wait(u64 tick) {
        const auto deadline = Clock::now() + std::chrono::seconds{10};
        while (gpu_tick.load() < tick) {
            CHECK(Clock::now() < deadline, "waited for a GPU tick that was never submitted");
            std::this_thread::sleep_for(std::chrono::microseconds{50});
        }
    }
};

struct Scheduler {
    MasterSemaphore master;
    Clock::time_point last_flush{};
    bool flush_pending{};
    u64 Flush(VkSemaphore signal_semaphore = {}, VkSemaphore wait_semaphore = {});
    bool DeferFlush();
    void FlushDeferred();
    bool WaitSubmitted(u64 tick);
    bool IsSubmitted(u64 tick) const { return tick < master.CurrentTick(); }
    u64 CurrentTick() const { return master.CurrentTick(); }
    MasterSemaphore& GetMasterSemaphore() { return master; }
    // vk_scheduler.h Wait with may_flush (pacing omitted).
    void Wait(u64 tick) {
        if (tick > 0) {
            if (tick >= master.CurrentTick()) Flush();
            master.Wait(tick);
        }
    }
    u64 SubmitExecution(VkSemaphore, VkSemaphore) {
        CHECK(g_in_submit.fetch_add(1) == 0, "two threads in SubmitExecution at once");
        std::this_thread::sleep_for(std::chrono::microseconds{100});
        const u64 tick = master.NextTick();
        {
            std::scoped_lock lock{g_mutex};
            g_on_back[tick] = std::this_thread::get_id() == g_back_id;
        }
        u64 known = master.gpu_tick.load();
        while (known < tick && !master.gpu_tick.compare_exchange_weak(known, tick)) {}
        ++g_submits;
        g_in_submit.fetch_sub(1);
        return tick;
    }
    void AllocateNewContext() {}
};
bool OnBack(u64 tick) { std::scoped_lock lock{g_mutex}; return g_on_back.count(tick) && g_on_back[tick]; }

struct InnerFence {
    explicit InnerFence(Scheduler& scheduler_) : scheduler{scheduler_} {}
    Scheduler& scheduler;
    bool is_stubbed{};
    u64 wait_tick{};
    void Queue();
    void Wait();
};
struct RasterizerVulkan {
    Scheduler& scheduler;
    u32 draw_counter{};
    void FlushCommands();
};
struct FenceManager {
    Scheduler& scheduler;
    void SubmitDeferredWork();
    void AfterSignalFence();
};

struct MemoryModel {
    std::array<u32, 0x400> words{}, gpu{};
    bool dirty{};
    std::thread::id flush_thread{}, query_thread{};
    bool IsMemoryDirty(GPUVAddr, size_t, VideoCommon::CacheType) const { return dirty; }
    void FlushRegion(GPUVAddr address, size_t bytes, VideoCommon::CacheType) {
        flush_thread = std::this_thread::get_id();
        for (size_t i = 0; i < bytes / 4; ++i) words[address / 4 + i] = gpu[address / 4 + i];
        dirty = false;
    }
    template <typename T> T Read(GPUVAddr address) const { return words[address / 4]; }
};
struct RasterizerModel {};
namespace VideoCommon::QueryDma {
inline void FlushPending(MemoryModel& memory, RasterizerModel&, GPUVAddr, size_t) {
    memory.query_thread = std::this_thread::get_id();
}
}
struct DmaReadModel {
    struct FrontState { std::array<u32, 0x1000> regs{}; std::vector<u32> fifo; };
    MemoryModel memory_manager;
    RasterizerModel raster_model;
    RasterizerModel* rasterizer = &raster_model;
    std::vector<u32> native_data_ram;
    void FrontDmaRead(VideoCommon::GpuSplit& split, FrontState& fs, u32 method, u32 count);
};

struct MaxwellModel {
    enum class ShadowRamControl : u32 { Track = 0 };
    struct Shadow { std::array<u32, 0x1000> reg_array{}; ShadowRamControl shadow_ram_control{}; };
    struct FrontState {
        std::array<u32, 0x1000> shadow{};
        ShadowRamControl control{};
        u32 executing_macro{};
        std::vector<u32> parameters;
    };
    Shadow shadow_state;
    std::unique_ptr<FrontState> front;
    bool front_macros{};
    u32 executing_macro{};
    std::vector<u32> macro_params;
    std::vector<std::pair<u32, u32>> method_sink;
    void ReleaseFront();
    void ConsumeSinkImpl() {
        MAXWELL_SINK
        for (const auto& [method, value] : method_sink) shadow_state.reg_array[method] = value;
        method_sink.clear();
    }
    void CallMethod() { MAXWELL_CALL }
    void CallMultiMethod() { MAXWELL_MULTI }
};
struct MacroEngine {};
struct KeplerModel {
    struct FrontState {
        std::array<u32, 0x1000> registers{};
        std::optional<u32> executing_macro;
        std::vector<u32> parameters;
        bool compute_uploaded{};
        u32 bind_pointer{};
        MacroEngine* macro{};
    };
    std::unique_ptr<FrontState> front;
    bool front_macros{};
    std::optional<u32> native_executing_macro;
    std::vector<u32> native_parameters;
    bool native_compute_uploaded{};
    u32 native_bind_pointer{};
    MacroEngine* native_macro{};
    void ReleaseFront();
    void CallMethod() { KEPLER_CALL }
};

PRODUCTION

struct Context {
    Scheduler scheduler;
    RasterizerVulkan raster{scheduler};
    FenceManager manager{scheduler};
    unsigned entry_submits{};
    bool entry_pending{};
    bool deadlock_free{};
    bool back_kept_front{};
    std::atomic<bool> fencing_go{}, fencing_done{}, entry_ran{};
};
Context* g;

void ArmFront(MaxwellModel& m) {
    m.front = std::make_unique<MaxwellModel::FrontState>();
    m.front->shadow[5] = 0x1234;
    m.front->executing_macro = 0xe01;
    m.front->parameters = {7, 8};
    m.front_macros = true;
}

int main(int argc, char** argv) {
    const std::string mode = argc > 1 ? argv[1] : "batched";
    setenv("EDEN_NX2_SPLIT", "1", 1);
    Settings::high = false;
    Settings::safe = false;
    Core::System system;
    auto& split = VideoCommon::GpuSplit::Get();
    static Context context;
    g = &context;
    auto& scheduler = context.scheduler;
    (void)scheduler;
    HOOK_INSTALL
#ifdef EDEN_NX2_PS5_PROTO
    split.RequestEnable();
#endif
    split.MaybeStart(system);
    CHECK(split.Active(), "split did not start");
    split.Defer([] { g_back_id = std::this_thread::get_id(); });
    split.Drain();

    // Fences and FlushCommands in one window: one submission, made before Drain returns.
    InnerFence fa{scheduler}, fb{scheduler}, fc{scheduler};
    split.Defer([fa = &fa, fb = &fb, fc = &fc] {
        auto& s = g->scheduler;
        s.Flush();
        const unsigned before = g_submits.load();
        fa->Queue();
        fb->Queue();
        g->raster.draw_counter = 1;
        g->raster.FlushCommands();
        fc->Queue();
        g->entry_submits = g_submits.load() - before;
        g->entry_pending = !s.IsSubmitted(fc->wait_tick);
    });
    split.Drain();
    if (mode == "immediate") {
        CHECK(context.entry_submits == 4 && !context.entry_pending,
              "EDEN_NX2_FENCE_FLUSH_US=0 must submit at every fence and FlushCommands");
        split.Stop();
        std::puts("UB042_IMMEDIATE_OK");
        return 0;
    }
    CHECK(context.entry_submits == 0 && context.entry_pending,
          "fences and FlushCommands in one window each submitted");
    if (mode == "default") {
        split.Stop();
        CHECK(scheduler.IsSubmitted(fc.wait_tick), "deferred work left after the split stopped");
        std::puts("UB042_DEFAULT_WINDOW_OK");
        return 0;
    }
    CHECK(fa.wait_tick == fc.wait_tick && scheduler.IsSubmitted(fc.wait_tick) &&
              !scheduler.flush_pending,
          "Drain returned before the back submitted its deferred work (back_quiet)");
    CHECK(OnBack(fc.wait_tick), "the batched submission was not made on the back");
    {
        const unsigned after = g_submits.load();
        std::this_thread::sleep_for(std::chrono::milliseconds{30});
        CHECK(g_submits.load() == after, "the back submitted after Drain returned");
    }

    // Submitted before the back sleeps, without a Drain or a request.
    InnerFence fe{scheduler};
    split.Defer([fe = &fe] {
        g->scheduler.Flush();
        fe->Queue();
        g->entry_pending = !g->scheduler.IsSubmitted(fe->wait_tick);
        g->entry_ran = true;
    });
    split.Publish();
    {
        const auto deadline = Clock::now() + std::chrono::seconds{2};
        while (!(context.entry_ran && scheduler.IsSubmitted(fe.wait_tick)) && Clock::now() < deadline) {
            std::this_thread::sleep_for(std::chrono::microseconds{100});
        }
        CHECK(scheduler.IsSubmitted(fe.wait_tick), "a deferred fence was left unsubmitted while the back slept");
    }
    split.Drain();
    CHECK(context.entry_pending && OnBack(fe.wait_tick), "the idle submission was not deferred work on the back");

    // A long entry (shader translation) after a deferred fence: the fencing thread keeps waiting.
    InnerFence ff{scheduler};
    context.fencing_go = false;
    split.Defer([ff = &ff] {
        g->scheduler.Flush();
        ff->Queue();
        g->entry_pending = !g->scheduler.IsSubmitted(ff->wait_tick);
        g->fencing_go = true;
        std::this_thread::sleep_for(std::chrono::milliseconds{2500});
    });
    split.Publish();
    bool returned_submitted{}, returned_complete{};
    double waited{};
    std::thread fencing([&] {
        while (!context.fencing_go) std::this_thread::yield();
        const auto start = Clock::now();
        ff.Wait();
        waited = std::chrono::duration<double>(Clock::now() - start).count();
        returned_submitted = scheduler.IsSubmitted(ff.wait_tick);
        returned_complete = scheduler.master.gpu_tick.load() >= ff.wait_tick;
    });
    fencing.join();
    split.Drain();
    CHECK(context.entry_pending, "the long-entry fence was not deferred");
    CHECK(returned_submitted && returned_complete,
          "InnerFence::Wait gave up on a deferred tick while the back still ran");
    CHECK(waited >= 2.0 && OnBack(ff.wait_tick), "the fencing thread submitted the back's tick itself");

    // WaitPendingFences on the back: its fence waits on the fencing thread for the back's submit.
    InnerFence fg{scheduler};
    context.fencing_go = false;
    context.fencing_done = false;
    std::thread waiter([&] {
        while (!context.fencing_go) std::this_thread::yield();
        fg.Wait();
        context.fencing_done = true;
    });
    split.Defer([fg = &fg] {
        g->scheduler.Flush();
        fg->Queue();
        g->fencing_go = true;
        g->manager.AfterSignalFence();
        const auto deadline = Clock::now() + std::chrono::seconds{3};
        while (!g->fencing_done && Clock::now() < deadline) {
            std::this_thread::sleep_for(std::chrono::microseconds{100});
        }
        g->deadlock_free = g->fencing_done.load();
    });
    split.Drain();
    waiter.join();
    CHECK(context.deadlock_free, "WaitPendingFences on the back blocked behind its own deferred flush");

    // FrontDmaRead: the buffer and query flushes run on the back.
    DmaReadModel dma;
    dma.native_data_ram.resize(16);
    DmaReadModel::FrontState fs;
    fs.regs[0x155] = 0x100;
    dma.memory_manager.dirty = true;
    dma.memory_manager.gpu[0x40] = 7;
    dma.memory_manager.gpu[0x41] = 8;
    dma.memory_manager.gpu[0x42] = 9;
    dma.FrontDmaRead(split, fs, 0x158, 3);
    CHECK(dma.memory_manager.flush_thread == g_back_id && dma.memory_manager.query_thread == g_back_id,
          "the front DMA read flushed back-owned caches on the front");
    CHECK((fs.fifo == std::vector<u32>{7, 8, 9}), "the front DMA read missed the flushed words");

    // Engine methods on the back keep the front's macros.
    static MaxwellModel on_back;
    ArmFront(on_back);
    split.Defer([] { on_back.CallMethod(); g->back_kept_front = on_back.front_macros; });
    split.Drain();
    CHECK(context.back_kept_front, "an engine method on the back took the macros from the front");

    // Stopping leaves nothing deferred, and a fence wait afterwards returns.
    InnerFence fh{scheduler};
    context.entry_ran = false;
    split.Defer([fh = &fh] {
        g->scheduler.Flush();
        fh->Queue();
        g->entry_ran = true;
    });
    split.Publish();
    while (!context.entry_ran) std::this_thread::yield();
    split.Stop();
    CHECK(!split.Active() && scheduler.IsSubmitted(fh.wait_tick), "deferred work left after the split stopped");
    fh.Wait();

    // After the stop, methods on this thread hand the macros and shadow RAM back, the sink's
    // newer writes first.
    MaxwellModel sink;
    ArmFront(sink);
    sink.method_sink.emplace_back(5, 0x5678);
    sink.ConsumeSinkImpl();
    CHECK(!sink.front_macros && !sink.front && sink.shadow_state.reg_array[5] == 0x5678 &&
              sink.executing_macro == 0xe01 && (sink.macro_params == std::vector<u32>{7, 8}),
          "ConsumeSinkImpl off the back did not hand the 3D macros back before the sunk writes");
    MaxwellModel call, multi;
    ArmFront(call);
    call.CallMethod();
    ArmFront(multi);
    multi.CallMultiMethod();
    CHECK(!call.front_macros && call.shadow_state.reg_array[5] == 0x1234 && !multi.front_macros,
          "a 3D method off the back kept the macros on the stopped split's front");
    KeplerModel compute;
    MacroEngine macro;
    compute.front = std::make_unique<KeplerModel::FrontState>();
    compute.front->executing_macro = 3;
    compute.front->parameters = {1, 2};
    compute.front->compute_uploaded = true;
    compute.front->bind_pointer = 4;
    compute.front->macro = &macro;
    compute.front_macros = true;
    compute.CallMethod();
    CHECK(!compute.front_macros && !compute.front && compute.native_executing_macro == 3u &&
              compute.native_compute_uploaded && compute.native_bind_pointer == 4 &&
              compute.native_macro == &macro && (compute.native_parameters == std::vector<u32>{1, 2}),
          "a compute method off the back kept the macros on the stopped split's front");
    std::puts("UB042_BATCHED_OK");
}
'''

production = [
    define(flush, 'u64 Scheduler::Flush(', 'u64 Scheduler::Flush('),
    defer, flush_deferred, wait_submitted, fence_queue, fence_wait, flush_commands,
    submit_deferred or 'void FenceManager::SubmitDeferredWork() {}',
    'void FenceManager::AfterSignalFence() {' + after_signal + '}',
    define(front_dma, 'Maxwell3D::', 'DmaReadModel::'),
    define(maxwell_release, 'Maxwell3D::', 'MaxwellModel::'),
    define(kepler_release, 'KeplerCompute::', 'KeplerModel::'),
]
fixture = (fixture.replace('PRODUCTION', '\n\n'.join(p for p in production if p))
           .replace('HOOK_INSTALL', hook_install)
           .replace('MAXWELL_SINK', maxwell_sink).replace('MAXWELL_CALL', maxwell_call)
           .replace('MAXWELL_MULTI', maxwell_multi).replace('KEPLER_CALL', kepler_call))

out = root / 'build/nx2-tests/batched-vulkan-submissions'
shutil.rmtree(out, ignore_errors=True)
shutil.copytree(root / 'tests-nx2/split-observer-stubs', out / 'include')
for name in ['gpu_split.cpp', 'gpu_split.h', 'native_semaphore_observation.h']:
    shutil.copy(src / name, out / 'include/video_core' / name)
(out / 'test.cpp').write_text(fixture)
compiler = os.environ.get('CXX', 'clang++-18')
for ps5 in [False, True]:
    binary = out / ('test-ps5' if ps5 else 'test')
    subprocess.run([compiler, '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined', '-pthread',
                    *(['-DEDEN_NX2_PS5_PROTO'] if ps5 else []), '-I', str(out / 'include'),
                    str(out / 'include/video_core/gpu_split.cpp'), str(out / 'test.cpp'),
                    '-o', str(binary)], check=True)
    # Production caches the window: a fresh process for each setting.
    for window, run_mode in [('200000', 'batched'), (None, 'default'), ('0', 'immediate')]:
        env = dict(os.environ)
        env.pop('EDEN_NX2_FENCE_FLUSH_US', None)
        if window is not None:
            env['EDEN_NX2_FENCE_FLUSH_US'] = window
        with tempfile.TemporaryDirectory(prefix='ub042-') as temp:
            env['EDEN_NX2_SPLIT_OBSERVER_LOG'] = str(Path(temp) / 'observer.log')
            subprocess.run([str(binary), run_mode], env=env, check=True)

source_checks()
print('Batched Vulkan submissions: production C++ behavior (desktop and PS5 split) and source checks PASS')
