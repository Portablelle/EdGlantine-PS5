"""Compile real GPU waits with device-loss/logging shims; run only on dedie."""
from pathlib import Path
import platform
import subprocess
import tempfile

assert platform.system() == 'Linux', 'Compile on dedie'
root = Path(__file__).resolve().parents[1]
source = Path((root / '.local/headless-cache').read_text().strip()) / 'source/src'
text = (source / 'video_core/renderer_vulkan/vk_master_semaphore.cpp').read_text()


def extract(signature):
    start = text.index(signature)
    end = text.index('{', start) + 1
    depth = 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


wait = extract('void MasterSemaphore::Wait(u64 tick)')
debug_wait = extract('[this](std::stop_token stop_token)')
cpp = r'''
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <exception>
#include <stop_token>
#include <string>
#include <vector>
using u64 = std::uint64_t;
constexpr int VK_ERROR_DEVICE_LOST = -4;
namespace vk {
struct Exception final : std::exception {
    int result;
    explicit Exception(int value) : result(value) {}
    const char* what() const noexcept override { return "VK_ERROR_DEVICE_LOST"; }
    int GetResult() const { return result; }
};
}
namespace VideoCommon::NativeWaitProfile {
enum class Kind { TimelineWait };
struct Scope {
    inline static unsigned active{};
    Scope(Kind, void*) { ++active; }
    ~Scope() { --active; }
};
}
struct CriticalLine { std::string category, message; };
std::vector<CriticalLine> critical_lines;
void RecordCritical(const char* category, std::string message, u64 tick, const char* reason) {
    auto pos = message.find("{}");
    assert(pos != std::string::npos);
    message.replace(pos, 2, std::to_string(tick));
    pos = message.find("{}");
    assert(pos != std::string::npos);
    message.replace(pos, 2, reason);
    critical_lines.push_back({category, message});
}
#define LOG_CRITICAL(category, ...) RecordCritical(#category, __VA_ARGS__)
struct Semaphore {
    bool present = true, fail = true;
    unsigned calls{}, timeouts{};
    u64 last_tick{}, last_timeout{};
    explicit operator bool() const { return present; }
    bool Wait(u64 tick, u64 timeout = ~u64{0}) {
        ++calls;
        last_tick = tick;
        last_timeout = timeout;
        if (timeouts) { --timeouts; return false; }
        if (fail) { throw vk::Exception(VK_ERROR_DEVICE_LOST); }
        return true;
    }
};
struct MasterSemaphore {
    Semaphore semaphore;
    std::atomic<u64> gpu_tick{0};
    unsigned refreshes{};
    bool free_after_refresh{};
    bool IsFree(u64 tick) const { return gpu_tick.load() >= tick; }
    void Refresh() { ++refreshes; if (free_after_refresh) gpu_tick.store(~u64{0}); }
    void Wait(u64 tick);
    void DebugWait(std::stop_token token);
};
'''
cpp += wait + '\nvoid MasterSemaphore::DebugWait(std::stop_token token) { auto run = '
cpp += debug_wait + '; run(token); }\n'
cpp += r'''
void CheckLine(u64 tick) {
    assert(critical_lines.size() == 1);
    assert(critical_lines[0].category == "Render_Vulkan");
    assert(critical_lines[0].message == "Waiting for GPU tick " + std::to_string(tick) +
                                        " failed: VK_ERROR_DEVICE_LOST");
    assert(VideoCommon::NativeWaitProfile::Scope::active == 0);
    critical_lines.clear();
}
int main() {
    // A timeout retries; device loss then logs once and preserves the Vulkan exception.
    constexpr u64 tick = 0x123456789abcdef0ULL;
    MasterSemaphore failed;
    failed.semaphore.timeouts = 1;
    bool propagated = false;
    try { failed.Wait(tick); }
    catch (const vk::Exception& exception) {
        propagated = true;
        assert(exception.GetResult() == VK_ERROR_DEVICE_LOST);
        assert(std::string(exception.what()) == "VK_ERROR_DEVICE_LOST");
    }
    assert(propagated);
    assert(failed.semaphore.calls == 2 && failed.semaphore.last_tick == tick);
    assert(failed.refreshes == 1); // Never refresh again after a failed wait.
    CheckLine(tick);

    // Execute the real debug-thread lambda synchronously so rethrow can be observed.
    MasterSemaphore debug;
    propagated = false;
    try { debug.DebugWait(std::stop_token{}); }
    catch (const vk::Exception& exception) {
        propagated = true;
        assert(exception.GetResult() == VK_ERROR_DEVICE_LOST);
    }
    assert(propagated);
    assert(debug.semaphore.calls == 1 && debug.semaphore.last_timeout == 10'000'000);
    CheckLine(0);

    MasterSemaphore success;
    success.semaphore.fail = false;
    success.semaphore.timeouts = 1;
    success.Wait(tick);
    assert(success.semaphore.calls == 2 && success.refreshes == 2);
    for (unsigned mode = 0; mode < 3; ++mode) {
        MasterSemaphore ready;
        if (mode == 0) ready.free_after_refresh = true;
        else ready.gpu_tick.store(tick);
        if (mode == 2) ready.semaphore.present = false;
        ready.Wait(tick);
        assert(ready.semaphore.calls == 0);
    }
    assert(critical_lines.empty());
    assert(VideoCommon::NativeWaitProfile::Scope::active == 0);
    std::puts("LOG_FAILED_GPU_WAIT_PASS");
}
'''
with tempfile.TemporaryDirectory(prefix='log-failed-gpu-wait-') as td:
    path = Path(td)
    (path / 'check.cpp').write_text(cpp)
    for defines in ([], ['-DEDEN_NX2_PS5_PROTO']):
        subprocess.run(['clang++-18', '-std=c++20', '-O1', '-g',
                        '-fsanitize=address,undefined', *defines,
                        str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
        subprocess.run([str(path / 'check')], check=True)
