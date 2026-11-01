// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdio>
#include <array>
#include "performance.h"
namespace Eden::NativeCpuProfile {
inline std::array<Performance::Totals, 10> totals;
inline constexpr std::array names{"pointer_sync", "stage_resources", "ssbo_binding",
                                  "fill_views", "host_stage_bind", "push_images", "descriptor_acquire",
                                  "host_uniform", "host_storage", "host_texel"};
class Scope {
public:
    explicit Scope(unsigned index_) : index{index_}, begin{Performance::MarkStart()} {}
    ~Scope() {
        if (!begin) return;
        const auto elapsed = Performance::NowNs() - begin;
        if (elapsed < 0) return;
        totals[index].nanoseconds.fetch_add(elapsed, std::memory_order_relaxed);
        totals[index].calls.fetch_add(1, std::memory_order_relaxed);
    }
private:
    unsigned index;
    long long begin;
};
inline void Report(long long now) {
            for (unsigned i = 0; i < ::Eden::NativeCpuProfile::totals.size(); ++i) {
                const auto& total = ::Eden::NativeCpuProfile::totals[i];
                std::fprintf(stderr, "NX2_CPU_DETAIL mono_ns=%lld phase=%s calls=%llu ns=%llu\n",
                             now, ::Eden::NativeCpuProfile::names[i], total.calls.load(), total.nanoseconds.load());
            }

}

}
