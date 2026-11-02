// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <atomic>
#include <cerrno>
#include <cstddef>

namespace Eden::HostFiles {
// The process also needs descriptors for logs, services, drivers and other VFSes.
// Keep a small LRU rather than letting one VFS retain 512 host files.
inline constexpr std::size_t MaxCachedOpenFiles = 64;
inline std::atomic<unsigned> exhausted_opens{};
inline void Reset() { exhausted_opens.store(0, std::memory_order_relaxed); }
inline void ObserveOpenError(int error) {
    if (error == EMFILE || error == ENFILE)
        exhausted_opens.fetch_add(1, std::memory_order_relaxed);
}
inline bool Exhausted() { return exhausted_opens.load(std::memory_order_relaxed) != 0; }
} // namespace Eden::HostFiles
