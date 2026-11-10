"""UB-129: avoid contiguous ASTC scan copies and repeated shader block setup.

Usage: check-cheaper-astc-uploads.py [--source-only] [SOURCE_DIR]
SOURCE_DIR contains src/; default is the prepared build cache. On Linux/dedie, compile the
extracted production JoinImages scan with real GuestMemory/ScratchBuffer and a recording memory
manager; compile the shader's actual GetBitLength and range search as scalar C++. Main compiles
with the SAME fixture but fails: it copies contiguous scans and takes up to 21 search probes.
No GPU decoder harness: source checks pin block setup placement and the unchanged scale formula.
--source-only checks wiring and a faithful scalar range model, without a compiler or GPU.
"""
from pathlib import Path
import argparse
import os
import platform
import re
import shutil
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source-only', action='store_true')
parser.add_argument('source', nargs='?', type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
source = args.source or Path((root / '.local/headless-cache').read_text().strip()) / 'source'
src = source.resolve() / 'src'
cache = (src / 'video_core/texture_cache/texture_cache.h').read_text()
base = (src / 'video_core/texture_cache/texture_cache_base.h').read_text()
shader = (src / 'video_core/host_shaders/astc_decoder.comp').read_text()


def block(text, marker):
    start = text.index(marker)
    end = text.index('{', start + len(marker)) + 1
    depth = 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


def compact(text):
    return re.sub(r'\s+', '', text)


join = block(cache, 'ImageId TextureCache<P>::JoinImages(')
scan = block(join, 'if constexpr (requires { runtime.UseOpaqueAstcFormat(); })')
buffer_decl = re.search(r'[^\n;]*\bastc_scan_buffer;', base).group().strip()
decode = block(shader, 'void DecodeColorValues(')
search_start = decode.index('// Find the largest encoding')
search_end = decode.index(';', decode.index('DecodeIntegerSequence(', search_start)) + 1
search = decode[search_start:search_end]
# Extract the actual packed encoding table, used by both the Python model and compiled fixture.
table = re.search(r'const uint encoding_values\[22\] = uint\[\]\((.*?)\);', shader, re.S).group(1)
entries = [re.sub(r'(\d+)u\b', r'\1', entry.strip()) for entry in table.split(',')]
encodings = [eval(entry, {'__builtins__': {}}, {'JUST_BITS': 0, 'QUINT': 1, 'TRIT': 2})
             for entry in entries]


def bit_length(n, index):
    """GetBitLength: packed low byte is the encoding; next byte is the bit count."""
    value = encodings[index]
    return (value >> 8) * n + ((n * 8 + 4) // 5 if value & 255 == 2 else
                             (n * 7 + 2) // 3 if value & 255 == 1 else 0)


def linear(n, bits):
    for index in range(1, len(encodings)):
        if bit_length(n, index) > bits:
            return index - 1
    return len(encodings) - 1


def bisect(n, bits):
    low, high = 1, len(encodings)
    while low < high:
        middle = (low + high) >> 1
        if bit_length(n, middle) > bits:
            high = middle
        else:
            low = middle + 1
    return low - 1


# Cover all legal endpoint counts (2..32 even), plus 0..64 and budgets beyond a block.
for n in range(65):
    lengths = [bit_length(n, i) for i in range(len(encodings))]
    assert lengths == sorted(lengths), (n, lengths)
    for bits in range(513):
        assert linear(n, bits) == bisect(n, bits), (n, bits)
print('PASS: scalar bisection matches the old linear range choice (33,345 pairs)', flush=True)

if not args.source_only:
    assert platform.system() == 'Linux', 'Compile on Linux/dedie only'
    compiler = os.environ.get('CXX') or next((c for c in ('clang++-18', 'clang++', 'g++')
                                             if shutil.which(c)), None)
    assert compiler, 'No host C++ compiler; use --source-only here and run the fixture on dedie'
    with tempfile.TemporaryDirectory(prefix='eden-cheaper-astc-') as temp_name:
        temp = Path(temp_name)
        (temp / 'common').mkdir()
        (temp / 'video_core').mkdir()
        # Only external dependencies are stubbed: the guest-view and scratch templates are real.
        (temp / 'common/assert.h').write_text('#pragma once\n#include <cassert>\n#define ASSERT(x) assert(x)\n')
        (temp / 'video_core/memory_manager.h').write_text(r'''#pragma once
#include <algorithm>
#include <cstring>
#include <vector>
namespace Tegra {
class MemoryManager {
public:
    static constexpr bool HAS_FLUSH_INVALIDATION = false;
    bool split = false;
    unsigned reads = 0;
    size_t copied = 0;
    std::vector<u8> first, second;
    MemoryManager() : first(32, 0x41), second(32, 0x52) {}
    u8* GetSpan(u64 addr, size_t size) {
        return !split && addr == 0 && size <= first.size() ? first.data() : nullptr;
    }
    void ReadBlockUnsafe(u64 addr, void* dest, size_t size) {
        assert(addr == 0 && size <= first.size() + second.size());
        ++reads;
        copied += size;
        size_t left = std::min(size, first.size());
        std::memcpy(dest, first.data(), left);
        if (size > left) std::memcpy(static_cast<u8*>(dest) + left, second.data(), size - left);
    }
};
using MaxwellDeviceMemoryManager = MemoryManager;
}
''')
        cpp = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <span>
#include <vector>
using u8 = std::uint8_t; using u32 = std::uint32_t; using u64 = std::uint64_t;
using uint = unsigned int;
#include "video_core/guest_memory.h"
constexpr size_t operator""_MiB(unsigned long long n) { return n * 1024 * 1024; }
static int failures = 0;
void check(bool ok, const char* message) {
    if (!ok) { ++failures; std::printf("FAIL: %s\n", message); }
}
struct Info { bool format = true, astc_opaque = false; size_t size = 32; };
bool IsPixelFormatASTC(bool format) { return format; }
size_t CalculateGuestSizeInBytes(const Info& info) { return info.size; }
struct Runtime { bool enabled = true; bool UseOpaqueAstcFormat() { return enabled; } };
struct Fixture {
    Runtime runtime;
    Tegra::MemoryManager memory;
    Tegra::MemoryManager* gpu_memory = &memory;
    u64 gpu_addr = 0, astc_opaque_images = 0, astc_alpha_images = 0;
    const u8* observed = nullptr;
    size_t observed_size = 0;
    unsigned scans = 0;
    BUFFER_DECL
    bool AstcDataLooksOpaque(std::span<const u8> data) {
        ++scans; observed = data.data(); observed_size = data.size();
        for (size_t i = 0; i < data.size(); ++i)
            check(data[i] == (i < 32 ? 0x41 : 0x52), "scan byte differs across mappings");
        return data.size() == 32;
    }
    void Run(Info& new_info) {
SCAN
    }
};
struct EncodingData { uint data; explicit EncodingData(uint v) : data(v) {} };
uint Encoding(EncodingData v) { return v.data & 255; }
uint NumBits(EncodingData v) { return (v.data >> 8) & 255; }
const uint JUST_BITS = 0, QUINT = 1, TRIT = 2;
const uint encoding_values[] = {TABLE};
DIVISIONS
BIT_LENGTH
unsigned probes = 0;
uint GetBitLength(uint n, uint index) { ++probes; return RawBitLength(n, index); }
int selected = -1;
void DecodeIntegerSequence(int index, uint) { selected = index; }
int Choose(uint num_values, uint color_data_bits) {
SEARCH
    return selected;
}
int main() {
    Fixture contiguous;
    Info info;
    contiguous.Run(info);
    check(contiguous.memory.reads == 0 && contiguous.memory.copied == 0,
          "contiguous scan must copy zero guest bytes");
    check(contiguous.observed == contiguous.memory.first.data(), "scan must see the guest pointer");
    check(contiguous.observed_size == 32 && info.astc_opaque && contiguous.astc_opaque_images == 1,
          "opaque result and counter");
    Fixture split;
    split.memory.split = true;
    info = Info{}; info.size = 64;
    split.Run(info);
    check(split.memory.reads == 1 && split.memory.copied == 64, "split scan copies exactly once");
    check(split.observed == split.astc_scan_buffer.data() && split.observed_size == 64,
          "split scan uses the supplied backup");
    check(!info.astc_opaque && split.astc_alpha_images == 1, "alpha result and counter");
    split.Run(info);
    check(split.memory.reads == 2, "backup is refreshed for each split scan");
    for (int mode = 0; mode < 3; ++mode) {
        Fixture skip;
        info = Info{};
        if (mode == 0) skip.runtime.enabled = false;
        if (mode == 1) info.format = false;
        if (mode == 2) info.size = 64_MiB + 1;
        skip.Run(info);
        check(skip.scans == 0 && skip.memory.reads == 0, "gate/format/limit must skip the scan");
    }
    for (uint n = 0; n <= 64; ++n) {
        for (uint bits = 0; bits <= 512; ++bits) {
            int expected = 0;
            while (expected + 1 < int(std::size(encoding_values)) &&
                   RawBitLength(n, expected + 1) <= bits) ++expected;
            probes = 0;
            check(Choose(n, bits) == expected, "production range choice differs from linear search");
            if (probes > 5) { check(false, "production range search exceeds five probes"); return 1; }
        }
    }
    std::puts(failures ? "Cheaper ASTC uploads FAILED" : "Cheaper ASTC uploads: PASS");
    return failures ? 1 : 0;
}
'''
        replacements = {
            'BUFFER_DECL': buffer_decl,
            'SCAN': scan,
            'TABLE': table,
            'DIVISIONS': '\n'.join(block(shader, 'uint ' + name + '(')
                                   for name in ('Div3Floor', 'Div3Ceil', 'Div5Floor', 'Div5Ceil')),
            'BIT_LENGTH': block(shader, 'uint GetBitLength(').replace('GetBitLength(', 'RawBitLength('),
            'SEARCH': search.replace('encoding_values.length()', 'int(std::size(encoding_values))'),
        }
        for marker, replacement in replacements.items():
            cpp = cpp.replace(marker, replacement)
        (temp / 'check.cpp').write_text(cpp)
        binary = temp / 'check'
        subprocess.run([compiler, '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
                        '-I' + str(temp), '-I' + str(src), str(temp / 'check.cpp'),
                        '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)

failed = False


def require(ok, message):
    global failed
    if not ok:
        print('FAIL: ' + message)
        failed = True


require(buffer_decl == 'Common::ScratchBuffer<u8> astc_scan_buffer;', 'scan backup must be ScratchBuffer')
require('GpuGuestMemory<u8,Tegra::Memory::GuestMemoryFlags::UnsafeRead>' in compact(scan) and
        'scan_data(*gpu_memory,gpu_addr,scan_bytes,&astc_scan_buffer)' in compact(scan),
        'opacity scan must use UnsafeRead guest view with its scratch backup')
require('ReadBlockUnsafe' not in scan and 'astc_scan_buffer.resize' not in scan,
        'opacity scan still copies every contiguous guest range')
require('AstcDataLooksOpaque(std::span<constu8>{scan_data.data(),scan_data.size()})' in compact(scan),
        'opacity scan must consume the guest view while it is alive')
require('constexprsize_tMaxScanBytes=64_MiB;' in compact(scan) and
        'if(scan_bytes<=MaxScanBytes)' in compact(scan) and 'runtime.UseOpaqueAstcFormat()' in scan,
        '64 MiB limit / opaque-format gate changed')
body = block(shader, 'void DecompressBlock(')
loop = body.index('for (uint j = 0; j < block_dims.y; j++)')
for axis, scale in (('x', 's'), ('y', 't')):
    assignment = f'weight_scale_{scale} = uint((block_dims.{axis} * 0.5f + 1024) / (block_dims.{axis} - 1));'
    require(body.count(assignment) == 1 and assignment in body[:loop],
            f'weight scale {scale} must use the same formula once before the texel loops')
weight = block(shader, 'uvec4 GetUnquantizedWeightVector(')
require('const uint Ds = weight_scale_s;' in weight and 'const uint Dt = weight_scale_t;' in weight,
        'texels still compute their own scale')
require(body.count('SetupPartition(') == 1 and
        'if(num_partitions>1){partition_setup=SetupPartition(partition_index,num_partitions);}' in compact(body[:loop]),
        'partition setup must run once before texels, only for multi-partition blocks')
select = block(shader, 'uint Select2DPartition(')
require('Hash52(' not in select and 'Select2DPartition(partition_setup, i, j)' in body[loop:],
        'partition hash setup still runs per texel')
require(all(s in search for s in ('range_low', 'range_high',
        'GetBitLength(num_values, uint(range_middle)) > color_data_bits',
        'DecodeIntegerSequence(range_low - 1, num_values)')) and '++range <' not in search,
        'production colour search must use bisection with the same comparison / decode argument')
# Keep the faithful Python model tied to the production bit-length formula.
length = compact(block(shader, 'uint GetBitLength('))
require('uinttotal_bits=NumBits(encoding_value)*n_vals;' in length and
        'if(encoding==TRIT){total_bits+=Div5Ceil(n_vals*8);}' in length and
        'elseif(encoding==QUINT){total_bits+=Div3Ceil(n_vals*7);}' in length,
        'GetBitLength changed: update the scalar model')
print('Source checks ' + ('FAILED' if failed else 'PASS'))
raise SystemExit(1 if failed else 0)
