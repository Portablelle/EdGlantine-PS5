"""Exhaustively compare production ASTC opacity with pre-UB-034 logic; run on dedie."""
from pathlib import Path
import platform
import subprocess
import tempfile

assert platform.system() == 'Linux', 'Compile on dedie'
root = Path(__file__).resolve().parents[1]
source = Path((root / '.local/headless-cache').read_text().strip()) / 'source/src'
text = (source / 'video_core/textures/astc.cpp').read_text()


def function(signature):
    start = text.index(signature)
    brace = text.index('{', start)
    end, depth = brace + 1, 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end] + '\n'


opaque = function('bool IsOpaque(')
# This assertion fails on main even though the old opacity results are correct.
assert 'mode_infos[' in opaque and 'MakeBlockModeInfos()' in opaque, \
    'IsOpaque must use the precomputed block-mode table'
assert 'DecodeBlockInfo(' not in opaque, 'IsOpaque must not decode modes per block'

# Frozen verbatim from patched main bce56e2 (same as selevet 114b5b0's parent).
old_opaque = r'''bool IsOpaque(std::span<const uint8_t> data) {
    // Endpoint modes with an alpha channel: LDR luminance+alpha (4, 5), RGB scale + two alpha
    // (10), LDR RGBA (12, 13) and HDR RGBA (14, 15).
    constexpr u32 AlphaModes = (1U << 4) | (1U << 5) | (1U << 10) | (1U << 12) | (1U << 13) |
                               (1U << 14) | (1U << 15);
    for (size_t offset = 0; offset + 16 <= data.size(); offset += 16) {
        const std::span<const u8> block = data.subspan(offset, 16);
        InputBitStream strm(block);
        const TexelWeightParams params = DecodeBlockInfo(strm);
        if (params.m_bError) {
            continue; // decodes to the opaque error colour
        }
        if (params.m_bVoidExtentLDR || params.m_bVoidExtentHDR) {
            // One RGBA16 colour in bits 64-127: UNORM16, or FP16 for HDR.
            const u32 alpha = block[14] | (u32{block[15]} << 8);
            if (alpha != (params.m_bVoidExtentHDR ? 0x3C00U : 0xFFFFU)) {
                return false;
            }
            continue;
        }
        const u32 partitions = strm.ReadBits<2>() + 1;
        if (partitions == 4 && params.m_bDualPlane) {
            continue;
        }
        if (partitions == 1) {
            if ((AlphaModes >> strm.ReadBits<4>()) & 1) {
                return false;
            }
            continue;
        }
        strm.ReadBits<10>(); // partition index
        const u32 base_cem = strm.ReadBits<6>();
        const u32 base_mode = base_cem & 3;
        if (base_mode == 0) {
            if ((AlphaModes >> (base_cem >> 2)) & 1) {
                return false;
            }
            continue;
        }
        // The rest of the per-partition modes sit just below the weights (DecompressBlock).
        const u32 weight_bits = params.GetPackedBitSize();
        if (weight_bits < 24 || weight_bits > 96) {
            continue;
        }
        const u32 extra_bits = partitions == 2 ? 2 : partitions == 3 ? 5 : 8;
        const u32 extra_offset = 128 - weight_bits - extra_bits;
        u32 extra = 0;
        for (u32 bit = 0; bit < extra_bits; ++bit) {
            const u32 position = extra_offset + bit;
            extra |= ((block[position / 8] >> (position % 8)) & 1U) << bit;
        }
        u32 cem = ((extra << 6) | base_cem) >> 2;
        const u32 classes = cem;
        cem >>= partitions;
        for (u32 i = 0; i < partitions; ++i) {
            const u32 mode = ((base_mode - (((classes >> i) & 1) != 0 ? 0 : 1)) << 2) |
                             ((cem >> (2 * i)) & 3);
            if ((AlphaModes >> mode) & 1) {
                return false;
            }
        }
    }
    return true;
}
'''

cpp = r'''
#include <array>
#include <bit>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <initializer_list>
#include <span>
using u8 = uint8_t;
using u16 = uint16_t;
using u32 = uint32_t;
using u64 = uint64_t;
static u64 decode_calls = 0;
'''
# Compile the real reader, weight packing and decoder, without unrelated decompression.
cpp += function('class InputBitStream {') + ';\n'
cpp += text[text.index('enum class IntegerEncoding'):text.index('namespace Tegra::Texture::ASTC')]
cpp += function('struct TexelWeightParams {') + ';\n'
decoder = function('static TexelWeightParams DecodeBlockInfo(')
cpp += decoder.replace('    TexelWeightParams params;',
                       '    ++decode_calls;\n    TexelWeightParams params;', 1)
cpp += function('struct BlockModeInfo {') + ';\n'
cpp += function('static std::array<BlockModeInfo, 2048> MakeBlockModeInfos(')
cpp += old_opaque.replace('bool IsOpaque(', 'bool OldIsOpaque(', 1) + '\n'
cpp += opaque
cpp += r'''
using Block = std::array<u8, 16>;
static u64 cases = 0;

static void Put(Block& block, u32 start, u32 bits, u32 value) {
    for (u32 bit = 0; bit < bits; ++bit) {
        const u32 pos = start + bit;
        block[pos / 8] = static_cast<u8>((block[pos / 8] & ~(1U << (pos % 8))) |
                                       (((value >> bit) & 1U) << (pos % 8)));
    }
}

static bool Compare(std::span<const u8> data) {
    const bool expected = OldIsOpaque(data);
    const u64 before = decode_calls;
    const bool actual = IsOpaque(data);
    assert(decode_calls == before); // No mode decoding after table initialization.
    ++cases;
    if (actual != expected) {
        std::fprintf(stderr, "Opacity mismatch, case %llu:",
                     static_cast<unsigned long long>(cases));
        for (u8 byte : data) std::fprintf(stderr, " %02x", byte);
        std::fprintf(stderr, "\nold=%d new=%d\n", expected, actual);
        std::abort();
    }
    return actual;
}

int main() {
    assert(IsOpaque({}));
    assert(decode_calls == 2048); // The actual table builder runs once.
    assert(IsOpaque({}));
    assert(decode_calls == 2048);
    const auto infos = MakeBlockModeInfos();
    bool saw_error = false, saw_void = false, saw_dual = false;
    bool saw_small_weights = false, saw_large_weights = false;
    for (u32 mode = 0; mode < 2048; ++mode) {
        Block block{};
        Put(block, 0, 11, mode);
        Put(block, 11, 1, 1);
        InputBitStream stream(block);
        const auto params = DecodeBlockInfo(stream);
        const auto& info = infos[mode];
        const bool is_void = params.m_bVoidExtentLDR || params.m_bVoidExtentHDR;
        assert(info.void_extent == is_void);
        assert(info.void_extent_hdr == params.m_bVoidExtentHDR);
        assert(info.error == (params.m_bError && !is_void));
        assert(info.dual_plane == params.m_bDualPlane);
        assert(info.weight_bits == (info.error || is_void ? 0 : params.GetPackedBitSize()));
        saw_error |= params.m_bError;
        saw_void |= is_void;
        saw_dual |= params.m_bDualPlane;
        if (is_void) {
            // All four HDR/LDR + bit-10 modes, both values of reserved bit 11,
            // both values of bit 12, and every possible RGBA16 alpha value.
            for (u32 partitions = 0; partitions < 4; ++partitions) {
                Put(block, 11, 2, partitions);
                for (u32 alpha = 0; alpha < 65536; ++alpha) {
                    Put(block, 112, 16, alpha);
                    const bool expected = params.m_bError || !(partitions & 1) ||
                        alpha == (params.m_bVoidExtentHDR ? 0x3C00U : 0xFFFFU);
                    assert(Compare(block) == expected);
                }
            }
            continue;
        }
        const u32 weight_bits = params.GetPackedBitSize();
        saw_small_weights |= !params.m_bError && weight_bits < 24;
        saw_large_weights |= !params.m_bError && weight_bits > 96;
        for (u32 partitions = 1; partitions <= 4; ++partitions) {
            Put(block, 11, 2, partitions - 1);
            if (partitions == 1) {
                // Every single-partition endpoint mode, including HDR and alpha.
                for (u32 cem = 0; cem < 16; ++cem) {
                    Put(block, 13, 4, cem);
                    Compare(block);
                }
                continue;
            }
            // All shared endpoint modes and all split endpoint-mode encodings.
            // Invalid weights and dual-plane/four-partition blocks must still skip.
            const u32 extra_bits = partitions == 2 ? 2 : partitions == 3 ? 5 : 8;
            for (u32 base_cem = 0; base_cem < 64; ++base_cem) {
                Put(block, 23, 6, base_cem);
                const bool split = (base_cem & 3) && !params.m_bError &&
                    !(partitions == 4 && params.m_bDualPlane) &&
                    weight_bits >= 24 && weight_bits <= 96;
                if (!split) {
                    Compare(block);
                    continue;
                }
                for (u32 extra = 0; extra < (1U << extra_bits); ++extra) {
                    // Restore the header: malformed blocks can overlap the CEM bits.
                    Put(block, 23, 6, base_cem);
                    Put(block, 128 - weight_bits - extra_bits, extra_bits, extra);
                    Compare(block);
                }
            }
        }
    }
    assert(saw_error && saw_void && saw_dual && saw_small_weights && saw_large_weights);
    // Vary payload, partition indices, irrelevant bits and alignment independently.
    // Complete blocks only: trailing bytes must remain ignored, even after opaque blocks.
    std::array<u8, 65> bytes{};
    u32 random = 0x034;
    for (u32 mode = 0; mode < 2048; ++mode) {
        for (auto& byte : bytes) {
            random = random * 1664525U + 1013904223U;
            byte = static_cast<u8>(random >> 24);
        }
        for (u32 partitions = 0; partitions < 4; ++partitions) {
            const u32 header = mode | (partitions << 11);
            bytes[1] = static_cast<u8>(header);
            bytes[2] = static_cast<u8>((bytes[2] & 0xE0) | (header >> 8));
            for (u32 size = 0; size <= 64; ++size) {
                Compare(std::span<const u8>(bytes).subspan(1, size));
            }
        }
    }
    // Explicit opaque/alpha mixtures test early exits in either block order.
    Block solid{}, transparent{};
    Put(solid, 0, 12, 0xDFC); // Valid LDR void extent.
    Put(solid, 112, 16, 0xFFFF);
    transparent = solid;
    Put(transparent, 112, 16, 0);
    assert(Compare(solid) && !Compare(transparent));
    for (bool reverse : {false, true}) {
        std::array<u8, 32> pair{};
        std::memcpy(pair.data(), reverse ? transparent.data() : solid.data(), 16);
        std::memcpy(pair.data() + 16, reverse ? solid.data() : transparent.data(), 16);
        assert(!Compare(pair));
    }
    std::printf("ASTC_OPACITY_TABLE_PASS %llu cases (ASan/UBSan)\n",
                static_cast<unsigned long long>(cases));
}
'''
with tempfile.TemporaryDirectory(prefix='astc-opacity-table-') as td:
    temp = Path(td)
    (temp / 'check.cpp').write_text(cpp)
    subprocess.run(['clang++-18', '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
                    '-fno-omit-frame-pointer', str(temp / 'check.cpp'),
                    '-o', str(temp / 'check')], check=True)
    subprocess.run([str(temp / 'check')], check=True)
