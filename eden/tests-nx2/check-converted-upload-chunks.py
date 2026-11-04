"""Converted images (ASTC kept as BC1/BC3) are uploaded a few layers at a time, at most 32 MiB each.

Issue #20, run of #25 (00.065.025, Mario Kart World): a 1434x1434 ASTC 6x6 array of 46 layers,
kept as BC3, was staged in one request of 126670752 bytes (128 MiB once rounded); the console's
shared pool had blocks of 80 MiB at most and the game ended. UploadInChunks excludes converted
images. Compiles the production TextureCache::UploadConvertedInChunks and ConvertImage (prepared
source, all layers applied) with the real ASTC decoder and BCn encoders; checks every staging
request is at most 32 MiB and the image gets the same bytes, level by level and layer by layer,
as from the whole-image upload; and that RefreshContents takes this path before the whole-image
staging buffer. Fails on a tree without layer 99zg. Run on dedie.
"""
from pathlib import Path
import glob
import os
import platform
import shutil
import subprocess
import sys
import tempfile

assert platform.system() == 'Linux', 'Compile on dedie'
root = Path(__file__).resolve().parents[1]
if len(sys.argv) > 1:
    source = Path(sys.argv[1]).resolve()
else:
    source = Path((root / '.local/headless-cache').read_text().strip()) / 'source'
src = source / 'src'
cache = (src / 'video_core/texture_cache/texture_cache.h').read_text()
util = (src / 'video_core/texture_cache/util.cpp').read_text()


def function(text, signature):
    assert text.count(signature) == 1, 'Missing production code: ' + signature
    start = text.index(signature)
    at = text.index('{', start)
    depth, end = 1, at + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end] + '\n'


refresh = function(cache, 'void TextureCache<P>::RefreshContents(Image& image, ImageId image_id) {')
whole = 'runtime.UploadStagingBuffer(MapSizeBytes(image))'
if 'UploadConvertedInChunks' not in cache:
    print('FAIL: RefreshContents stages a converted image whole (UploadInChunks excludes ImageFlagBits::Converted): '
          'the 1434x1434x46 ASTC 6x6 array kept as BC3 is one request of 126670752 bytes')
    sys.exit(1)
assert refresh.count(whole) == 1 and 'UploadConvertedInChunks(image)' in refresh.split(whole)[0], \
    'RefreshContents does not try UploadConvertedInChunks before the whole-image staging buffer'
chunks = function(cache, 'bool TextureCache<P>::UploadConvertedInChunks(Image& image) {')
convert = function(util, 'void ConvertImage(std::span<const u8> input, const ImageInfo& info, std::span<u8> output,')

boost = sorted(glob.glob(str(source / '.cache/cpm/boost/*/libs/*/include')))
temp_root = tempfile.mkdtemp(prefix='eden-converted-chunks-')
try:
    temp = Path(temp_root)
    if not boost and not Path('/usr/include/boost/container/static_vector.hpp').exists():
        debs = sorted((root / '.deps').glob('libboost*-dev_*.deb'))
        assert debs, 'No Boost headers: run after a configure (CPM cache) or tools/prepare-build.sh (.deps)'
        subprocess.run(['dpkg-deb', '-x', str(debs[-1]), str(temp / 'boost')], check=True)
        boost = [str(temp / 'boost/usr/include')]
    overlay = temp / 'overlay/common'
    overlay.mkdir(parents=True)
    (overlay / 'thread_worker.h').write_text('''#pragma once
#include <utility>
namespace Common {
struct ThreadWorker {
    template <class F> void QueueWork(F&& work) { std::forward<F>(work)(); }
    void WaitForRequests() {}
};
}
''')
    fixture = r'''
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <deque>
#include <map>
#include <span>
#include <vector>
#include "common/alignment.h"
#include "common/common_types.h"
#include "common/literals.h"
#include "common/scratch_buffer.h"
#include "video_core/textures/astc.h"
#include "video_core/textures/bcn.h"
#include "video_core/textures/workers.h"
using namespace Common::Literals;

namespace Tegra::Texture {
Common::ThreadWorker& GetThreadWorkers() { static Common::ThreadWorker workers; return workers; }
}
namespace Tegra { struct MemoryManager {}; }
#define ASSERT(test) do { if (!(test)) { std::fprintf(stderr, "ASSERT %s\n", #test); std::abort(); } } while (0)
namespace Settings {
enum class AstcRecompression { Uncompressed, Bc1, Bc3 };
struct Setting { AstcRecompression value; AstcRecompression GetValue() const { return value; } };
struct Values { Setting astc_recompression{AstcRecompression::Bc3}; };
Values values;
}
namespace VideoCore::Surface {
enum class PixelFormat { A8B8G8R8_UNORM, ASTC_2D_4X4_UNORM, ASTC_2D_6X6_UNORM, ASTC_2D_8X8_UNORM };
constexpr u32 BytesPerBlock(PixelFormat format) { return format == PixelFormat::A8B8G8R8_UNORM ? 4 : 16; }
constexpr bool IsPixelFormatASTC(PixelFormat format) { return format != PixelFormat::A8B8G8R8_UNORM; }
}
namespace VideoCommon {
using VideoCore::Surface::BytesPerBlock;
using VideoCore::Surface::IsPixelFormatASTC;
using VideoCore::Surface::PixelFormat;
struct Extent2D { u32 width, height; };
struct Extent3D { u32 width, height, depth; bool operator==(const Extent3D&) const = default; };
struct Offset3D { s32 x, y, z; bool operator==(const Offset3D&) const = default; };
struct SubresourceLayers { s32 base_level; s32 base_layer; s32 num_layers; };
struct BufferImageCopy {
    size_t buffer_offset; size_t buffer_size; u32 buffer_row_length; u32 buffer_image_height;
    SubresourceLayers image_subresource; Offset3D image_offset; Extent3D image_extent;
};
enum class ImageType { e1D, e2D, e3D };
enum class ImageFlagBits : u32 { Converted = 1, Sparse = 2, AcceleratedUpload = 4, Unbacked = 8, TrimmedLevels = 16 };
constexpr ImageFlagBits operator|(ImageFlagBits a, ImageFlagBits b) { return ImageFlagBits(u32(a) | u32(b)); }
constexpr ImageFlagBits operator&(ImageFlagBits a, ImageFlagBits b) { return ImageFlagBits(u32(a) & u32(b)); }
constexpr bool True(ImageFlagBits f) { return u32(f) != 0; }
constexpr bool False(ImageFlagBits f) { return u32(f) == 0; }
struct Resources { s32 levels; s32 layers; };
struct ImageInfo { PixelFormat format; Extent3D size; bool astc_opaque = false; ImageType type = ImageType::e2D; Resources resources{1, 1}; };
Extent2D DefaultBlockSize(PixelFormat format) {
    switch (format) {
    case PixelFormat::ASTC_2D_4X4_UNORM: return {4, 4};
    case PixelFormat::ASTC_2D_6X6_UNORM: return {6, 6};
    case PixelFormat::ASTC_2D_8X8_UNORM: return {8, 8};
    default: return {1, 1};
    }
}
Extent3D AdjustMipSize(Extent3D size, s32 level) {
    return {std::max(size.width >> level, 1U), std::max(size.height >> level, 1U), std::max(size.depth >> level, 1U)};
}
u32 ConvertedBytesPerBlock(PixelFormat) { std::abort(); }
void DecompressBCn(std::span<const u8>, std::span<u8>, BufferImageCopy&, PixelFormat) { std::abort(); }
template <class T> T FixSmallVectorADL(const T& v) { return v; }

struct Staging { std::span<u8> mapped_span; };
struct Runtime {
    std::deque<std::vector<u8>> buffers;
    std::vector<size_t> requests;
    int barriers = 0;
    Staging UploadStagingBuffer(size_t size) {
        requests.push_back(size);
        buffers.emplace_back(size, u8{0xcd});
        return {buffers.back()};
    }
    void InsertUploadMemoryBarrier() { ++barriers; }
};
// The host image: the bytes each (level, layer) received.
struct Image {
    ImageInfo info;
    ImageFlagBits flags;
    u64 gpu_addr = 0x100000;
    size_t unswizzled_size_bytes = 0;
    u32 converted_size_bytes = 0;
    std::map<std::pair<s32, s32>, std::vector<u8>> contents;
    void UploadMemory(const Staging& staging, std::span<const BufferImageCopy> copies) {
        for (const BufferImageCopy& copy : copies) {
            const size_t layer_bytes = copy.buffer_size / copy.image_subresource.num_layers;
            ASSERT(copy.buffer_offset + copy.buffer_size <= staging.mapped_span.size());
            for (s32 i = 0; i < copy.image_subresource.num_layers; ++i) {
                const auto bytes = staging.mapped_span.subspan(copy.buffer_offset + i * layer_bytes, layer_bytes);
                contents[{copy.image_subresource.base_level, copy.image_subresource.base_layer + i}].assign(bytes.begin(), bytes.end());
            }
        }
    }
};
u32 MapSizeBytes(const Image& image) { return image.converted_size_bytes; }
// The unswizzled guest data: level after level, layer after layer (as util.cpp's UnswizzleImage).
std::vector<BufferImageCopy> UnswizzleImage(Tegra::MemoryManager&, u64 gpu_addr, const ImageInfo& info,
                                            std::span<const u8>, std::span<u8> output, Common::ScratchBuffer<u8>*) {
    const Extent2D tile = DefaultBlockSize(info.format);
    std::vector<BufferImageCopy> copies;
    size_t offset = 0;
    for (s32 level = 0; level < info.resources.levels; ++level) {
        const Extent3D size = AdjustMipSize(info.size, level);
        const size_t layer = size_t{Common::DivideUp(size.width, tile.width)} * Common::DivideUp(size.height, tile.height) * 16;
        copies.push_back({offset, layer * info.resources.layers, Common::AlignUp(size.width, tile.width),
                          Common::AlignUp(size.height, tile.height), {level, 0, info.resources.layers}, {}, size});
        offset += layer * info.resources.layers;
    }
    ASSERT(offset <= output.size());
    u64 state = gpu_addr;
    for (size_t i = 0; i < offset; ++i) {
        state = state * 6364136223846793005ULL + 1442695040888963407ULL;
        output[i] = u8(state >> 56);
    }
    return copies;
}
'''
    harness = r'''
template <class P>
struct TextureCache {
    using Image = VideoCommon::Image;
    Runtime runtime;
    Tegra::MemoryManager memory;
    Tegra::MemoryManager* gpu_memory = &memory;
    Common::ScratchBuffer<u8> unswizzle_data_buffer;
    Common::ScratchBuffer<u8> swizzle_data_buffer;
    bool UploadConvertedInChunks(Image& image);
    // The whole-image path of RefreshContents/UploadImageContents for a converted image.
    void UploadWhole(Image& image) {
        auto staging = runtime.UploadStagingBuffer(MapSizeBytes(image));
        unswizzle_data_buffer.resize_destructive(image.unswizzled_size_bytes);
        auto copies = UnswizzleImage(*gpu_memory, image.gpu_addr, image.info, {}, unswizzle_data_buffer, &swizzle_data_buffer);
        ConvertImage(unswizzle_data_buffer, image.info, staging.mapped_span, copies);
        image.UploadMemory(staging, copies);
    }
};
'''
    main = r'''
} // namespace VideoCommon
using namespace VideoCommon;

static Image Make(PixelFormat format, u32 w, u32 h, s32 layers, s32 levels, bool opaque) {
    Image image{{format, {w, h, 1}, opaque, ImageType::e2D, {levels, layers}}, ImageFlagBits::Converted};
    const Extent2D tile = DefaultBlockSize(format);
    for (s32 level = 0; level < levels; ++level) {
        const Extent3D size = AdjustMipSize(image.info.size, level);
        image.unswizzled_size_bytes += size_t{Common::DivideUp(size.width, tile.width)} * Common::DivideUp(size.height, tile.height) * 16 * layers;
        image.converted_size_bytes += Common::AlignUp(size.width, 4U) * Common::AlignUp(size.height, 4U) * layers / (opaque ? 2 : 1);
    }
    return image;
}

// Returns the largest staging request of the chunked upload.
static size_t Check(PixelFormat format, u32 w, u32 h, s32 layers, s32 levels, bool opaque) {
    TextureCache<int> whole_cache, chunk_cache;
    Image whole = Make(format, w, h, layers, levels, opaque), chunked = whole;
    whole_cache.UploadWhole(whole);
    if (!chunk_cache.UploadConvertedInChunks(chunked)) {
        std::fprintf(stderr, "FAIL: %ux%ux%d (%d levels): not uploaded in chunks\n", w, h, layers, levels);
        std::exit(1);
    }
    size_t largest = 0, total = 0;
    for (const size_t request : chunk_cache.runtime.requests) {
        largest = std::max(largest, request);
        total += request;
    }
    if (largest > 32_MiB) {
        std::fprintf(stderr, "FAIL: %ux%ux%d: a staging request of %zu bytes, more than 32 MiB\n", w, h, layers, largest);
        std::exit(1);
    }
    ASSERT(total == MapSizeBytes(whole));
    ASSERT(chunk_cache.runtime.barriers == 1);
    ASSERT(whole.contents.size() == size_t(layers) * levels);
    if (chunked.contents != whole.contents) {
        std::fprintf(stderr, "FAIL: %ux%ux%d (%d levels): the image got other bytes than from the whole upload\n", w, h, layers, levels);
        std::exit(1);
    }
    return largest;
}

int main() {
    // The console's texture: 1434x1434, 46 layers, 11 levels, ASTC 6x6 to BC3 (126670752 bytes).
    const size_t console = Check(PixelFormat::ASTC_2D_6X6_UNORM, 1434, 1434, 46, 11, false);
    Check(PixelFormat::ASTC_2D_4X4_UNORM, 1021, 1023, 40, 4, false);  // mips, odd sizes
    Check(PixelFormat::ASTC_2D_8X8_UNORM, 2048, 2048, 13, 2, true);   // opaque: BC1
    Check(PixelFormat::ASTC_2D_4X4_UNORM, 4120, 4120, 2, 1, false);   // one layer per request (16.2 MiB each)
    // Not taken: small, one layer, or not converted.
    for (Image image : {Make(PixelFormat::ASTC_2D_4X4_UNORM, 1024, 1024, 8, 1, false),
                        Make(PixelFormat::ASTC_2D_4X4_UNORM, 8192, 8192, 1, 1, false)}) {
        TextureCache<int> cache;
        ASSERT(!cache.UploadConvertedInChunks(image) && cache.runtime.requests.empty());
    }
    Image plain = Make(PixelFormat::ASTC_2D_6X6_UNORM, 1434, 1434, 46, 1, false);
    plain.flags = ImageFlagBits::Sparse;
    TextureCache<int> cache;
    ASSERT(!cache.UploadConvertedInChunks(plain));
    std::printf("PASS: converted images upload in chunks of <= 32 MiB with the same bytes as the whole upload "
                "(1434x1434x46 ASTC 6x6 -> BC3: largest request %zu bytes, was one of 126670752; mips, BC1, "
                "large layers; small, single-layer and sparse images keep their path)\n", console);
}
'''
    cpp = temp / 'check.cpp'
    cpp.write_text(fixture + convert + harness + 'template <class P>\n' + chunks + main)
    compiler = os.environ.get('CXX') or next((c for c in ('clang++-18', 'clang++', 'g++') if shutil.which(c)), None)
    assert compiler, 'No host C++ compiler'
    flags = ['-std=c++20', '-O2', '-g', '-DNDEBUG', '-fsanitize=address,undefined', '-D_GLIBCXX_ASSERTIONS',
             '-I' + str(temp / 'overlay'), '-I' + str(src), '-I' + str(source / 'externals/stb')]
    flags += ['-isystem' + b for b in boost]
    binary = temp / 'check'
    subprocess.run([compiler, *flags, str(cpp), str(src / 'video_core/textures/astc.cpp'),
                    str(src / 'video_core/textures/bcn.cpp'), str(source / 'externals/stb/stb_dxt.cpp'),
                    '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
finally:
    shutil.rmtree(temp_root, ignore_errors=True)
