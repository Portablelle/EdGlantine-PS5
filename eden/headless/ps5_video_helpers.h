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

namespace Eden::VideoDecode {
using Bytes = std::span<const std::uint8_t>;
constexpr std::size_t Alignment = 0x4000;
constexpr std::size_t InputBytes = 0x800000;
constexpr std::size_t Slots = 3; // The documented depth-one PS5 bring-up, not EVO's async rings.

inline std::optional<std::size_t> Align(std::uint64_t size, std::size_t alignment = Alignment) {
    if (!size || alignment < Alignment || (alignment & (alignment - 1)) ||
        size > std::numeric_limits<std::size_t>::max() - (alignment - 1)) return {};
    return (static_cast<std::size_t>(size) + alignment - 1) & ~(alignment - 1);
}

inline std::vector<Bytes> AnnexBNals(Bytes bytes) {
    std::vector<Bytes> units;
    std::size_t begin = 0;
    bool found = false;
    for (std::size_t i = 0; i + 3 <= bytes.size(); ++i) {
        if (bytes[i] || bytes[i + 1] || bytes[i + 2] != 1) continue;
        if (found) {
            auto end = i;
            while (end > begin && bytes[end - 1] == 0) --end;
            if (end == begin || units.size() == 256) return {};
            units.push_back(bytes.subspan(begin, end - begin));
        } else {
            for (std::size_t j = 0; j < i; ++j) if (bytes[j]) return {};
        }
        found = true;
        begin = i + 3;
        i += 2;
    }
    if (!found || begin == bytes.size() || units.size() == 256) return {};
    auto end = bytes.size();
    while (end > begin && bytes[end - 1] == 0) --end;
    if (end == begin) return {};
    units.push_back(bytes.subspan(begin, end - begin));
    for (const auto unit : units) if (unit[0] & 0x80) return {};
    return units;
}

inline bool IsIdr(Bytes bytes) {
    for (auto nal : AnnexBNals(bytes)) if ((nal[0] & 31) == 5) return true;
    return false;
}

// Native Configure may supply avcC; the decoder itself only receives Annex-B access units.
inline std::optional<std::vector<std::uint8_t>> H264Extradata(Bytes bytes) {
    if (bytes.size() > InputBytes) return {};
    if (bytes.empty()) return std::vector<std::uint8_t>{};
    if (!AnnexBNals(bytes).empty()) return std::vector<std::uint8_t>{bytes.begin(), bytes.end()};
    if (bytes.size() < 7 || bytes[0] != 1) return {};
    std::vector<std::uint8_t> result;
    std::size_t pos = 6;
    unsigned count = bytes[5] & 31;
    for (int group = 0; group < 2; ++group) {
        for (unsigned i = 0; i < count; ++i) {
            if (bytes.size() - pos < 2) return {};
            const auto length = (std::size_t{bytes[pos]} << 8) | bytes[pos + 1];
            pos += 2;
            if (!length || length > bytes.size() - pos || result.size() + length + 4 > InputBytes) return {};
            result.insert(result.end(), {0, 0, 0, 1});
            result.insert(result.end(), bytes.begin() + pos, bytes.begin() + pos + length);
            pos += length;
        }
        if (group == 0) {
            if (pos == bytes.size()) return {};
            count = bytes[pos++];
        }
    }
    return result;
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

struct Bits {
    Bytes bytes;
    std::size_t pos{};
    bool valid{true};
    std::uint32_t Read(unsigned count) {
        if (count > 32 || pos > bytes.size() * 8 || count > bytes.size() * 8 - pos) {
            valid = false;
            return 0;
        }
        std::uint32_t value = 0;
        while (count--) { value = (value << 1) | ((bytes[pos / 8] >> (7 - pos % 8)) & 1); ++pos; }
        return value;
    }
    std::uint32_t UE() {
        unsigned zeros = 0;
        while (valid && Read(1) == 0) if (++zeros > 30) { valid = false; return 0; }
        return ((1U << zeros) - 1) + Read(zeros);
    }
    std::int32_t SE() {
        const auto value = UE();
        return value & 1 ? static_cast<std::int32_t>((value + 1) / 2) : -static_cast<std::int32_t>(value / 2);
    }
};
inline std::vector<std::uint8_t> Rbsp(Bytes nal, std::size_t limit = InputBytes) {
    std::vector<std::uint8_t> result;
    unsigned zeros = 0;
    for (std::size_t i = 1; i < nal.size() && result.size() < limit; ++i) {
        if (zeros >= 2 && nal[i] == 3) {
            if (i + 1 == nal.size() || nal[i + 1] > 3) return {};
            zeros = 0;
            continue;
        }
        result.push_back(nal[i]);
        zeros = nal[i] == 0 ? zeros + 1 : 0;
    }
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

struct Picture {
    std::uint32_t coded_width{}, coded_height{}, width{}, height{}, left{}, top{}, level{};
    std::uint32_t matrix{2}; // AVCOL_SPC_UNSPECIFIED, native service keeps its BT.709 default.
    bool full_range{};
};
inline std::optional<Picture> H264Sps(Bytes nal) {
    auto data = Rbsp(nal);
    Bits b{data};
    const auto profile = b.Read(8);
    b.Read(8); const auto level = b.Read(8); b.UE(); // constraints, level, SPS id
    if (!level || level > 52) return {};
    if (profile == 100) {
        if (b.UE() != 1 || b.UE() != 0 || b.UE() != 0) return {}; // 8-bit 4:2:0 only
        b.Read(1);
        if (b.Read(1)) {
            for (int list = 0; list < 8; ++list) {
                if (!b.Read(1)) continue;
                int last = 8, next = 8;
                for (int i = 0; i < (list < 6 ? 16 : 64); ++i) {
                    if (next) next = static_cast<int>((std::int64_t{last} + b.SE() + 256) & 255);
                    last = next ? next : last;
                }
            }
        }
    } else if (profile != 66 && profile != 77) return {};
    if (b.UE() > 12) return {};
    const auto poc = b.UE();
    if (poc == 0) { if (b.UE() > 12) return {}; }
    else if (poc == 1) {
        b.Read(1); b.SE(); b.SE();
        const auto cycle = b.UE();
        if (cycle > 256) return {};
        for (unsigned i = 0; i < cycle; ++i) b.SE();
    } else if (poc != 2) return {};
    if (b.UE() > 4) return {}; // The documented depth-one decoder has four DPB frames.
    b.Read(1);
    const auto mw = b.UE(), mh = b.UE();
    if (mw >= 240 || mh >= 136 || !b.Read(1)) return {}; // progressive only
    b.Read(1);
    Picture p;
    p.level = level;
    p.coded_width = (mw + 1) * 16; p.coded_height = (mh + 1) * 16;
    std::uint32_t right = 0, bottom = 0;
    if (b.Read(1)) { p.left = b.UE(); right = b.UE(); p.top = b.UE(); bottom = b.UE(); }
    if (p.left >= p.coded_width / 2 || right >= p.coded_width / 2 - p.left ||
        p.top >= p.coded_height / 2 || bottom >= p.coded_height / 2 - p.top) return {};
    p.left *= 2; p.top *= 2;
    p.width = p.coded_width - p.left - right * 2;
    p.height = p.coded_height - p.top - bottom * 2;
    if (b.Read(1)) { // VUI prefix: colour information precedes timing/HRD.
        if (b.Read(1) && b.Read(8) == 255) { b.Read(16); b.Read(16); }
        if (b.Read(1)) b.Read(1);
        if (b.Read(1)) {
            b.Read(3); p.full_range = b.Read(1);
            if (b.Read(1)) { b.Read(8); b.Read(8); p.matrix = b.Read(8); }
        }
    }
    if (!b.valid || p.matrix > 14) return {};
    return p;
}

struct Vp9Header {
    bool shown{}, existing{}, key{};
    unsigned profile{};
};
inline std::optional<Vp9Header> ParseVp9(Bytes bytes) {
    Bits b{bytes};
    if (b.Read(2) != 2) return {};
    Vp9Header h;
    h.profile = b.Read(1); h.profile |= b.Read(1) << 1;
    if (h.profile == 3 && b.Read(1)) return {};
    h.existing = b.Read(1);
    if (h.existing) { b.Read(3); h.shown = true; }
    else { h.key = !b.Read(1); h.shown = b.Read(1); }
    if (!b.valid) return {};
    return h;
}
} // namespace Eden::VideoDecode
