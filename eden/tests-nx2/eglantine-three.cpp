// SPDX-License-Identifier: GPL-3.0-or-later
#include "fragmented_commit.h"
#include "staging_buffers.h"
#include "core/hle/service/auto_stub_reports.h"
#include <array>
#include <atomic>
#include <cassert>
#include <cstdio>
#include <map>
#include <thread>
#include <vector>

namespace {
constexpr std::uint64_t MiB = 1ULL << 20;
struct Entry {
    std::vector<unsigned char> mapped_span;
    unsigned log2_level;
    bool deferred;
    unsigned tick;
};
struct Level {
    std::vector<Entry> entries;
    std::size_t delete_index = 0, iterate_index = 0;
};
void Staging() {
    using namespace Eden::StagingBuffers;
    static_assert(!Exact(16 * MiB, true));
    static_assert(Exact(16 * MiB + 1, true));
    static_assert(!Exact(341 * MiB, false));
    static_assert(Size(341 * MiB, 29, true) == 352 * MiB);
    static_assert(Size(341 * MiB, 29, false) == 512 * MiB);
    static_assert(Holds(352 * MiB, 29) < 400 * MiB);
    static_assert(Holds(0, 29) == 512 * MiB);
    Level level{{{{8}, 4, false, 1}, {{8}, 4, true, 1}, {{8}, 4, false, 9}}};
    level.delete_index = level.iterate_index = 3;
    const auto idle = [](const Entry& entry) { return !entry.deferred && entry.tick < 5; };
    const auto released = ReleaseFrom(level, idle);
    assert(released.buffers == 1 && released.bytes == 1);
    assert(level.entries.size() == 2 && level.entries[0].deferred);
    assert(level.delete_index == 0 && level.iterate_index == 0);
    assert(ReleaseFrom(level, idle).buffers == 0);
    level.entries[0].deferred = false;
    level.entries[1].tick = 1;
    assert(ReleaseFrom(level, idle).buffers == 2);
    assert(level.entries.empty());
}
struct Ops {
    std::size_t max_block = 8, available = 64;
    int fail_map = -1, maps = 0;
    std::int64_t next = 100;
    std::map<std::int64_t, std::size_t> live;
    std::vector<std::uintptr_t> mapped, rolled_back;
    bool Allocate(std::size_t bytes, std::int64_t& physical) {
        if (bytes > max_block || bytes > available) return false;
        physical = next++;
        live.emplace(physical, bytes);
        available -= bytes;
        return true;
    }
    bool Map(const Common::FragmentedCommit::Piece& piece) {
        if (maps++ == fail_map) return false;
        mapped.push_back(piece.address);
        return true;
    }
    void ReleaseUnmapped(const Common::FragmentedCommit::Piece& piece) {
        assert(live.erase(piece.physical) == 1);
        available += piece.size;
    }
    void Rollback(const Common::FragmentedCommit::Piece& piece) {
        assert(mapped.back() == piece.address);
        mapped.pop_back();
        rolled_back.push_back(piece.address);
        ReleaseUnmapped(piece);
    }
};
void Fragmentation() {
    using namespace Common::FragmentedCommit;
    std::array<Piece, 16> scratch;
    std::size_t count;
    Ops whole;
    assert(Commit(128, 8, 2, scratch, whole, count) && count == 1);
    Ops split;
    assert(Commit(128, 30, 2, scratch, split, count) && count > 1);
    std::size_t total = 0;
    for (std::size_t i = 0; i < count; ++i) {
        assert(scratch[i].address == 128 + total);
        assert(scratch[i].size % 2 == 0 && scratch[i].size <= 8);
        total += scratch[i].size;
    }
    assert(total == 30 && split.available == 34);
    const auto pieces = count;
    // Every mapping failure must give back the failed allocation and prior pieces.
    for (std::size_t fail = 0; fail < pieces; ++fail) {
        Ops failed; failed.fail_map = static_cast<int>(fail);
        assert(!Commit(128, 30, 2, scratch, failed, count));
        assert(count == 0 && failed.live.empty() && failed.mapped.empty() && failed.available == 64);
    }
    Ops exhausted; exhausted.available = 10;
    assert(!Commit(128, 30, 2, scratch, exhausted, count));
    assert(exhausted.live.empty() && exhausted.available == 10);
    Ops no_slots;
    assert(!Commit(128, 30, 2, std::span<Piece>{scratch}.first(1), no_slots, count));
    assert(no_slots.live.empty() && no_slots.available == 64);
    Ops invalid;
    assert(!Commit(0, 8, 2, scratch, invalid, count));
    assert(!Commit(129, 8, 2, scratch, invalid, count));
    assert(!Commit(128, 7, 2, scratch, invalid, count));
    assert(!Commit(128, 8, 0, scratch, invalid, count));
    assert(!Commit(UINTPTR_MAX - 1, 8, 2, scratch, invalid, count));
    assert(invalid.live.empty() && invalid.maps == 0);
}
void Reports() {
    Service::AutoStubReports reports;
    assert(reports.ShouldReport(false, "camera", 29));
    assert(reports.ShouldReport(false, "camera", 29));
    assert(reports.ShouldReport(true, "camera", 29));
    assert(!reports.ShouldReport(true, "camera", 29));
    assert(reports.ShouldReport(true, "other", 29));
    assert(reports.ShouldReport(true, "camera", 30));
    assert(reports.ShouldReport(false, "camera", 29));
    std::atomic<int> first{0};
    std::vector<std::thread> workers;
    for (int i = 0; i < 8; ++i) workers.emplace_back([&] {
        for (int j = 0; j < 1000; ++j) if (reports.ShouldReport(true, "concurrent", 1)) ++first;
    });
    for (auto& worker : workers) worker.join();
    assert(first == 1);
}
}
int main() {
    Staging(); Fragmentation(); Reports();
    std::puts("PASS: staging sizes/lifetime, fragmented commit/rollback, auto-stub policy and concurrent deduplication");
}
