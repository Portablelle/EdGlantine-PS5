// SPDX-License-Identifier: GPL-3.0-or-later
#include "profiling_session.h"
#include "performance.h"
#include "native_gpu_profile.h"
#include "native_cpu_profile.h"
#include "video_core/gpu_split.h"
#include "video_core/native_draw_memo.h"
#include "video_core/native_resource_memo.h"
#ifdef EDEN_NX2_PS5_PROTO
#include "video_core/native_wait_profile.h"
#include "video_core/native_draw_indirect.h"
#include "video_core/buffer_cache/readback_statistics.h"
#endif
namespace Eden::Performance {
ProfilingSession::ProfilingSession() : initial_deadline{NowNs() + 180'000'000'000LL} {}
ProfilingSession::~ProfilingSession() { Stop(); }
void ProfilingSession::Stop() {
    detailed_until_ns.store(0, std::memory_order_relaxed);
    dev_marks.store(false, std::memory_order_relaxed);
    Vulkan::NativeGpuProfile::enabled.store(false, std::memory_order_relaxed);
    timers_on.store(false, std::memory_order_relaxed);
    vulkan_cost_enabled.store(false, std::memory_order_relaxed);
#ifdef EDEN_NX2_PS5_PROTO
    VideoCommon::ReadbackStatistics::enabled.store(false, std::memory_order_relaxed);
#endif
}

void ProfilingSession::Restart() {
    next_report = 0;
    reports = 0;
#ifdef EDEN_NX2_PS5_PROTO
    const auto epoch = VideoCommon::NativeWaitProfile::Restart();
    std::fprintf(stderr, "NX2_PROFILE_REFRESH epoch=%llu mono_ns=%lld\n",
                 static_cast<unsigned long long>(epoch), NowNs());
#endif
    detailed_until_ns.store(NowNs() + 20'000'000'000LL, std::memory_order_relaxed);
    dev_marks.store(true, std::memory_order_relaxed);
    Vulkan::NativeGpuProfile::epoch.fetch_add(1, std::memory_order_relaxed);
    Vulkan::NativeGpuProfile::enabled.store(true, std::memory_order_relaxed);
}

void ProfilingSession::Tick() {
    // Diagnostic prototype: bounded aggregate sampling, no PC sampling or GPU waits added.
    if (initial_deadline && NowNs() >= initial_deadline) {
        initial_deadline = 0;
        if (!detailed_until_ns.load(std::memory_order_relaxed))
            dev_marks.store(false, std::memory_order_relaxed);
    }
    const auto detailed_deadline = detailed_until_ns.load(std::memory_order_relaxed);
    if (detailed_deadline && NowNs() >= detailed_deadline) {
        dev_marks.store(false, std::memory_order_relaxed);
        Vulkan::NativeGpuProfile::enabled.store(false, std::memory_order_relaxed);
        detailed_until_ns.store(0, std::memory_order_relaxed);
    }
    if (reports < 36) {
#ifdef EDEN_NX2_PS5_PROTO
        VideoCommon::ReadbackStatistics::enabled.store(true, std::memory_order_relaxed);
#endif
        timers_on.store(true, std::memory_order_relaxed);
        vulkan_cost_enabled.store(true, std::memory_order_relaxed);
        const auto now = NowNs();
        if (!next_report || now >= next_report) {
            next_report = now + 5'000'000'000LL;
            ReportRuntime(now);
            ::Eden::NativeCpuProfile::Report(now);
            VideoCommon::NativeDrawMemo::Report(now);
            VideoCommon::NativeResourceMemo::Report(now);
            VideoCommon::SplitPerformance::Report(now);
#ifdef EDEN_NX2_PS5_PROTO
            Tegra::NativeDrawIndirect::Report();
            VideoCommon::ReadbackStatistics::Report(now);
#endif
            if (++reports == 36) {
#ifdef EDEN_NX2_PS5_PROTO
                VideoCommon::ReadbackStatistics::enabled.store(false, std::memory_order_relaxed);
#endif
                dev_marks.store(false, std::memory_order_relaxed);
                vulkan_cost_enabled.store(false, std::memory_order_relaxed);
                timers_on.store(false, std::memory_order_relaxed);
            }
        }
    }
}

}
