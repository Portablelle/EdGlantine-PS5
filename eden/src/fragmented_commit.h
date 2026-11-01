// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <span>

namespace Common::FragmentedCommit {
struct Piece {
    std::uintptr_t address;
    std::size_t size;
    std::int64_t physical;
};

// Ops must not allocate: this runs inside malloc. The caller owns the reserved
// virtual range and serializes access to scratch. Successful mappings stay live;
// on failure every acquired piece is rolled back before the caller can retry.
template <class Ops>
bool Commit(std::uintptr_t begin, std::size_t size, std::size_t page,
            std::span<Piece> scratch, Ops& ops, std::size_t& count) noexcept {
    count = 0;
    if (begin == 0 || page == 0 || size == 0 || begin % page || size % page ||
        size > (std::numeric_limits<std::uintptr_t>::max)() - begin) {
        return false;
    }
    std::size_t done = 0, block = size;
    while (done < size && count < scratch.size()) {
        block = (std::min)(block, size - done);
        std::int64_t physical = -1;
        if (!ops.Allocate(block, physical)) {
            if (block == page) break;
            block = (std::max)(page, block / 2 / page * page);
            continue;
        }
        const Piece piece{begin + done, block, physical};
        if (!ops.Map(piece)) {
            ops.ReleaseUnmapped(piece);
            break;
        }
        scratch[count++] = piece;
        done += block;
    }
    if (done != size) {
        while (count != 0) ops.Rollback(scratch[--count]);
        return false;
    }
    return true;
}
} // namespace Common::FragmentedCommit
