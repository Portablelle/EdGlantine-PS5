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

// What orders a frame picture for display, from the first slice header of its access unit
// (7.3.3, 8.2.1). Fields are absent from the SPS this backend admits (frame_mbs_only).
struct H264SliceOrder {
    bool idr{}, reference{};
    std::uint32_t poc_lsb{};
};
inline std::optional<H264SliceOrder> ParseH264SliceOrder(Bytes nal, const Picture& sps) {
    if (nal.empty()) return {};
    auto data = Rbsp(nal, 32);
    Bits bits{data};
    bits.UE(); // first_mb_in_slice
    if (bits.UE() > 9) return {}; // slice_type
    if (bits.UE() > 255) return {}; // pic_parameter_set_id
    bits.Read(sps.frame_num_bits);
    H264SliceOrder order;
    order.idr = (nal[0] & 31) == 5;
    order.reference = (nal[0] & 0x60) != 0;
    if (order.idr) bits.UE(); // idr_pic_id
    if (sps.poc_type == 0) order.poc_lsb = bits.Read(sps.poc_lsb_bits);
    if (!bits.valid) return {};
    return order;
}

// Display order of H.264 frame pictures (8.2.1.1 for pic_order_cnt_type 0; type 2 outputs in
// decode order). Keys grow with display order across IDR pictures. Memory management
// operation 5, which also restarts the count, is not tracked.
class H264DisplayOrder {
public:
    std::optional<std::uint64_t> Key(const H264SliceOrder& order, const Picture& sps) {
        if (order.idr) {
            ++epoch;
            prev_msb = prev_lsb = 0;
            decode_index = 0;
        }
        std::int64_t count;
        if (sps.poc_type == 2) {
            count = decode_index++;
        } else if (sps.poc_type == 0) {
            const std::int64_t max_lsb = std::int64_t{1} << sps.poc_lsb_bits;
            const std::int64_t lsb = order.poc_lsb;
            std::int64_t msb = prev_msb;
            if (lsb < prev_lsb && prev_lsb - lsb >= max_lsb / 2) msb += max_lsb;
            else if (lsb > prev_lsb && lsb - prev_lsb > max_lsb / 2) msb -= max_lsb;
            count = msb + lsb;
            if (order.reference) { prev_msb = msb; prev_lsb = lsb; }
        } else return {};
        if (count < -(std::int64_t{1} << 31) || count >= (std::int64_t{1} << 31)) return {};
        return (epoch << 32) | static_cast<std::uint32_t>(count + (std::int64_t{1} << 31));
    }

private:
    std::uint64_t epoch{};
    std::int64_t prev_msb{}, prev_lsb{}, decode_index{};
};

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
