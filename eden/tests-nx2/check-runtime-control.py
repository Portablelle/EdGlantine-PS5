#!/usr/bin/env python3
"""Exercise production command polling and profiling teardown without HUD calls."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / 'headless/performance.cpp').read_text()
start = source.index('ProfilingSession::ProfilingSession()')
end = source.index('    if (reports < 36) {', start)
implementation = source[start:end] + '}\n'
with tempfile.TemporaryDirectory(prefix='nx2-runtime-control-') as directory:
    temp = Path(directory)
    fixture = r'''
#include <atomic>
#include <cassert>
#include <cstdio>
#include <fstream>
#include <string>
#include <thread>
#include <filesystem>
#include "runtime_control.h"
#include "profiling_session.h"
static long long clock_ns=1;
long long MonotonicNs(){return clock_ns;}
long long NowNs(){return clock_ns;}
std::atomic<long long> detailed_until_ns{};
std::atomic<bool> dev_marks{},timers_on{},vulkan_cost_enabled{};
namespace VideoCommon {
struct NativeWaitProfile {static unsigned Restart(){static unsigned epoch;return ++epoch;}};
namespace ReadbackStatistics {std::atomic<bool> enabled{false};}
}
namespace Vulkan::NativeGpuProfile {
std::atomic<unsigned long long> epoch{1};
std::atomic<bool> enabled{false};
}
'''
    fixture += '\nnamespace Eden::Performance {\n' + implementation + '}\n'
    fixture += r'''
int main(int argc,char**argv){
 assert(argc==2);const std::filesystem::path root=argv[1];
 auto request=[&](const char* file,const char* nonce){std::ofstream(root/file)<<nonce;};
 unsigned enables=0;
 dev_marks=true; // Preserve diagnostics explicitly configured before worker startup.
 {
 Eden::Performance::ProfilingSession profiling;
 assert(dev_marks);
 Eden::RuntimeControl controller((root/"split-enable.request").string(),(root/"profile-refresh.request").string());
 auto tick=[&]{controller.Poll(clock_ns,[&]{++enables;},[&]{profiling.Restart();});profiling.Tick();};
 request("split-enable.request","one");request("profile-refresh.request","one");
 tick();assert(enables==1);
 assert(!std::filesystem::exists(root/"split-enable.request"));
 assert(!std::filesystem::exists(root/"profile-refresh.request"));
 assert(dev_marks && Vulkan::NativeGpuProfile::enabled && detailed_until_ns==20'000'000'001LL);
 const auto epoch=Vulkan::NativeGpuProfile::epoch.load();
 clock_ns+=1'000'000'000LL;
 request("split-enable.request","one");request("profile-refresh.request","one");
 tick();assert(enables==1 && Vulkan::NativeGpuProfile::epoch==epoch);
 clock_ns=21'000'000'001LL;tick();
 assert(!dev_marks && !Vulkan::NativeGpuProfile::enabled && detailed_until_ns==0);
 // Terminate during a freshly armed capture, before its deadline.
 request("profile-refresh.request","two");clock_ns+=1'000'000'000LL;tick();
 timers_on=true;vulkan_cost_enabled=true;VideoCommon::ReadbackStatistics::enabled=true;
 assert(dev_marks && detailed_until_ns>clock_ns);
 }
 assert(!dev_marks && !timers_on && !vulkan_cost_enabled);
 assert(!Vulkan::NativeGpuProfile::enabled && !VideoCommon::ReadbackStatistics::enabled);
 assert(detailed_until_ns==0);
 // A fresh session owns fresh nonce/report state, even on the same thread.
 {
 Eden::Performance::ProfilingSession profiling;
 Eden::RuntimeControl next((root/"split-enable.request").string(),(root/"profile-refresh.request").string());
 request("split-enable.request","one");request("profile-refresh.request","one");
 next.Poll(clock_ns,[&]{++enables;},[&]{profiling.Restart();});profiling.Tick();
 assert(enables==2 && dev_marks);
 }
 assert(!dev_marks && !Vulkan::NativeGpuProfile::enabled && detailed_until_ns==0);
 std::puts("RUNTIME_CONTROL_OK: no HUD, consume once, expiry, early teardown, fresh session");
}
'''
    cpp = temp / 'test.cpp'
    cpp.write_text(fixture)
    subprocess.run([os.environ.get('CXX', 'clang++'), '-std=c++20', '-O1', '-g',
                    '-fsanitize=address,undefined', '-pthread', '-DEDEN_NX2_PS5_PROTO',
                    '-I', str(root / 'headless'), str(cpp), '-o', str(temp / 'test')], check=True)
    subprocess.run([str(temp / 'test'), str(temp)], check=True)
telemetry = source[source.index('unsigned GpuBusyPercent() {'):source.index('void MemoryPool(')]
assert 'RequestEnable' not in telemetry and 'std::fopen' not in source[start:source.index('void MemoryPool(')]
main = (root / 'headless/main.cpp').read_text()
a = main.index('std::jthread runtime_control')
b = main.index('system.ShutdownMainProcess();', a)
assert 'Eden::Performance::ProfilingSession profiling;' in main[a:b]
assert 'Eden::RuntimeControl commands' in main[a:b]
assert 'profiling.Tick();' in main[a:b] and 'runtime_control.join();' in main[a:b]
