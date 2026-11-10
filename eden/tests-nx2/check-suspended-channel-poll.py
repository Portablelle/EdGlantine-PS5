"""UB-113: pending-channel wait polls every 50 us after the yield window, 1 ms after 2 s.

Compiles the PRODUCTION wait of ThreadManager::StartThread (the PendingSleep block of the
HasPendingNativeChannels path, extracted from the prepared gpu_thread.cpp) with a fake clock, a
counting yield and a recording queue whose PopWaitFor logs its timeout and can be made to return an
item (a new command). Checked, with no command queued:
 - first 500 us since last progress: yields, no wait;
 - from 500 us to 2 s: PopWaitFor(50 us);  from 2 s on: PopWaitFor(1 ms);
 - a command arriving during the wait is popped (the wait is still PopWaitFor, wakeable).
Source checks: no prctl / PR_SET_TIMERSLACK / sys/prctl.h in gpu_thread.cpp, PopWaitFor kept.
Negative control: on main (a tree without layer 99zzzzd) the wait after the yield window is 250 us
at every elapsed time, so the 50 us and the 1 ms-after-2 s expectations fail. --source-only asserts
those intervals in the extracted production block (and still rejects prctl / sleep_for). The compiled
harness is Linux/dedie-only.

Usage: check-suspended-channel-poll.py [--source-only] [SOURCE_DIR]   SOURCE_DIR contains src/
(default: this checkout's prepared build cache).
"""
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

args = [a for a in sys.argv[1:] if not a.startswith('--')]
source_only = '--source-only' in sys.argv[1:]
if not source_only:
    assert platform.system() == 'Linux', 'Run on the Linux build server'
root = Path(__file__).resolve().parents[1]
if args:
    source = Path(args[0]).resolve()
else:
    source = Path((root / '.local/headless-cache').read_text().strip()) / 'source'
text = (source / 'src/video_core/gpu_thread.cpp').read_text()

for banned in ('prctl', 'PR_SET_TIMERSLACK', 'sys/prctl.h', 'TIMERSLACK'):
    assert banned not in text, 'Linux-only timer slack must not be ported: ' + banned
start = text.index('Profile::Scope scope{Profile::Zone::PendingSleep};')
end = text.index('PopWaitFor(', start)
end = text.index('continue;', end)
end = text.index('}', end) + 1
block = text[start:end]
assert 'PopWaitFor(' in block and 'sleep_for' not in block, 'the wait must stay wakeable (PopWaitFor)'
block = block.replace('std::chrono::steady_clock::now()', 'fake_now()')
block = block.replace('std::this_thread::yield()', 'fake_yield()')

# Source-level behavior gate (no compiler): main still waits 250 us with no 2 s back-off.
has_50 = 'microseconds{50}' in block or 'microseconds{ 50}' in block
has_250 = 'microseconds{250}' in block or 'microseconds{ 250}' in block
has_2s = 'seconds{2}' in block or 'seconds{ 2}' in block
has_1000 = 'microseconds{1000}' in block or 'microseconds{ 1000}' in block or 'milliseconds{1}' in block
assert has_50 and has_2s and has_1000 and not has_250, (
    f'source wait is not 50 us with 2 s -> 1 ms back-off '
    f'(50={has_50} 2s={has_2s} 1000={has_1000} still_250={has_250})'
)

if source_only:
    print('suspended-channel-poll source checks passed')
    sys.exit(0)

harness = r'''
#include <chrono>
#include <cstdio>
#include <string>
namespace Profile { enum class Zone { PendingSleep }; struct Scope { Scope(Zone) {} }; }
using TP = std::chrono::steady_clock::time_point;
static TP g_now;
static TP fake_now() { return g_now; }
static std::string g_event;
static void fake_yield() { g_event = "yield"; }
struct Q {
    bool deliver = false;
    template <typename R, typename P>
    bool PopWaitFor(int& item, const std::chrono::duration<R, P>& t) {
        g_event = "wait:" + std::to_string(std::chrono::duration_cast<std::chrono::microseconds>(t).count());
        if (deliver) { item = 7; return true; }
        return false;
    }
};
// Returns the event of one pass of the production block, "popped" if a command arrived.
static std::string Step(long long elapsed_us, bool deliver = false) {
    Q queue; queue.deliver = deliver;
    struct { Q& queue; } state{queue};
    int next = 0;
    const TP last_progress{};
    g_now = last_progress + std::chrono::microseconds{elapsed_us};
    g_event = "none";
    bool popped = false;
    do {
        {
''' + block + r'''
            popped = true;
        }
    } while (false);  // `continue` leaves the pass, as it re-enters the loop in production
    return popped ? g_event + ",popped" : g_event;
}
static int fails = 0;
static void Expect(long long us, const char* want, bool deliver = false) {
    const std::string got = Step(us, deliver);
    if (got != want) { std::fprintf(stderr, "at %lld us: got %s want %s\n", us, got.c_str(), want); ++fails; }
}
int main() {
    Expect(0, "yield"); Expect(499, "yield");
    Expect(500, "wait:50"); Expect(10000, "wait:50"); Expect(1999999, "wait:50");
    Expect(2000000, "wait:1000"); Expect(60000000, "wait:1000");
    Expect(1000, "wait:50,popped", true);
    Expect(3000000, "wait:1000,popped", true);
    return fails ? 3 : 0;
}
'''
out = root / 'build/nx2-tests/suspended-channel-poll'
out.mkdir(parents=True, exist_ok=True)
cpp = out / 'harness.cpp'
cpp.write_text(harness)
subprocess.run(['g++', '-std=c++20', str(cpp), '-o', str(out / 'h')], check=True)
subprocess.run([str(out / 'h')], check=True)
print('suspended-channel-poll checks passed')
