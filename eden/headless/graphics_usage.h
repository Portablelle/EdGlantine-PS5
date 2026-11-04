// SPDX-License-Identifier: GPL-3.0-or-later
// "Memory in use" the texture cache weighs against its marks on the console (tools/
// prepare-vulkan-port.py, Device::GetDeviceMemoryUsage): the budget less the pool's largest free
// block, less kReserve.
//
// The marks assume graphics may use the whole 6 GiB budget: the collector evicted what is unused
// from 1.6 GiB of largest free block on and evicted hard from 0.8 GiB on. The CPU shares the pool
// and had taken 6.4 GiB of it (3.3 GiB of guest RAM filled during a load), and the pool went from
// 4.4 GiB to 0.63 GiB of largest free block in 10 s: the window where the collector could act
// lasted 1 to 2 s, and a 128 MiB staging buffer was refused (issue #20). The last 1.25 GiB of the
// pool are not counted as room for graphics, so the collector starts at 2.85 GiB of largest free
// block and evicts hard at 2.05 GiB, about 2 s of such a load earlier, and keeps room for what the
// CPU asks in one piece (486 MiB at most seen, 361 MiB for a decode, 128 MiB for staging).
#pragma once
#include <cstdint>

namespace Eden::GraphicsUsage {
inline constexpr std::uint64_t kReserve = std::uint64_t{1280} << 20;
inline constexpr std::uint64_t kFullCapacity = std::uint64_t{6400} << 20;

// `budget`: the device budget the marks come from; `largest_free`: the pool's largest free block;
// `capacity`: its largest free block when the device was made (0: unknown). Where the pool could
// never give graphics 6.4 GiB, the room left is scaled up so the marks become a quarter and an
// eighth of what it could give.
constexpr std::uint64_t Usage(std::uint64_t budget, std::uint64_t largest_free, std::uint64_t capacity) {
    const std::uint64_t room = largest_free > kReserve ? largest_free - kReserve : 0;
    const double scale = capacity != 0 && capacity < kFullCapacity
                             ? static_cast<double>(kFullCapacity) / static_cast<double>(capacity)
                             : 1.0;
    const auto free_bytes = static_cast<std::uint64_t>(static_cast<double>(room) * scale);
    return budget > free_bytes ? budget - free_bytes : 0;
}
} // namespace Eden::GraphicsUsage
