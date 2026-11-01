#!/usr/bin/env python3
"""Exercise production request/deadline polling without calling HUD telemetry."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / 'headless/performance.cpp').read_text()
start = source.index('namespace {\nstruct ProfilingState {')
end = source.index('    if (reports < 36) {', start)
poll = source[start:end] + '}\n'
# Execute the real controller header and production profiling restart/expiry logic.
with tempfile.TemporaryDirectory(prefix='nx2-runtime-control-') as directory:
    temp = Path(directory)
    fixture = r'''
#include <atomic>
#include <cassert>
#include <cstdio>
#include <cstdint>
#include <fstream>
#include <string>
#include <thread>
#include <filesystem>
#include "runtime_control.h"
static long long clock_ns=1;
long long MonotonicNs(){return clock_ns;}
long long NowNs(){return clock_ns;}
std::atomic<long long> detailed_until_ns{};
std::atomic<bool> dev_marks{};
namespace VideoCommon {
struct GpuSplit {
 unsigned enables{};
 static GpuSplit& Get(){static GpuSplit split;return split;}
 void RequestEnable(){++enables;}
};
struct NativeWaitProfile {static unsigned Restart(){static unsigned epoch;return ++epoch;}};
}
namespace Vulkan::NativeGpuProfile {
std::atomic<unsigned long long> epoch{1};
std::atomic<bool> enabled{false};
}
'''
    fixture += poll
    fixture += r'''
int main(int argc,char**argv){
 assert(argc==2);const std::filesystem::path root=argv[1];
 Eden::RuntimeControl controller((root/"split-enable.request").string(),(root/"profile-refresh.request").string());
 auto tick=[&]{controller.Poll(clock_ns,[]{VideoCommon::GpuSplit::Get().RequestEnable();},[]{RestartProfiling();});TickProfiling();};
 auto request=[&](const char* file,const char* nonce){std::ofstream(root/file)<<nonce;};
 request("split-enable.request","one");request("profile-refresh.request","one");
 tick();
 assert(VideoCommon::GpuSplit::Get().enables==1);
 assert(!std::filesystem::exists(root/"split-enable.request"));
 assert(!std::filesystem::exists(root/"profile-refresh.request"));
 assert(dev_marks && Vulkan::NativeGpuProfile::enabled && detailed_until_ns==20'000'000'001LL);
 const auto epoch=Vulkan::NativeGpuProfile::epoch.load();
 clock_ns+=1'000'000'000LL;
 request("split-enable.request","one");request("profile-refresh.request","one");
 tick();assert(VideoCommon::GpuSplit::Get().enables==1);
 assert(Vulkan::NativeGpuProfile::epoch==epoch);
 clock_ns=21'000'000'001LL;tick();
 assert(!dev_marks && !Vulkan::NativeGpuProfile::enabled && detailed_until_ns==0);
 // A fresh session thread owns fresh nonce/report state.
 request("split-enable.request","one");request("profile-refresh.request","one");
 std::thread next_session([&]{
 Eden::RuntimeControl next((root/"split-enable.request").string(),(root/"profile-refresh.request").string());
 next.Poll(clock_ns,[]{VideoCommon::GpuSplit::Get().RequestEnable();},[]{RestartProfiling();});
 TickProfiling();
 });next_session.join();
 assert(VideoCommon::GpuSplit::Get().enables==2);
 assert(Vulkan::NativeGpuProfile::epoch==epoch+1 && dev_marks);
 std::puts("RUNTIME_CONTROL_OK: no HUD, consume once, expiry, new session");
}
'''
    cpp = temp / 'test.cpp'
    cpp.write_text(fixture)
    subprocess.run([os.environ.get('CXX', 'clang++'), '-std=c++20', '-O1', '-g',
                    '-fsanitize=address,undefined', '-pthread', '-DEDEN_NX2_PS5_PROTO',
                    '-I', str(root / 'headless'),
                    str(cpp), '-o', str(temp / 'test')], check=True)
    subprocess.run([str(temp / 'test'), str(temp)], check=True)
# Integration guards: ordinary telemetry cannot trigger commands, and the session
# loop must be joined before guest/renderer teardown.
telemetry = source[source.index('unsigned GpuBusyPercent() {'):source.index('void MemoryPool(')]
assert 'RequestEnable' not in telemetry and 'std::fopen' not in telemetry
main = (root / 'headless/main.cpp').read_text()
a = main.index('std::jthread runtime_control')
b = main.index('system.ShutdownMainProcess();', a)
assert 'Eden::Performance::TickProfiling();' in main[a:b]
assert 'Eden::RuntimeControl commands' in main[a:b]
assert 'std::fopen' not in source[source.index('void RestartProfiling() {'):source.index('void MemoryPool(')]
assert 'runtime_control.join();' in main[a:b]
