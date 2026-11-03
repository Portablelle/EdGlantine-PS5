// SPDX-License-Identifier: GPL-3.0-only
// Adapted from sainsaji/EVO-PLAYER-PS5 a54dcf516e9cfda4c26d78733bf5ccb8c10e7e0b (GPL-3.0)
// Bounded packet adaptation for the synchronous, 8-bit NV12 Eden backend.
#pragma once
#include <array>
#include <cstdint>
#include <limits>
#include <optional>
#include <span>
#include <vector>
#include "video_core/host1x/video_decode.h"

namespace Eden::VideoDecode {
constexpr std::size_t Alignment = 0x4000;
constexpr std::size_t Slots = 3; // The documented depth-one PS5 bring-up, not EVO's async rings.

inline std::optional<std::size_t> Align(std::uint64_t size, std::size_t alignment = Alignment) {
    if (!size || alignment < Alignment || (alignment & (alignment - 1)) ||
        size > std::numeric_limits<std::size_t>::max() - (alignment - 1)) return {};
    return (static_cast<std::size_t>(size) + alignment - 1) & ~(alignment - 1);
}

struct Superframe {
    std::array<Bytes, 8> frames{};
    std::size_t count{};
};
inline std::optional<Superframe> SplitVp9(Bytes bytes) {
    if (bytes.empty()) return {};
    Superframe result;
    const auto marker = bytes.back();
    if ((marker & 0xe0) != 0xc0) {
        result.frames[result.count++] = bytes;
        return result;
    }
    const std::size_t count = (marker & 7) + 1;
    const std::size_t magnitude = ((marker >> 3) & 3) + 1;
    const auto index_size = 2 + count * magnitude;
    if (index_size > bytes.size() || bytes[bytes.size() - index_size] != marker) return {};
    const auto payload = bytes.size() - index_size;
    std::size_t index = payload + 1, offset = 0;
    for (std::size_t i = 0; i < count; ++i) {
        std::size_t size = 0;
        for (std::size_t j = 0; j < magnitude; ++j) size |= std::size_t{bytes[index++]} << (8 * j);
        if (!size || size > payload - offset) return {};
        result.frames[result.count++] = bytes.subspan(offset, size);
        offset += size;
    }
    if (offset != payload) return {};
    return result;
}

inline std::optional<bool> IsBSlice(Bytes nal) {
    auto data = Rbsp(nal, 16);
    Bits bits{data};
    bits.UE(); // first_mb_in_slice
    const auto type = bits.UE();
    if (!bits.valid || type > 9) return {};
    return type % 5 == 1;
}

struct Vp9Header {
    bool shown{}, existing{}, key{}, color_config{}, full_range{};
    unsigned profile{}, matrix{2};
};
inline std::optional<Vp9Header> ParseVp9(Bytes bytes) {
    Bits b{bytes};
    if (b.Read(2) != 2) return {};
    Vp9Header h;
    h.profile = b.Read(1); h.profile |= b.Read(1) << 1;
    if (h.profile != 0) return {}; // Only the 8-bit profile-0 backend is supported.
    h.existing = b.Read(1);
    if (h.existing) { b.Read(3); h.shown = true; }
    else {
        h.key = !b.Read(1); h.shown = b.Read(1);
        const bool resilient = b.Read(1);
        const bool intra_only = !h.key && !h.shown && b.Read(1);
        if (!h.key && !resilient) b.Read(2); // reset_frame_context
        if (h.key || intra_only) {
            if (b.Read(24) != 0x498342) return {};
            h.color_config = true;
            if (h.key) {
                const auto space = b.Read(3);
                // VP9 color_space to FFmpeg AVColorSpace, matching the software decoder.
                constexpr unsigned matrices[]{2, 5, 1, 6, 7, 9};
                if (space >= 6) return {}; // Reserved / RGB are invalid for profile 0.
                h.matrix = matrices[space];
                h.full_range = b.Read(1);
            } else h.matrix = 5; // Profile-0 intra-only implies BT.601, studio range.
        }
    }
    if (!b.valid) return {};
    return h;
}
} // namespace Eden::VideoDecode
