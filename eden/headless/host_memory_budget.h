// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <atomic>
#include <cstddef>
#include <cstdio>
#include <utility>
#include <vector>
#include "core/file_sys/vfs/read_cache_budget.h"
#include "descriptor_memory.h"

namespace Eden::HostMemory {
inline constexpr std::size_t ReadCacheLimit = FileSys::ReadCacheMemory::Limit;
inline auto& read_live = FileSys::ReadCacheMemory::live;
inline auto& read_peak = FileSys::ReadCacheMemory::peak;
inline auto& read_bypass = FileSys::ReadCacheMemory::bypass;
using ReadBytes = std::vector<unsigned char, FileSys::ReadCacheMemory::Allocator<unsigned char>>;
inline bool Prepare(ReadBytes& data, std::size_t bytes) {
    return FileSys::ReadCacheMemory::Prepare(data, bytes);
}
template<class Blocks> void Release(Blocks& blocks) {
    // Cache eviction chooses what to discard; the allocator owns accounting.
    blocks.clear();
}
inline void Report(const char* phase) {
    std::fprintf(stdout, "EDEN_HOST_MEMORY phase=%s read_cache=%zu read_peak=%zu read_limit=%zu read_bypass=%zu descriptors=%zu descriptor_peak=%zu\n",
        phase, read_live.load(), read_peak.load(), ReadCacheLimit, read_bypass.load(),
        descriptor_live.load(), descriptor_peak.load());
}
} // namespace Eden::HostMemory
