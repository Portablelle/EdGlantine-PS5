"""UB-056, Linux/dedie only: production CFG lookup/order and claim-once pipeline builds.

Usage: python3 tests-nx2/check-faster-shader-translation.py [SOURCE_DIR]
SOURCE_DIR contains src/; defaults to .local/headless-cache's source directory.
Negative control: run the SAME command against prepared main without layer 99zzzz4.
It must fail by behavior: linear Contains calls, long sibling walk, and a waiter unable
to finish a queued build. Missing RunBuild on main is modeled as a no-op, not a source
assertion failure. Requires clang++-18. No Vulkan driver needed; compile extracted production algorithms
with instrumented containers and a paused worker. This is not a shader timing benchmark.
"""
from pathlib import Path
import platform
import subprocess
import sys

assert platform.system() == 'Linux', 'Run on dedie only'
root = Path(__file__).resolve().parents[1]
source = (Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else
          Path((root / '.local/headless-cache').read_text().strip()) / 'source')
src = source / 'src'
out = root / 'build/nx2-tests/faster-shader-translation'
out.mkdir(parents=True, exist_ok=True)


def function(text, signature):
    assert text.count(signature) == 1, 'Ambiguous/missing production code: ' + signature
    start = text.index(signature)
    end = text.index('{', start) + 1
    depth = 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end] + '\n'


cfg = (src / 'shader_recompiler/frontend/maxwell/control_flow.cpp').read_text()
structured = (src / 'shader_recompiler/frontend/maxwell/structured_control_flow.cpp').read_text()
compare = function(cfg, 'struct Compare {') + ';\n'
lookup = function(cfg, 'bool CFG::InspectVisitedBlocks(')
# Extract the complete production lookup and miss branch, stopping before split/insert.
# Return membership instead of splitting; the block container only needs ordered lookup.
lookup = lookup[:lookup.index('    Block* const visited_block')] + '    return true;\n}\n'
ordered = function(structured, 'bool AreOrdered(')

code = r'''
#include <algorithm>
#include <atomic>
#include <barrier>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <functional>
#include <iterator>
#include <mutex>
#include <set>
#include <stdexcept>
#include <thread>
#include <utility>
#include <vector>
int failures = 0;
void check(bool ok, const char* what) {
    if (!ok) { ++failures; std::printf("FAIL: %s\n", what); }
}
using Location = int;
int contains_calls = 0, compares = 0, increments = 0;
struct Block {
    Location begin, end;
    bool Contains(Location pc) const { ++contains_calls; return begin <= pc && pc < end; }
};
'''
code += compare
code += r'''
struct CountCompare : Compare {
    using is_transparent = void;
    template<class L, class R> bool operator()(const L& l, const R& r) const {
        ++compares; return Compare::operator()(l, r);
    }
};
// Production uses an intrusive ordered set. This adapter preserves its upper_bound API
// and instruments comparisons separately from Contains, so linear lookup fails on main.
struct Blocks : std::set<Block, CountCompare> {
    auto upper_bound(Location pc, Compare) { return std::set<Block, CountCompare>::upper_bound(pc); }
};
struct Function { Blocks blocks; };
using FunctionId = int;
struct Label { Location address; };
struct CFG {
    Function functions[1];
    bool InspectVisitedBlocks(FunctionId function_id, const Label& label);
};
'''
code += lookup
code += r'''
struct Parent;
struct Node {
    int index;
    Parent* up;
    Node* operator->() { return this; }
    Node& operator++() { ++increments; ++index; return *this; }
    bool operator==(const Node&) const = default;
};
struct Parent {
    struct Children { Parent* parent; int size; Node end() { return {size, parent}; } } children;
    explicit Parent(int size) : children{this, size} {}
};
'''
code += ordered
code += r'''
namespace vk { struct CommandBuffer {}; }
struct Worker {
    std::vector<std::function<void()>> jobs;
    template<class F> void QueueWork(F f) { jobs.emplace_back(std::move(f)); }
    void Drain() { for (auto& job : jobs) job(); jobs.clear(); }
};
struct Scheduler {
    template<class F> void Record(F f) { f(vk::CommandBuffer{}); }
};
// Bound a regression's wait rather than hanging the test forever on main. The production
// wait predicate and lock are unchanged, including when the worker already owns the task.
struct Condvar : std::condition_variable {
    std::function<void()> before_wait;
    template<class P> void wait(std::unique_lock<std::mutex>& lock, P predicate) {
        if (before_wait) before_wait();
        check(wait_for(lock, std::chrono::seconds(1), predicate), "waiter did not finish queued build");
    }
};
'''
for kind, cls, configure, worker in (
        ('compute', 'ComputePipeline', 'Configure', 'thread_worker'),
        ('graphics', 'GraphicsPipeline', 'ConfigureDraw', 'worker_thread')):
    text = (src / f'video_core/renderer_vulkan/vk_{kind}_pipeline.cpp').read_text()
    header = (src / f'video_core/renderer_vulkan/vk_{kind}_pipeline.h').read_text()
    run_sig = f'void {cls}::RunBuild()'
    run = function(text, run_sig) if run_sig in text else run_sig + ' {}\n'
    # Extract production scheduling from the constructor, with its optional task storage.
    worker_at = text.index(f'    if ({worker})')
    tail = text[:text.index('\n}\n', worker_at) + 3]
    assert tail.count(f'if ({worker})') == 1
    start = tail.find('    build_task = std::move(func);')
    queue = tail[start:worker_at] if start != -1 else ''
    queue += function(tail[worker_at:], f'if ({worker})')
    queue += function(tail[worker_at:], 'else {')
    wait = function(function(text, f'bool {cls}::{configure}('),
                    'if (!is_built.load(std::memory_order::relaxed))')
    fields = '\n'.join(line.strip() for line in header.splitlines()
                       if 'std::function<void()> build_task;' in line or
                       'std::atomic_bool build_claimed{' in line)
    code += f'''
struct {cls} {{
    {fields}
    std::atomic_bool is_built{{false}};
    Condvar build_condvar;
    std::mutex build_mutex;
    std::atomic_int builds{{0}};
    std::function<void()> before_build;
    void RunBuild();
    void Start(Worker* {worker}) {{
        auto func = [this] {{
            ++builds;
            if (before_build) before_build();
            std::scoped_lock lock{{build_mutex}};
            is_built = true;
            build_condvar.notify_one();
        }};
        {queue}
    }}
    void Wait(Scheduler& scheduler) {{ {wait} }}
}};
'''
    code += run

code += r'''
template<class Pipeline> void TestPipeline() {
    Scheduler scheduler;
    {   // The queue is deliberately paused: the waiter must claim and finish its own build.
        Pipeline p; Worker worker; p.Start(&worker);
        check(!p.is_built && p.builds == 0, "worker queue was not paused");
        p.Wait(scheduler);
        check(p.is_built && p.builds == 1, "waiter failed to claim queued build");
        worker.Drain();
        check(p.builds == 1, "late worker built pipeline twice");
    }
    { Pipeline p; p.Start(nullptr); check(p.is_built && p.builds == 1, "synchronous build"); }
    // Both direct and scheduler claims must publish completion even if the task throws.
    for (int via_wait = 0; via_wait < 2; ++via_wait) {
        Pipeline p; Worker worker;
        p.before_build = [] { throw std::runtime_error("non-vk build failure"); };
        p.Start(&worker);
        bool caught = false;
        try {
            if (via_wait) p.Wait(scheduler); else p.RunBuild();
        } catch (const std::runtime_error&) {
            caught = true;
        }
        check(caught, "non-vk build exception must propagate");
        check(p.is_built && p.builds == 1, "throwing build must publish completion");
        if constexpr (requires { p.build_task; }) {
            check(!p.build_task, "throwing build must clear its task");
        }
        p.RunBuild();
        p.Wait(scheduler);
        // Main has no claim path: allow its queued task to drain without an uncaught throw.
        p.before_build = nullptr;
        worker.Drain();
        check(p.builds == 1, "throwing build must not be retried");
    }
    for (int i = 0; i < 100; ++i) {
        Pipeline p; Worker worker; p.Start(&worker);
        std::barrier gate(3);
        std::thread a([&] { gate.arrive_and_wait(); p.RunBuild(); });
        std::thread b([&] { gate.arrive_and_wait(); p.RunBuild(); });
        gate.arrive_and_wait(); a.join(); b.join();
        check(p.is_built && p.builds == 1, "racing callers must build exactly once");
        worker.Drain();
        check(p.builds == 1, "queued caller after racing builds");
    }
    {   // Worker owns a build that is still running when the scheduler arrives.
        Pipeline p; Worker worker;
        std::barrier entered(2);
        p.before_build = [&] { entered.arrive_and_wait(); entered.arrive_and_wait(); };
        p.build_condvar.before_wait = [&] { entered.arrive_and_wait(); };
        p.Start(&worker);
        std::thread builder([&] { worker.Drain(); });
        entered.arrive_and_wait(); p.Wait(scheduler); builder.join();
        check(p.is_built && p.builds == 1, "wait on worker-owned build");
    }
}
int main() {
    CFG cfg;
    check(!cfg.InspectVisitedBlocks(0, Label{0}), "empty block set");
    constexpr int n = 4096;
    for (int i = 0; i < n; ++i) cfg.functions[0].blocks.insert(Block{i * 4, i * 4 + 2});
    contains_calls = compares = 0;
    check(cfg.InspectVisitedBlocks(0, Label{(n - 1) * 4 + 1}), "last block membership");
    check(contains_calls <= 1, "last block lookup scans Contains linearly");
    check(compares < 64, "last block lookup is not logarithmic");
    for (int pc = -1; pc <= n * 4; ++pc) {
        const bool expected = pc >= 0 && pc < n * 4 && pc % 4 < 2;
        check(cfg.InspectVisitedBlocks(0, Label{pc}) == expected, "lookup gap/boundary membership");
    }
    Parent siblings(n);
    increments = 0;
    check(AreOrdered(Node{0, &siblings}, Node{1, &siblings}), "nearby sibling ordering");
    check(increments <= 2, "nearby sibling walks to end of entire list");
    for (int size = 1; size <= 32; ++size) {
        Parent parent(size);
        for (int left = 0; left < size; ++left)
            for (int right = 0; right < size; ++right)
                check(AreOrdered(Node{left, &parent}, Node{right, &parent}) == (left < right),
                      "sibling ordering differs from list order");
    }
    TestPipeline<ComputePipeline>();
    TestPipeline<GraphicsPipeline>();
    std::puts(failures ? "Faster shader translation FAILED" : "Faster shader translation PASS");
    return failures ? 1 : 0;
}
'''
(out / 'translation.cpp').write_text(code)
exe = out / 'translation'
subprocess.run(['clang++-18', '-std=c++20', '-pthread', '-O1', '-g',
                '-fsanitize=address,undefined', str(out / 'translation.cpp'), '-o', str(exe)], check=True)
subprocess.run([str(exe)], check=True)

# Secondary source checks: do not bypass the layered physical-pointer coherence path.
memory = (src / 'core/memory.cpp').read_text()
manager = (src / 'core/device_memory_manager.h').read_text()
assert 'bool IsPhysicalPointer(const u8* p) const' in manager
for name in ('HandleRasterizerDownload', 'HandleRasterizerWrite'):
    body = function(memory, 'void ' + name + '(')
    guard = function(body, 'if (!gpu_device_memory->IsPhysicalPointer(p))')
    assert 'ReportForeignPointer(v_address, p);' in guard and 'return;' in guard
    assert body.index('GetPointerImpl(') < body.index('IsPhysicalPointer(p)') < body.index('ApplyOpOnPointer(')
report = function(memory, 'void ReportForeignPointer(')
assert 'reported.fetch_add(1, std::memory_order_relaxed) >= 16' in report
print('Physical-pointer guard source checks PASS')
graphics = (src / 'video_core/renderer_vulkan/vk_graphics_pipeline.cpp').read_text()
assert graphics.index('configure_func = ConfigureFunc(spv_modules, stage_infos);') < graphics.index(
    'build_task = std::move(func);') < graphics.index('worker_thread->QueueWork(')
