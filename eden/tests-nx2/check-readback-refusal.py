"""A readback whose staging buffer graphics memory refuses is skipped; the session goes on.

Issue #20, run of #26 (00.065.026, Mario Kart World): a 144 MiB staging buffer was refused three
times (idle buffers released, texture cache reclaimed) with 462 MiB free in blocks of 128 MiB at
most, and the GPU worker ended the session. 144 MiB is exactly the 6144x6144 RGBA8 render target
in the texture cache's report (flags CPU- and GPU-modified): uploads of such an image already go
in 32 MiB chunks (UploadInChunks), so the transfer was its whole-image readback, which the texture
cache queues each time the render target is bound once the CPU has read it (PreemtiveDownload).

Checks, compiled with the production code: DropImageReadbacks (pending_download.h) takes the image
readbacks out of a batch and keeps the buffer ones; the production CommitAsyncFlushes skips the
image readbacks when TryDownloadStagingBuffer gives nothing, and still downloads them otherwise;
the production synchronous batch (headless/vulkan_download_batch.inc, as generated) publishes what
it copied and leaves the refused image and the ones after it GPU-modified. Then checks the
generated staging pool names the refused transfer's kind. Fails on 3d82baf.

Run of 3e0e601 (00.065.027): that readback was refused once, the pool's idle buffers went and it
was made with 430 MiB free; a moment later the CPU heap could not get 16 MiB and the session ended
in std::bad_alloc. A readback queued ahead of a CPU read is now not made where the pool's largest
free block would keep less than the texture cache's 1280 MiB reserve (AheadReadbackFits): checked
at that run's numbers, with CommitAsyncFlushes. Fails on 3e0e601.
"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
if len(sys.argv) > 1:
    source = Path(sys.argv[1]).resolve()
else:
    source = Path((root / '.local/headless-cache').read_text().strip()) / 'source'
src = source / 'src'
pending = (src / 'video_core/texture_cache/pending_download.h').read_text()
if 'DropImageReadbacks' not in pending:
    print('FAIL: a refused readback staging buffer ends the session: nothing skips the readbacks '
          '(pending_download.h has no DropImageReadbacks)')
    sys.exit(1)
runtime_header = (src / 'video_core/renderer_vulkan/vk_texture_cache.h').read_text()
assert 'std::optional<StagingBufferRef> TryDownloadStagingBuffer(' in runtime_header, \
    'The Vulkan texture cache runtime has no TryDownloadStagingBuffer'
runtime_source = (src / 'video_core/renderer_vulkan/vk_texture_cache.cpp').read_text()


def function(text, signature):
    assert text.count(signature) == 1, 'Missing production code: ' + signature
    start = text.index(signature)
    at = text.index('{', start)
    depth, end = 1, at + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end] + '\n'


try_download = function(runtime_source, 'std::optional<StagingBufferRef> TextureCacheRuntime::TryDownloadStagingBuffer(')
for needed in ('staging_buffer_pool.Request(size, MemoryUsage::Download, deferred)', 'catch (const vk::Exception& refused)',
               'VK_ERROR_OUT_OF_DEVICE_MEMORY', 'throw;', 'return std::nullopt;'):
    assert needed in try_download, 'TryDownloadStagingBuffer lacks: ' + needed
cache = (src / 'video_core/texture_cache/texture_cache.h').read_text()
commit = function(cache, 'void TextureCache<P>::CommitAsyncFlushes() {')
batch = (root / 'headless/vulkan_download_batch.inc').read_text()
if 'AheadReadbackFits' not in pending:
    print('FAIL: a readback queued ahead of a CPU read takes the pool\'s last memory (no AheadReadbackFits)')
    sys.exit(1)
fits = function(runtime_source, 'bool TextureCacheRuntime::AheadReadbackFits(')
for needed in ('eden_direct_memory_free(&pool_free, &largest_free)', 'VideoCommon::AheadReadbackFits(largest_free, size)'):
    assert needed in fits, 'TextureCacheRuntime::AheadReadbackFits lacks: ' + needed
assert 'AheadReadbackFits' not in batch, 'A readback the CPU waits for must not be held to the reserve'
assert 'TryDownloadStagingBuffer' in batch, 'The synchronous download batch still ends the session on a refusal'

test = r'''
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <deque>
#include <optional>
#include <span>
#include <type_traits>
#include <utility>
#include <vector>
#include <boost/container/small_vector.hpp>
#include "common/common_types.h"
#include "common/alignment.h"
#include "common/literals.h"
#include "common/slot_vector.h"
#include "video_core/texture_cache/pending_download.h"
#include "graphics_usage.h"
static_assert(VideoCommon::kAheadReadbackReserve == Eden::GraphicsUsage::kReserve,
              "the readback reserve is the texture cache's");
using namespace Common::Literals;

namespace VideoCommon {
enum class ImageFlagBits : u32 { GpuModified = 1 << 3 };
constexpr ImageFlagBits operator|(ImageFlagBits a, ImageFlagBits b) { return ImageFlagBits(u32(a) | u32(b)); }
constexpr ImageFlagBits& operator|=(ImageFlagBits& a, ImageFlagBits b) { return a = a | b; }
constexpr ImageFlagBits operator&(ImageFlagBits a, ImageFlagBits b) { return ImageFlagBits(u32(a) & u32(b)); }
constexpr bool True(ImageFlagBits f) { return u32(f) != 0; }
struct Info { bool forced_flushed = true; };
struct Copy { size_t size; };
struct Map {
    std::size_t offset = 0;
    std::size_t size = 0;
    std::vector<u8> bytes;
    std::span<u8> mapped_span;
};
static int downloads = 0, swizzles = 0, finishes = 0;
struct Image {
    Info info;
    ImageFlagBits flags{};
    std::size_t unswizzled_size_bytes = 0;
    u64 gpu_addr = 0;
    void DownloadMemory(Map& map, std::span<const Copy>) {
        assert(map.offset + unswizzled_size_bytes <= map.size);
        ++downloads;
    }
};
inline std::vector<Copy> FullDownloadCopies(const Info&) { return {Copy{0}}; }
template <class T> T FixSmallVectorADL(T value) { return value; }
inline bool NativeDrawDiagnosticsEnabled() { return false; }
#undef LOG_WARNING
#define LOG_WARNING(...) ((void)0)
using ImageId = Common::SlotId;
struct Gpu {};
inline void SwizzleImage(Gpu&, u64, const Info&, std::span<const Copy>, std::span<u8>, int&) { ++swizzles; }
}  // namespace VideoCommon
namespace Vulkan {
struct TextureCacheRuntime {
    std::size_t free_bytes = 0;  // largest staging buffer graphics memory still gives
    std::size_t largest = SIZE_MAX;  // the pool's largest free block, as the console reports it
    int refusals = 0, requests = 0;
    bool AheadReadbackFits(std::size_t size, std::size_t& largest_free) const {
        largest_free = largest;
        return VideoCommon::AheadReadbackFits(largest_free, size);
    }
    VideoCommon::Map DownloadStagingBuffer(std::size_t size, bool = false) {
        assert(false && "the refusable request must be used");
        return {};
    }
    std::optional<VideoCommon::Map> TryDownloadStagingBuffer(std::size_t size, bool = false) {
        ++requests;
        if (size > free_bytes) { ++refusals; return std::nullopt; }
        VideoCommon::Map map{0, size, std::vector<u8>(size)};
        map.mapped_span = map.bytes;
        return map;
    }
    void Finish() { ++VideoCommon::finishes; }
};
}  // namespace Vulkan
namespace VideoCommon {
struct P { using Runtime = Vulkan::TextureCacheRuntime; using Image = VideoCommon::Image; };
template <class P>
struct TextureCache {
    using Runtime = typename P::Runtime;
    using Image = typename P::Image;
    using PendingDownload = PendingImageDownload<Image>;
    static constexpr bool IMPLEMENTS_ASYNC_DOWNLOADS = true;
    Runtime runtime;
    Common::SlotVector<Image> slot_images;
    std::vector<PendingDownload> uncommitted_downloads;
    std::deque<std::vector<PendingDownload>> committed_downloads;
    std::vector<Map> uncommitted_async_buffers;
    std::deque<std::vector<Map>> async_buffers;
    std::deque<Map> async_buffers_death_ring;
    Gpu gpu;
    Gpu* gpu_memory = &gpu;
    int swizzle_data_buffer = 0;
    void CommitAsyncFlushes();
    void DownloadMemory(boost::container::small_vector<ImageId, 16> images);
};
COMMIT
template <class P>
void TextureCache<P>::DownloadMemory(boost::container::small_vector<ImageId, 16> images) {
BATCH
}
}  // namespace VideoCommon
using namespace VideoCommon;

int main() {
    // DropImageReadbacks: image readbacks go, buffer ones stay.
    TextureCache<P> cache;
    const auto target = cache.slot_images.insert(Image{Info{}, ImageFlagBits::GpuModified, 144_MiB});
    const auto small = cache.slot_images.insert(Image{Info{}, ImageFlagBits::GpuModified, 9_MiB});
    std::vector<PendingImageDownload<Image>> batch{{true, 0, target}, {false, 0, {}}, {true, 0, small}};
    const auto dropped = DropImageReadbacks(batch, cache.slot_images);
    assert(dropped.images == 2 && dropped.bytes == 153_MiB && batch.size() == 1 && !batch[0].is_swizzle);
    assert(!cache.slot_images[target].info.forced_flushed && !cache.slot_images[small].info.forced_flushed);

    // CommitAsyncFlushes, the console's case: 144 MiB asked, at most 128 MiB given.
    cache.slot_images[target].info.forced_flushed = true;
    cache.runtime.free_bytes = 128_MiB;
    cache.uncommitted_downloads = {{true, 0, target}};
    cache.CommitAsyncFlushes();
    assert(cache.runtime.refusals == 1 && downloads == 0);
    assert(cache.committed_downloads.size() == 1 && cache.committed_downloads.back().empty());
    assert(cache.async_buffers.size() == 1 && cache.async_buffers.back().empty());
    assert(!cache.slot_images[target].info.forced_flushed);
    assert(True(cache.slot_images[target].flags & ImageFlagBits::GpuModified));
    // With the memory there, the readback is made as before.
    cache.runtime.free_bytes = 1_GiB;
    cache.uncommitted_downloads = {{true, 0, target}, {true, 0, small}};
    cache.CommitAsyncFlushes();
    assert(downloads == 2 && cache.committed_downloads.back().size() == 2 && cache.async_buffers.back().size() == 1);

    // The run of 3e0e601: 144 MiB queued ahead with 182 MiB in the largest free block after the
    // idle buffers went (made, then the heap was refused 16 MiB). Now not asked for at all.
    static_assert(!AheadReadbackFits(182_MiB, 144_MiB) && !AheadReadbackFits(1198_MiB, 144_MiB));
    static_assert(AheadReadbackFits(1424_MiB, 144_MiB) && AheadReadbackFits(4396_MiB, 144_MiB));
    static_assert(AheadReadbackFits(SIZE_MAX, 144_MiB) && !AheadReadbackFits(100_MiB, 144_MiB));
    downloads = 0;
    const int asked = cache.runtime.requests;
    cache.slot_images[target].info.forced_flushed = true;
    cache.runtime.largest = 182_MiB;
    cache.uncommitted_downloads = {{true, 0, target}, {false, 0, {}}};
    cache.CommitAsyncFlushes();
    assert(cache.runtime.requests == asked && downloads == 0);
    assert(cache.committed_downloads.back().size() == 1 && !cache.committed_downloads.back()[0].is_swizzle);
    assert(!cache.slot_images[target].info.forced_flushed);
    cache.runtime.largest = 4396_MiB;
    cache.uncommitted_downloads = {{true, 0, target}};
    cache.CommitAsyncFlushes();
    assert(cache.runtime.requests == asked + 1 && downloads == 1);

    // The synchronous batch (not held to the reserve: the CPU waits for it): the 9 MiB image is copied and published, the 144 MiB one is refused.
    downloads = swizzles = 0;
    cache.slot_images[target].info.forced_flushed = true;
    cache.slot_images[target].flags = {};
    cache.slot_images[small].flags = {};
    cache.runtime.free_bytes = 128_MiB;
    cache.runtime.largest = 182_MiB;
    cache.DownloadMemory({small, target});
    assert(downloads == 1 && swizzles == 1);
    assert(!True(cache.slot_images[small].flags & ImageFlagBits::GpuModified));
    assert(True(cache.slot_images[target].flags & ImageFlagBits::GpuModified));
    assert(!cache.slot_images[target].info.forced_flushed);
    std::printf("PASS: a refused 144 MiB readback is skipped (async: buffer readbacks kept, forced_flushed reset; "
                "sync: copied images published, the rest left GPU-modified); with memory it is read back; queued ahead, "
                "it is not asked for where the pool would keep less than 1280 MiB (182 MiB left at 3e0e601)\n");
}
'''

with tempfile.TemporaryDirectory(prefix='eden-readback-refusal-') as temp:
    temp = Path(temp)
    compiler = os.environ.get('CXX') or next((c for c in ('clang++-18', 'clang++', 'g++') if shutil.which(c)), None)
    assert compiler, 'No host C++ compiler'
    body = batch.replace('    if constexpr (std::is_same_v<Runtime, Vulkan::TextureCacheRuntime>) {', '    {', 1)
    (temp / 'check.cpp').write_text(test.replace('COMMIT', 'template <class P>\n' + commit).replace('BATCH', body))
    flags = ['-std=c++20', '-O1', '-g']
    if sys.platform.startswith('linux'):
        flags.append('-fsanitize=address,undefined')
    subprocess.run([compiler, *flags, '-I' + str(src), '-I' + str(root / 'headless'), str(temp / 'check.cpp'), '-o', str(temp / 'check')], check=True)
    subprocess.run([str(temp / 'check')], check=True)

    tools = temp / 'bin'
    tools.mkdir()
    (tools / 'glslangValidator').write_text(
        '#!/bin/sh\nwhile [ $# -gt 0 ]; do [ "$1" = -o ] && printf \'\\003\\002\\043\\007\' > "$2"; shift; done\n')
    (tools / 'spirv-val').write_text('#!/bin/sh\nexit 0\n')
    for tool in tools.iterdir():
        tool.chmod(0o755)
    env = dict(os.environ, PATH=f'{tools}:{os.environ.get("PATH", "/usr/bin:/bin")}')
    subprocess.run([sys.executable, '-B', str(root / 'tools/prepare-vulkan-port.py'), str(source), str(temp / 'out')],
                   env=env, check=True, capture_output=True)
    pool = (temp / 'out/vulkan_staging_buffer_pool.cpp').read_text()
    create = re.search(r'StagingBufferRef StagingBufferPool::CreateStagingBuffer\(.*?\n\}\n', pool, re.S)
    assert create, 'No CreateStagingBuffer in the generated pool'
    for needed in ('usage == MemoryUsage::Download ? "download"', 'EDEN_STAGING_OOM kind=%s', 'EDEN_VRAM_RECLAIM kind=%s'):
        assert needed in create.group(0), 'Generated CreateStagingBuffer lacks: ' + needed
    generated = (temp / 'out/vulkan-cache/video_core/texture_cache/texture_cache.h').read_text()
    assert generated.count('TryDownloadStagingBuffer') >= 2, 'The generated texture cache does not use TryDownloadStagingBuffer'
print('PASS: the generated staging pool names the refused transfer (download, upload or device)')
