// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
namespace Eden::CpuPolicy {
inline constexpr unsigned GuestCores = 6;
inline constexpr unsigned GpuWorker = GuestCores;
inline constexpr unsigned PinnedWorkers = GuestCores + 1;
inline constexpr std::array<unsigned, GuestCores> JitMiB{256, 96, 96, 96, 96, 96};
constexpr std::uint32_t JitBytes(std::size_t core) {
    return (core < JitMiB.size() ? JitMiB[core] : 16u) * 1024u * 1024u;
}
static_assert(JitMiB[0]+JitMiB[1]+JitMiB[2]+JitMiB[3]+JitMiB[4]+JitMiB[5] == 736);
}
