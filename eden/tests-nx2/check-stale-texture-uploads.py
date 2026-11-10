"""UB-128: no texture upload for guest memory the GPU data left, none under a join copy that overwrites it.

Ocarina of Time moves render targets from frame to frame and resizes a shadow map every frame; main
uploaded the guest memory of every new image first (stale bytes the GPU overwrites; a whole upload
under a join copy that writes every texel). Compiled with the PRODUCTION code of the prepared source,
over a recording backend: StalePages (stale_pages.h), GpuWrittenPages (gpu_written_pages.h), the
extracted TextureCache::MarkStale / ClearStale / ClearStaleImage / ClearStaleGpu / WriteMemory /
UnmapMemory / DownloadMemory, the stale decision of RefreshContents, the tail of JoinImages (the
whole-copy search, the upload, the scaling and every copy) and util.cpp's CopiesWriteWholeImage:
 - stale marking: whole pages only (a partial boundary page stays unmarked), Switch 2 titles only,
   never a CpuModified, Sparse, Unbacked or not GPU-written image; marked pages stay tracked;
 - an image made on fully stale pages is made without an upload; any CPU write, unmap, image or
   buffer write-back clears every page it touches (a buffer write-back across mappings that are not
   contiguous in device memory too) and the upload comes back; pages written by a buffer, a query
   or the memory manager keep the upload, pages written only by images do not (this core's
   GpuWrittenPages gets a second bitmap for it); non-Switch 2 titles, Sparse, Unbacked, Remapped
   images and images with dirty layers keep it;
 - UB-150 (layer 99zzzz7): a join whose non-alias, GPU-modified, 1-sample overlaps together write every
   level and layer (each its own layer or mip; MarkSubresourcesWrittenWhole accumulates) also skips the
   upload; one layer missing, a partial extent or offset, another or a compressed format, Rescaled,
   TrimmedLevels, Sparse or Unbacked images, CPU-only or multisampled overlaps, an overlap TryFindBase
   cannot place, and a rescaled or multisampled join keep it. Negative control: a tree with 99zzzz3
   but not 99zzzz7 uploads in the multi-image cases (and MarkSubresourcesWrittenWhole is absent);
 - a join whose alias copy writes every mip, layer and texel of a fully backed 1x image of the same
   uncompressed format makes neither the upload nor the alias copies before that copy (the images
   end with the same contents); partial copies of any kind, scaling, compressed formats, Rescaled,
   TrimmedLevels, Sparse, Unbacked images, unsafe or other-sample-count aliases keep the upload.
Then source checks of what the compiled code cannot reach (the collector's one marking site, the
write-back sites of PopAsyncFlushes, the order inside RefreshContents and JoinImages, and that the
earlier layers' hooks are kept). Fails on main by behavior. NOT run where no compiler exists
(--source-only runs only the source checks).

Usage: check-stale-texture-uploads.py [--source-only] [SOURCE_DIR]   SOURCE_DIR is the tree that
contains src/ (default: this checkout's prepared build cache). Negative control: run this script
against the prepared source of main (a tree without layer 99zzzz3).
"""
from pathlib import Path
import platform
import subprocess
import sys

args = [a for a in sys.argv[1:] if not a.startswith('--')]
source_only = '--source-only' in sys.argv[1:]
if not source_only:
    assert platform.system() == 'Linux', 'Run on the Linux build server'
root = Path(__file__).resolve().parents[1]
if args:
    source = Path(args[0]).resolve()
else:
    source = Path((root / '.local/headless-cache').read_text().strip()) / 'source'
src = source / 'src'
cache = (src / 'video_core/texture_cache/texture_cache.h').read_text()
util = (src / 'video_core/texture_cache/util.cpp').read_text()
pages_header = (src / 'video_core/gpu_written_pages.h').read_text()
have_stale_pages = (src / 'video_core/texture_cache/stale_pages.h').exists()
have_non_image = 'AnyNonImage' in pages_header and 'MarkImage' in pages_header
out = root / 'build/nx2-tests/stale-texture-uploads'
(out / 'common').mkdir(parents=True, exist_ok=True)


def function(text, signature, required=True):
    """The text of the function whose definition starts with signature, up to its closing brace."""
    if not required and text.count(signature) == 0:
        return ''
    assert text.count(signature) == 1, 'Missing production code: ' + signature
    start = text.index(signature)
    end = text.index('{', start) + 1
    depth = 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end] + '\n'


def member(signature, stand_in):
    """A TextureCache member as production has it, or the stand-in when this tree lacks it (main)."""
    text = function(cache, 'void TextureCache<P>::' + signature, required=False)
    return 'template <class P>\n' + text if text else 'template <class P>\n' + stand_in + '\n'


# ------------------------------------------------------------------------------------------ build
(out / 'common/common_types.h').write_text(
    '#pragma once\n#include <cstddef>\n#include <cstdint>\n'
    'using u8 = std::uint8_t; using u16 = std::uint16_t; using u32 = std::uint32_t;\n'
    'using u64 = std::uint64_t; using s32 = std::int32_t; using s64 = std::int64_t;\n'
    'using DAddr = u64; using GPUVAddr = u64;\n')

join_text = function(cache, 'ImageId TextureCache<P>::JoinImages(')
join_end = join_text.index('    RegisterImage(new_image_id);')
if 'const auto alias_copy' in join_text:
    # The whole decision: the alias copy lookup, the whole-copy search, the upload, the scaling and
    # every copy of the join.
    join_tail = join_text[join_text.index('    // The copy from an alias into the new image'):join_end]
else:
    # Main: the upload and scaling, then the copy loop (the sort and the alias bookkeeping between
    # them are done by the fixture).
    join_tail = (join_text[join_text.index('    if (overwritten_by_clear()) {'):
                           join_text.index('    std::ranges::sort(join_copies_to_do')] +
                 join_text[join_text.index('    for (const auto& copy_object : join_copies_to_do) {'):join_end])

refresh_text = function(cache, 'void TextureCache<P>::RefreshContents(Image& image, ImageId image_id) {')
stale_marker = '    // Made where a dropped GPU-written image left stale bytes (MarkStale): nothing to upload.'
if stale_marker in refresh_text:
    begin = refresh_text.index(stale_marker)
    open_brace = refresh_text.index('{', begin)
    depth, end = 1, open_brace + 1
    while depth:
        depth += (refresh_text[end] == '{') - (refresh_text[end] == '}')
        end += 1
    stale_block = refresh_text[begin:end] + '\n'
else:
    stale_block = ''   # main: every refresh uploads

mark_whole = function(util, 'void MarkSubresourcesWrittenWhole(', required=False)
if not mark_whole:
    mark_whole = ('void MarkSubresourcesWrittenWhole(const ImageBase&, const ImageBase&, '
                  'std::span<const ImageCopy>, std::span<u8>) {}\n')   # 99zzzz3 and main: no accumulation
whole_copy = function(util, 'bool CopiesWriteWholeImage(', required=False)
if not whole_copy:
    whole_copy = ('bool CopiesWriteWholeImage(const ImageBase&, const ImageBase&, '
                  'std::span<const ImageCopy>) { return false; }\n')   # main: no such helper

stale_pages_include = ('#include "video_core/texture_cache/stale_pages.h"\n' if have_stale_pages else
                       'namespace VideoCommon { struct StalePages { static constexpr u64 PAGE_BITS = 12; '
                       'template <class F> void Mark(u64, u64, F&&) {} template <class F> void Clear(u64, u64, F&&) {} '
                       'bool IsAll(u64, u64) const { return false; } u64 Count() const { return 0; } }; }\n')
non_image_stand_in = ('' if have_non_image else
                      'namespace VideoCommon::GpuWrittenPages { inline void MarkImage(u64 a, u64 s) noexcept { Mark(a, s); } '
                      'inline bool AnyNonImage(u64 a, u64 s) noexcept { return Any(a, s); } }\n')

test = r'''
#include "common/common_types.h"
#include <algorithm>
#include <atomic>
#include <compare>
#include <cstdio>
#include <map>
#include <optional>
#include <span>
#include <string>
#include <utility>
#include <vector>
#include "video_core/nx2.h"
#include "video_core/gpu_written_pages.h"
''' + stale_pages_include + non_image_stand_in + r'''
#define LOG_INFO(...) ((void)0)
namespace boost::container { template <class T, size_t N> using small_vector = std::vector<T>; }
namespace Settings { struct Resolution { u32 up_scale = 1; u32 down_shift = 0; }; struct Values { Resolution resolution_info; }; inline Values values; }
namespace VideoCommon {
struct ImageId {
    u32 index = ~0u;
    explicit operator bool() const { return index != ~0u; }
    auto operator<=>(const ImageId&) const = default;
};
struct Extent3D { constexpr auto operator<=>(const Extent3D&) const noexcept = default; u32 width; u32 height; u32 depth; };
struct Offset3D { constexpr auto operator<=>(const Offset3D&) const noexcept = default; s32 x; s32 y; s32 z; };
struct SubresourceLayers { s32 base_level = 0; s32 base_layer = 0; s32 num_layers = 1; };
struct SubresourceBase { constexpr auto operator<=>(const SubresourceBase&) const noexcept = default; s32 level = 0; s32 layer = 0; };
struct SubresourceExtent { constexpr auto operator<=>(const SubresourceExtent&) const noexcept = default; s32 levels = 1; s32 layers = 1; };
struct ImageCopy { SubresourceLayers src_subresource; SubresourceLayers dst_subresource; Offset3D src_offset; Offset3D dst_offset; Extent3D extent; };
enum class ImageType { e1D, e2D, e3D, Linear };
enum class PixelFormat { A8B8G8R8_UNORM, R32_FLOAT, BC1_RGBA_UNORM };
inline u32 DefaultBlockWidth(PixelFormat f) { return f == PixelFormat::BC1_RGBA_UNORM ? 4 : 1; }
inline u32 DefaultBlockHeight(PixelFormat f) { return f == PixelFormat::BC1_RGBA_UNORM ? 4 : 1; }
enum class ImageFlagBits : u32 {
    None = 0, CpuModified = 1u << 2, GpuModified = 1u << 3, Tracked = 1u << 4, Remapped = 1u << 8,
    Sparse = 1u << 9, Rescaled = 1u << 13, Unbacked = 1u << 18, TrimmedLevels = 1u << 19,
};
constexpr ImageFlagBits operator|(ImageFlagBits a, ImageFlagBits b) { return ImageFlagBits(u32(a) | u32(b)); }
constexpr ImageFlagBits operator&(ImageFlagBits a, ImageFlagBits b) { return ImageFlagBits(u32(a) & u32(b)); }
constexpr ImageFlagBits operator~(ImageFlagBits a) { return ImageFlagBits(~u32(a)); }
inline ImageFlagBits& operator|=(ImageFlagBits& a, ImageFlagBits b) { return a = a | b; }
inline ImageFlagBits& operator&=(ImageFlagBits& a, ImageFlagBits b) { return a = a & b; }
constexpr bool True(ImageFlagBits f) { return u32(f) != 0; }
constexpr bool False(ImageFlagBits f) { return u32(f) == 0; }
struct ImageInfo {
    ImageType type = ImageType::e2D;
    PixelFormat format = PixelFormat::A8B8G8R8_UNORM;
    bool astc_opaque = false;
    Extent3D size{1, 1, 1};
    SubresourceExtent resources{};
    u32 num_samples = 1;
    u64 guest_size = 0;   // bytes SwizzleImage writes back
    std::vector<ImageCopy> shrink;   // test hook: what MakeShrinkImageCopies returns for this overlap
};
struct AliasedImage { std::vector<ImageCopy> copies; ImageId id; };
struct JoinCopy { bool is_alias; ImageId id; };
struct ImageBase {
    ImageInfo info;
    ImageFlagBits flags = ImageFlagBits::None;
    GPUVAddr gpu_addr = 0;
    DAddr cpu_addr = 0;
    DAddr cpu_addr_end = 0;
    size_t guest_size_bytes = 0;
    size_t unswizzled_size_bytes = 16;
    u64 modification_tick = 0;
    std::vector<u64> dirty_layers;
    std::vector<AliasedImage> aliased_images;
    bool safe_copy = true;
    bool registered = false;
    std::map<std::pair<s32, s32>, int> cells;   // (level, layer) -> content token
    bool IsSafeGpuCopy() const noexcept { return safe_copy; }
    bool has_base = true;
    std::optional<SubresourceBase> TryFindBase(GPUVAddr) const noexcept { return has_base ? std::optional<SubresourceBase>(SubresourceBase{}) : std::nullopt; }
    template <class M, class C> void DownloadMemory(M&, const C&) {}
};
using Image = ImageBase;
''' + function(util, 'constexpr u32 AdjustMipSize(u32 size, u32 level) {') \
    + function(util, 'constexpr Extent3D AdjustMipSize(Extent3D size, s32 level) {') \
    + function(util, 'Extent3D MipSize(Extent3D size, u32 level) {') + mark_whole + whole_copy + r'''
template <class T> T FixSmallVectorADL(T value) { return value; }
inline std::vector<int> FullDownloadCopies(const ImageInfo&) { return {0}; }
inline std::vector<ImageCopy> MakeShrinkImageCopies(const ImageInfo&, const ImageInfo& overlap, SubresourceBase, u32, u32) { return overlap.shrink.empty() ? std::vector<ImageCopy>{ImageCopy{}} : overlap.shrink; }
inline void InvalidateAsyncDecode(ImageBase&) noexcept {}

struct MockGpuMemory {
    struct Segment { GPUVAddr gpu; u64 size; DAddr cpu; };
    std::vector<Segment> segments;
    std::vector<u8> guest = std::vector<u8>(u64{1} << 20);   // guest memory, indexed by (address & 0xFFFFF)
    size_t writebacks = 0;
    std::vector<std::pair<GPUVAddr, size_t>> GetSubmappedRange(GPUVAddr addr, size_t size) const {
        std::vector<std::pair<GPUVAddr, size_t>> pieces;
        for (const Segment& s : segments) {
            const u64 lo = std::max<u64>(addr, s.gpu);
            const u64 hi = std::min<u64>(addr + size, s.gpu + s.size);
            if (lo < hi) pieces.emplace_back(lo, hi - lo);
        }
        return pieces;
    }
    std::optional<DAddr> GpuToCpuAddress(GPUVAddr addr) const {
        for (const Segment& s : segments) {
            if (addr >= s.gpu && addr < s.gpu + s.size) return s.cpu + (addr - s.gpu);
        }
        return std::nullopt;
    }
};
inline void SwizzleImage(MockGpuMemory& memory, GPUVAddr gpu_addr, const ImageInfo& info,
                         const std::vector<int>&, std::span<u8>, std::vector<u8>&) {
    if (const auto cpu = memory.GpuToCpuAddress(gpu_addr)) {
        for (u64 i = 0; i < info.guest_size; ++i) memory.guest[(*cpu + i) & 0xFFFFF] = 0xAB;
        ++memory.writebacks;
    }
}
struct MockDeviceMemory {
    std::map<u64, int> counts;   // cached count per 4 KiB page
    void UpdatePagesCachedCount(u64 addr, u64 size, int delta) {
        for (u64 page = addr >> 12; page <= (addr + size - 1) >> 12; ++page) counts[page] += delta;
    }
    int at(u64 addr) const { const auto it = counts.find(addr >> 12); return it == counts.end() ? 0 : it->second; }
    bool balanced() const { for (const auto& [page, n] : counts) if (n != 0) return false; return true; }
};
struct MockRuntime {
    std::vector<std::string>* ops = nullptr;
    std::vector<u8> staging = std::vector<u8>(64);
    struct Map { std::span<u8> mapped_span; };
    void TransitionImageLayout(Image&) { ops->push_back("transition"); }
    void CopyImage(Image& dst, Image& src, const std::vector<ImageCopy>&) { ops->push_back("shrink " + std::to_string(src.gpu_addr)); }
    void CopyImageMSAA(Image& dst, Image& src, const std::vector<ImageCopy>&) { ops->push_back("shrink-msaa " + std::to_string(src.gpu_addr)); }
    Map DownloadStagingBuffer(size_t) { return Map{std::span<u8>(staging)}; }
    void Finish() {}
};

template <class P>
struct TextureCache {
    struct Images {
        std::vector<Image> v;
        Image& operator[](ImageId id) { return v.at(id.index); }
    } slot_images;
    MockDeviceMemory device_memory;
    MockGpuMemory gpu_storage;
    MockGpuMemory* gpu_memory = &gpu_storage;
    MockRuntime runtime;
    std::vector<std::string> ops;
    StalePages stale_pages;
    u64 tc_stale_skips{}, tc_stale_skip_bytes{}, tc_stale_gpu_written{};
    int uploads = 0;
    std::vector<u8> swizzle_data_buffer;
    std::vector<JoinCopy> join_copies_to_do;
    std::map<ImageId, size_t> join_alias_indices;

    TextureCache() { runtime.ops = &ops; }
    bool IsDownloadable(const ImageBase& image) const noexcept { return image.safe_copy; }
    bool MarkSparseWrite(ImageId, Image&, DAddr, size_t) { return false; }
    bool MarkPartialWrite(Image&, DAddr, size_t) { return false; }
    template <class... A> void LogWholeUpload(A&&...) {}
    bool IsWatchedImage(u64) const { return false; }
    template <class F> void ForEachImageInRegion(DAddr addr, size_t size, F&& f) {
        for (u32 i = 0; i < slot_images.v.size(); ++i) {
            Image& im = slot_images.v[i];
            if (im.registered && im.cpu_addr < addr + size && addr < im.cpu_addr + im.guest_size_bytes) f(ImageId{i}, im);
        }
    }
    void TrackImage(ImageBase& image, ImageId) {
        image.flags |= ImageFlagBits::Tracked;
        device_memory.UpdatePagesCachedCount(image.cpu_addr, image.guest_size_bytes, 1);
        ops.push_back("track");
    }
    void UntrackImage(ImageBase& image, ImageId id) {
        image.flags &= ~ImageFlagBits::Tracked;
        device_memory.UpdatePagesCachedCount(image.cpu_addr, image.guest_size_bytes, -1);
        ops.push_back("untrack " + std::to_string(id.index));
    }
    void UnregisterImage(ImageId id) { slot_images[id].registered = false; }
    void DeleteImage(ImageId id, bool = false) { ops.push_back("delete " + std::to_string(id.index)); }
    void ScaleUp(Image&) { ops.push_back("scaleup"); }
    void ScaleDown(Image&) { ops.push_back("scaledown"); }
    // The upload: every texel of every level and layer holds the guest's content (token 1000).
    void RefreshContents(Image& image, ImageId) {
        for (s32 level = 0; level < image.info.resources.levels; ++level)
            for (s32 layer = 0; layer < image.info.resources.layers; ++layer) image.cells[{level, layer}] = 1000;
        image.flags &= ~ImageFlagBits::CpuModified;
        ++uploads;
        ops.push_back("upload");
    }
    // A copy writes the source's token into every cell it covers whole, -1 into cells it covers in part.
    void CopyImage(ImageId dst_id, ImageId src_id, std::vector<ImageCopy> copies) {
        Image& dst = slot_images[dst_id];
        Image& src = slot_images[src_id];
        ops.push_back("copy " + std::to_string(dst_id.index) + "<-" + std::to_string(src_id.index));
        for (const ImageCopy& copy : copies) {
            const Extent3D size = MipSize(dst.info.size, u32(copy.dst_subresource.base_level));
            const bool whole = copy.extent.width >= size.width && copy.extent.height >= size.height &&
                               copy.dst_offset == Offset3D{};
            for (s32 layer = copy.dst_subresource.base_layer; layer < copy.dst_subresource.base_layer + copy.dst_subresource.num_layers; ++layer) {
                dst.cells[{copy.dst_subresource.base_level, layer}] =
                    whole ? src.cells[{copy.src_subresource.base_level, layer}] : -1;
            }
        }
    }
    void MarkStale(const ImageBase& image);
    void ClearStale(DAddr addr, size_t size);
    void ClearStaleImage(const ImageBase& image);
    void ClearStaleGpu(GPUVAddr gpu_addr, size_t size);
    void WriteMemory(DAddr cpu_addr, size_t size);
    void UnmapMemory(DAddr cpu_addr, size_t size);
    void DownloadMemory(DAddr cpu_addr, size_t size);
    void RefreshOrSkip(Image& image);
    void JoinTail(Image& new_image, ImageId new_image_id, ImageInfo& new_info, bool can_rescale, bool clear_overwrites);
};
''' + member('MarkStale(const ImageBase& image) {', 'void TextureCache<P>::MarkStale(const ImageBase&) {}') \
    + member('ClearStale(DAddr addr, size_t size) {', 'void TextureCache<P>::ClearStale(DAddr, size_t) {}') \
    + member('ClearStaleImage(const ImageBase& image) {', 'void TextureCache<P>::ClearStaleImage(const ImageBase&) {}') \
    + member('ClearStaleGpu(GPUVAddr gpu_addr, size_t size) {', 'void TextureCache<P>::ClearStaleGpu(GPUVAddr, size_t) {}') \
    + member('WriteMemory(DAddr cpu_addr, size_t size) {', 'void TextureCache<P>::WriteMemory(DAddr, size_t) {}') \
    + member('UnmapMemory(DAddr cpu_addr, size_t size) {', 'void TextureCache<P>::UnmapMemory(DAddr, size_t) {}') \
    + member('DownloadMemory(DAddr cpu_addr, size_t size) {', 'void TextureCache<P>::DownloadMemory(DAddr, size_t) {}') + r'''
// The stale decision of RefreshContents (absent on main), then what follows it: the upload.
template <class P>
void TextureCache<P>::RefreshOrSkip(Image& image) {
''' + stale_block + r'''    RefreshContents(image, ImageId{});
}
// The tail of JoinImages: the whole-copy search, the upload, the scaling, the copies.
template <class P>
void TextureCache<P>::JoinTail(Image& new_image, ImageId new_image_id, ImageInfo& new_info, bool can_rescale, bool clear_overwrites) {
    const auto overwritten_by_clear = [&] { return clear_overwrites; };
''' + join_tail + r'''}
} // namespace VideoCommon
using namespace VideoCommon;

static int failures = 0;
static void expect(u64 got, u64 want, const char* what) {
    if (got != want) {
        ++failures;
        std::printf("FAIL: %s: %llu, expected %llu\n", what, (unsigned long long)got, (unsigned long long)want);
    }
}
static void check(bool ok, const char* what) {
    if (!ok) {
        ++failures;
        std::printf("FAIL: %s\n", what);
    }
}
static void ops_are(const std::vector<std::string>& got, const std::vector<std::string>& want, const char* what) {
    if (got != want) {
        ++failures;
        std::printf("FAIL: %s:", what);
        for (const auto& op : got) std::printf(" [%s]", op.c_str());
        std::printf(" expected:");
        for (const auto& op : want) std::printf(" [%s]", op.c_str());
        std::printf("\n");
    }
}
static bool has(const std::vector<std::string>& ops, const std::string& op) {
    return std::find(ops.begin(), ops.end(), op) != ops.end();
}

// ------------------------------------------------------------------------------- GpuWrittenPages
static void gpu_written_pages() {
    namespace P = VideoCommon::GpuWrittenPages;
    const u64 base = u64{0x7000} << 16;
    check(!P::Any(base, 0x3000) && !P::AnyNonImage(base, 0x3000), "pages start unmarked");
    const u64 before = P::new_marks.load();
    P::MarkImage(base, 0x2000);   // an image write: the page bitmap, not the non-image one
    check(P::Any(base, 0x2000), "an image write marks the written pages");
    check(!P::AnyNonImage(base, 0x2000), "an image write is not a non-image write");
    check(P::new_marks.load() != before, "an image write counts as a new mark");
    P::Mark(base + 0x2000, 16);   // a buffer, query, semaphore or memory manager write
    check(P::AnyNonImage(base + 0x2000, 16) && P::Any(base + 0x2000, 16), "a non-image write marks both bitmaps");
    check(!P::AnyNonImage(base, 0x2000), "the neighbouring image pages stay image-only");
    check(P::AnyNonImage(base, 0x3000), "any page of the range marked");
    P::Mark(base, 1);   // a page that is already image-marked
    check(P::AnyNonImage(base, 0x1000), "a non-image write to an image-marked page");
    check(!P::AnyNonImage(base + 0x1000, 0x1000), "and only that page");
    check(!P::AnyNonImage(base, 0), "an empty range");
    check(P::AnyNonImage(u64{1} << 40, 16), "pages outside the device address space count as written");
}

// ---------------------------------------------------------------------------------- stale marking
constexpr u64 Page = 0x1000;
static u64 scenario_base = 0;
static u64 next_base() { return scenario_base += u64{1} << 24; }   // each scenario has its own device pages

struct Stale {
    TextureCache<int> c;
    Stale() { Tegra::g_nx2_ampere.store(true); c.slot_images.v.reserve(32); }
    ~Stale() { Tegra::g_nx2_ampere.store(false); }
    u32 add(DAddr cpu, size_t size, ImageFlagBits flags) {
        Image image;
        image.cpu_addr = cpu;
        image.guest_size_bytes = size;
        image.info.guest_size = size;
        image.flags = flags;
        image.registered = true;
        image.gpu_addr = cpu;
        image.info.resources = {1, 1};
        c.slot_images.v.push_back(image);
        const u32 id = u32(c.slot_images.v.size() - 1);
        if (True(flags & ImageFlagBits::Tracked)) c.device_memory.UpdatePagesCachedCount(cpu, size, 1);
        return id;
    }
    // What the collector does to an image it drops without a write-back.
    void drop(u32 id) {
        Image& image = c.slot_images.v[id];
        c.MarkStale(image);
        if (True(image.flags & ImageFlagBits::Tracked)) c.UntrackImage(image, ImageId{id});
        image.registered = false;
    }
    void mark_pages(u64 addr, u64 size) {
        c.stale_pages.Mark(addr, size, [&](u64 a, u64 s) { c.device_memory.UpdatePagesCachedCount(a, s, 1); });
    }
    // A new image on [cpu, cpu + size): CpuModified, refreshed. Returns the uploads it made.
    int refresh(DAddr cpu, size_t size, ImageFlagBits extra = ImageFlagBits::None) {
        const u32 id = add(cpu, size, ImageFlagBits::CpuModified | extra);
        c.ops.clear();
        const int before = c.uploads;
        c.RefreshOrSkip(c.slot_images.v[id]);
        return c.uploads - before;
    }
};
constexpr ImageFlagBits Gpu = ImageFlagBits::GpuModified | ImageFlagBits::Tracked;

static void stale_marking() {
    {   // Whole pages only: the pages shared with other data at either end stay unmarked.
        Stale s;
        const u64 b = next_base();
        const u32 id = s.add(b + 0x800, 0x3000, Gpu);   // pages b+0x1000 and b+0x2000 are whole
        s.drop(id);
        expect(s.c.stale_pages.Count(), 2, "partial boundary pages: whole pages marked");
        check(s.c.stale_pages.IsAll(b + 0x1000, 0x2000), "the whole pages are stale");
        check(!s.c.stale_pages.IsAll(b + 0x800, 0x3000), "the image's range is not all stale");
        expect(s.c.device_memory.at(b), 0, "boundary page is not kept tracked");
        expect(s.c.device_memory.at(b + 0x1000), 1, "a stale page stays tracked once");
        expect(s.c.device_memory.at(b + 0x2000), 1, "the other stale page stays tracked once");
        expect(s.c.device_memory.at(b + 0x3000), 0, "the last partial page is not tracked");
        Stale t;
        const u64 c0 = next_base();
        t.drop(t.add(c0, 0x4000, Gpu));
        expect(t.c.stale_pages.Count(), 4, "a page-aligned image: all four pages marked");
        check(t.c.stale_pages.IsAll(c0, 0x4000), "all stale");
        for (u64 p = 0; p < 4; ++p) expect(t.c.device_memory.at(c0 + p * Page), 1, "tracked once");
        expect(t.c.device_memory.at(c0 + 4 * Page), 0, "no page past the image");
    }
    {   // What does not mark: not Switch 2, not GPU-written, CPU-modified, sparse, unbacked.
        Stale s;
        const u64 b = next_base();
        Tegra::g_nx2_ampere.store(false);
        s.drop(s.add(b, 0x2000, Gpu));
        expect(s.c.stale_pages.Count(), 0, "a non-Switch 2 title");
        Tegra::g_nx2_ampere.store(true);
        s.drop(s.add(b + 0x10000, 0x2000, ImageFlagBits::Tracked));
        expect(s.c.stale_pages.Count(), 0, "an image the GPU did not write");
        s.drop(s.add(b + 0x20000, 0x2000, Gpu | ImageFlagBits::CpuModified));
        expect(s.c.stale_pages.Count(), 0, "a CPU-modified image: its pages hold the CPU's data");
        s.drop(s.add(b + 0x30000, 0x2000, Gpu | ImageFlagBits::Sparse));
        expect(s.c.stale_pages.Count(), 0, "a sparse image");
        s.drop(s.add(b + 0x40000, 0x2000, Gpu | ImageFlagBits::Unbacked));
        expect(s.c.stale_pages.Count(), 0, "an unbacked image");
        check(s.c.device_memory.balanced(), "tracking of the unmarked images released");
    }
}

static void stale_refresh() {
    {   // A new image wholly on stale pages is made without an upload; the pages a buffer wrote are uploaded.
        Stale s;
        const u64 b = next_base();
        s.drop(s.add(b, 0x4000, Gpu));
        expect(s.refresh(b, 0x4000), 0, "image on stale pages: uploads");
        expect(s.c.tc_stale_skips, 1, "skips counted");
        expect(s.c.tc_stale_skip_bytes, 0x4000, "skipped bytes counted");
        ops_are(s.c.ops, {"transition"}, "a skipped upload still prepares the layout");
        expect(s.refresh(b + 0x1000, 0x2000), 0, "a smaller image inside the stale pages: uploads");
        expect(s.refresh(b + 0x800, 0x2000), 0, "an image that touches only stale pages: skips");
        expect(s.refresh(b - 0x800, 0x2000), 1, "an image that touches a page outside the stale ones: uploads");
        expect(s.refresh(b, 0x5000), 1, "an image reaching past the stale pages: uploads");
    }
    {   // What the GPU wrote through anything but an image keeps the upload; image writes do not.
        Stale s;
        const u64 b = next_base();
        s.drop(s.add(b, 0x4000, Gpu));
        VideoCommon::GpuWrittenPages::MarkImage(b, 0x4000);   // the dropped image's own writes
        expect(s.refresh(b, 0x4000), 0, "pages written by images only: uploads");
        VideoCommon::GpuWrittenPages::Mark(b + 0x2000, 16);   // a buffer write
        expect(s.refresh(b, 0x4000), 1, "a page written by a buffer: uploads");
        expect(s.c.tc_stale_gpu_written, 1, "the buffer-written upload is counted");
        expect(s.refresh(b, 0x2000), 0, "the buffer-written page outside the image: uploads");
        expect(s.refresh(b + 0x3000, 0x1000), 0, "the other pages stay skipped");
    }
    {   // Other flags and a non-Switch 2 title keep the upload.
        Stale s;
        const u64 b = next_base();
        s.drop(s.add(b, 0x4000, Gpu));
        for (const ImageFlagBits flag : {ImageFlagBits::Sparse, ImageFlagBits::Unbacked, ImageFlagBits::Remapped})
            expect(s.refresh(b, 0x4000, flag), 1, "sparse, unbacked and remapped images: uploads");
        const u32 layered = s.add(b, 0x4000, ImageFlagBits::CpuModified);
        s.c.slot_images.v[layered].dirty_layers.assign(1, 1);
        s.c.RefreshOrSkip(s.c.slot_images.v[layered]);
        expect(s.c.uploads, 4, "an image with dirty layers: uploads");
        Tegra::g_nx2_ampere.store(false);
        expect(s.refresh(b, 0x4000), 1, "a non-Switch 2 title: uploads");
        Tegra::g_nx2_ampere.store(true);
        expect(s.refresh(b, 0x4000), 0, "back on a Switch 2 title: skips");
    }
}

static void stale_clearing() {
    {   // A CPU write clears every page it touches, releases their tracking, and the upload comes back.
        Stale s;
        const u64 b = next_base();
        s.drop(s.add(b, 0x4000, Gpu));
        s.c.WriteMemory(b + Page + 5, 1);
        expect(s.c.stale_pages.Count(), 3, "a one byte CPU write clears one page");
        expect(s.c.device_memory.at(b + Page), 0, "the written page is no longer tracked");
        expect(s.c.device_memory.at(b), 1, "the others stay tracked");
        expect(s.refresh(b, 0x4000), 1, "an image over a written page: uploads");
        expect(s.refresh(b + 2 * Page, 0x2000), 0, "an image over untouched stale pages: skips");
        s.c.WriteMemory(b + 2 * Page - 1, 2);   // straddles pages 1 (clear already) and 2
        expect(s.c.stale_pages.Count(), 2, "a write across a page boundary clears the page it reaches");
        check(!s.c.stale_pages.IsAll(b + 2 * Page, Page), "page 2 is no longer stale");
        check(s.c.stale_pages.IsAll(b + 3 * Page, Page) && s.c.stale_pages.IsAll(b, Page), "pages 0 and 3 stay stale");
        s.c.WriteMemory(b, 0x10000);
        expect(s.c.stale_pages.Count(), 0, "a big write clears all");
    }
    {   // A CPU write marks a live image CpuModified as before.
        Stale s;
        const u64 b = next_base();
        const u32 live = s.add(b, 0x2000, Gpu);
        s.c.WriteMemory(b, 4);
        check(True(s.c.slot_images.v[live].flags & ImageFlagBits::CpuModified), "a CPU write still marks the image");
        check(False(s.c.slot_images.v[live].flags & ImageFlagBits::Tracked), "and untracks it");
    }
    {   // An unmap clears too (and deletes the images there as before).
        Stale s;
        const u64 b = next_base();
        s.drop(s.add(b, 0x6000, Gpu));
        const u32 live = s.add(b + 0x10000, 0x1000, Gpu);
        s.c.UnmapMemory(b + Page, 2 * Page);
        expect(s.c.stale_pages.Count(), 4, "an unmap clears the pages it covers");
        s.c.UnmapMemory(b + 0x10000, 0x1000);
        check(has(s.c.ops, "delete " + std::to_string(live)), "an unmap still deletes the images");
        s.c.UnmapMemory(b, 0x6000);
        expect(s.c.stale_pages.Count(), 0, "an unmap of everything");
        check(s.c.device_memory.balanced(), "every page's tracking was released");
    }
    {   // An image write-back clears the pages of the image, not the rest, and writes its bytes.
        Stale s;
        const u64 b = next_base();
        s.drop(s.add(b, 0x8000, Gpu));
        const u32 live = s.add(b + 2 * Page, 2 * Page, Gpu);
        s.c.gpu_storage.segments.push_back({b + 2 * Page, 2 * Page, b + 2 * Page});
        s.c.DownloadMemory(b + 2 * Page, 2 * Page);
        expect(s.c.gpu_storage.writebacks, 1, "the image was written back");
        expect(s.c.gpu_storage.guest[(b + 2 * Page) & 0xFFFFF], 0xAB, "its bytes reached guest memory");
        expect(s.c.gpu_storage.guest[(b + 2 * Page + 2 * Page - 1) & 0xFFFFF], 0xAB, "up to its last byte");
        expect(s.c.stale_pages.Count(), 6, "the written back pages are no longer stale");
        check(!s.c.stale_pages.IsAll(b, 0x8000), "the range is not all stale");
        check(False(s.c.slot_images.v[live].flags & ImageFlagBits::GpuModified), "the write-back still clears GpuModified");
        expect(s.refresh(b + 2 * Page, 2 * Page), 1, "an image on the written back pages: uploads");
        expect(s.refresh(b + 4 * Page, 4 * Page), 0, "an image on the rest: skips");
    }
    {   // A write-back of a boundary-straddling image clears every page it touches.
        Stale s;
        const u64 b = next_base();
        s.drop(s.add(b, 0x4000, Gpu));
        s.c.ClearStaleImage(s.c.slot_images.v[s.add(b + 0x800, 0x1000, Gpu)]);
        expect(s.c.stale_pages.Count(), 2, "an image touching two pages clears both");
    }
    {   // A buffer write-back across mappings that are not contiguous in device memory clears every piece.
        Stale s;
        const u64 a = next_base();
        const u64 other = next_base();
        const u64 gpu = u64{0x40} << 24;
        s.mark_pages(a, 0x2000);
        s.mark_pages(other, 0x2000);
        s.c.gpu_storage.segments.push_back({gpu, 0x2000, a});
        s.c.gpu_storage.segments.push_back({gpu + 0x2000, 0x2000, other});
        s.c.ClearStaleGpu(gpu, 0x4000);
        expect(s.c.stale_pages.Count(), 0, "both device pieces of a buffer write-back are cleared");
        check(s.c.device_memory.balanced(), "and released");
        s.mark_pages(a, 0x2000);
        s.mark_pages(other, 0x2000);
        s.c.ClearStaleGpu(gpu + 0x2000, 0x2000);   // only the second mapping
        expect(s.c.stale_pages.Count(), 2, "a write-back of one mapping clears only that mapping");
        check(s.c.stale_pages.IsAll(a, 0x2000), "the first mapping stays stale");
    }
    {   // A sparse image's write-back is cleared through its mappings; a plain one through its CPU address.
        Stale s;
        const u64 a = next_base();
        const u64 other = next_base();
        const u64 gpu = u64{0x50} << 24;
        s.mark_pages(a, 0x2000);
        s.mark_pages(other, 0x2000);
        s.c.gpu_storage.segments.push_back({gpu, 0x2000, a});
        s.c.gpu_storage.segments.push_back({gpu + 0x2000, 0x2000, other});
        Image sparse;
        sparse.flags = ImageFlagBits::Sparse;
        sparse.gpu_addr = gpu;
        sparse.cpu_addr = u64{1} << 41;   // a stand-in far outside the device pages
        sparse.guest_size_bytes = 0x4000;
        s.c.ClearStaleImage(sparse);
        expect(s.c.stale_pages.Count(), 0, "a sparse image clears every mapping");
        s.mark_pages(a, 0x2000);
        Image plain;
        plain.cpu_addr = a;
        plain.guest_size_bytes = 0x1000;
        plain.gpu_addr = gpu;
        s.c.ClearStaleImage(plain);
        expect(s.c.stale_pages.Count(), 1, "a plain image clears the pages of its CPU range");
    }
}

// ---------------------------------------------------------------------------------- join copies
struct Join {
    TextureCache<int> c;
    ImageInfo new_info;
    bool rescale = false;
    bool clear = false;
    Join(s32 levels = 2, s32 layers = 3, u32 width = 5, u32 height = 4) {
        c.slot_images.v.reserve(16);
        Image image;
        image.gpu_addr = 0x100;
        image.cpu_addr = 0x100000;
        image.cpu_addr_end = 0x104000;
        image.guest_size_bytes = 0x4000;
        image.flags = ImageFlagBits::CpuModified;
        image.info.size = {width, height, 1};
        image.info.resources = {levels, layers};
        for (s32 l = 0; l < levels; ++l) for (s32 y = 0; y < layers; ++y) image.cells[{l, y}] = 0;
        c.slot_images.v.push_back(image);
        new_info = image.info;
    }
    Image& image() { return c.slot_images.v[0]; }
    std::vector<ImageCopy> whole() const {
        std::vector<ImageCopy> copies;
        for (s32 level = 0; level < new_info.resources.levels; ++level) copies.push_back(level_copy(level, true));
        return copies;
    }
    ImageCopy level_copy(s32 level, bool full) const {
        const Extent3D size = MipSize(new_info.size, u32(level));
        ImageCopy copy{};
        copy.src_subresource = {level, 0, new_info.resources.layers};
        copy.dst_subresource = copy.src_subresource;
        copy.extent = {full ? size.width : size.width - 1, size.height, 1};
        return copy;
    }
    // An alias of the new image: token index*100 in every cell; joined as AddImageAlias would.
    u32 alias(u64 tick, std::vector<ImageCopy> copies, ImageFlagBits flags = ImageFlagBits::None, bool safe = true,
              bool indexed = true) {
        Image a;
        const u32 index = u32(c.slot_images.v.size());
        a.gpu_addr = 0x100 + index;
        a.info = new_info;
        a.modification_tick = tick;
        a.flags = flags;
        a.safe_copy = safe;
        for (s32 l = 0; l < new_info.resources.levels; ++l)
            for (s32 y = 0; y < new_info.resources.layers; ++y) a.cells[{l, y}] = int(index) * 100;
        c.slot_images.v.push_back(a);
        if (indexed) {
            image().aliased_images.push_back({std::move(copies), ImageId{index}});
            c.join_alias_indices.emplace(ImageId{index}, image().aliased_images.size() - 1);
        }
        c.join_copies_to_do.push_back(JoinCopy{true, ImageId{index}});
        return index;
    }
    // One layer of one level, written whole (or short of a texel column when !full).
    ImageCopy layer_copy(s32 level, s32 layer, bool full = true) const {
        ImageCopy copy = level_copy(level, full);
        copy.src_subresource = {level, 0, 1};
        copy.dst_subresource = {level, layer, 1};
        return copy;
    }
    // A GPU-modified, non-alias overlap whose shrink copies are `shrink`; returns its slot index.
    u32 overlap(u64 tick, std::vector<ImageCopy> shrink, ImageFlagBits flags = ImageFlagBits::None, bool base = true) {
        Image o;
        const u32 index = u32(c.slot_images.v.size());
        o.gpu_addr = 0x100 + index;
        o.info = new_info;
        o.info.shrink = std::move(shrink);
        o.flags = ImageFlagBits::GpuModified | ImageFlagBits::Tracked | flags;
        o.registered = true;
        o.cpu_addr = 0x200000 + index * 0x1000;
        o.cpu_addr_end = o.cpu_addr + 0x1000;
        o.guest_size_bytes = 0x1000;
        o.modification_tick = tick;
        o.has_base = base;
        c.slot_images.v.push_back(o);
        c.join_copies_to_do.push_back(JoinCopy{false, ImageId{index}});
        return index;
    }
    // Every layer of every level as its own overlap, except the (level, layer) pairs in `skip`.
    void per_layer_overlaps(std::vector<std::pair<s32, s32>> skip = {}) {
        u64 tick = 1;
        for (s32 level = 0; level < new_info.resources.levels; ++level)
            for (s32 layer = 0; layer < new_info.resources.layers; ++layer)
                if (std::find(skip.begin(), skip.end(), std::pair<s32, s32>{level, layer}) == skip.end())
                    overlap(tick++, {layer_copy(level, layer)});
    }
    void run() {
        c.ops.clear();
        c.JoinTail(image(), ImageId{0}, new_info, rescale, clear);
    }
    int cell(s32 level, s32 layer) { return image().cells[{level, layer}]; }
    bool all_cells(int token) {
        for (const auto& [key, value] : image().cells) if (value != token) return false;
        return true;
    }
};

static void join_copies() {
    {   // One alias copy writes every texel: no upload, the copy, the same contents.
        Join j;
        j.alias(7, j.whole());
        j.run();
        expect(j.c.uploads, 0, "whole alias copy: uploads");
        ops_are(j.c.ops, {"track", "transition", "scaledown", "copy 0<-1"}, "whole alias copy: operations");
        check(j.all_cells(100), "whole alias copy: every texel holds the alias");
        check(False(j.image().flags & ImageFlagBits::CpuModified), "whole alias copy: the image is not CpuModified");
        check(True(j.image().flags & ImageFlagBits::Tracked), "whole alias copy: the image is tracked");
        expect(j.image().modification_tick, 7, "whole alias copy: modification tick");
    }
    {   // A later partial copy still runs over a whole one; an earlier partial one is dropped by a later whole one.
        Join j;
        j.alias(1, j.whole());
        j.alias(2, {j.level_copy(0, true)});
        j.run();
        expect(j.c.uploads, 0, "whole then partial: uploads");
        ops_are(j.c.ops, {"track", "transition", "scaledown", "copy 0<-1", "copy 0<-2"}, "whole then partial: copies run in order");
        check(j.cell(0, 0) == 200 && j.cell(0, 2) == 200 && j.cell(1, 0) == 100 && j.cell(1, 2) == 100,
              "whole then partial: contents");
        Join k;
        k.alias(1, {k.level_copy(0, true)});
        k.alias(2, k.whole());
        k.run();
        expect(k.c.uploads, 0, "partial then whole: uploads");
        ops_are(k.c.ops, {"track", "transition", "scaledown", "copy 0<-2"}, "partial then whole: the earlier copy is skipped");
        check(k.all_cells(200), "partial then whole: contents");
        Join m;   // two aliases that each cover one mip: together whole, but no single copy is
        m.alias(1, {m.level_copy(0, true)});
        m.alias(2, {m.level_copy(1, true)});
        m.run();
        expect(m.c.uploads, 1, "two partial copies: uploads");
        ops_are(m.c.ops, {"upload", "scaledown", "copy 0<-1", "copy 0<-2"}, "two partial copies: operations");
        check(m.cell(0, 0) == 100 && m.cell(1, 0) == 200 && m.cell(0, 2) == 100, "two partial copies: contents");
    }
    {   // Partial copies keep the upload: missing mip, fewer layers, an offset, a smaller extent.
        Join j;
        j.alias(1, {j.level_copy(0, true)});
        j.run();
        expect(j.c.uploads, 1, "a copy of the first mip only: uploads");
        check(j.cell(0, 0) == 100 && j.cell(1, 0) == 1000, "the uncopied mip keeps the guest's upload");
        Join l;
        auto copies = l.whole();
        for (auto& copy : copies) copy.dst_subresource.num_layers = 2;
        l.alias(1, copies);
        l.run();
        expect(l.c.uploads, 1, "a copy of fewer layers: uploads");
        check(l.cell(0, 2) == 1000, "the uncopied layer keeps the guest's upload");
        Join o;
        auto offset = o.whole();
        offset[0].dst_offset.x = 1;
        o.alias(1, offset);
        o.run();
        expect(o.c.uploads, 1, "a copy from an offset: uploads");
        Join e;
        auto small = e.whole();
        small[1].extent.width -= 1;
        e.alias(1, small);
        e.run();
        expect(e.c.uploads, 1, "a copy that leaves an edge column: uploads");
        check(e.cell(0, 0) == 100 && e.cell(1, 0) == -1, "the edge copy leaves a partly copied mip");
        Join f;
        auto from_layer = f.whole();
        from_layer[0].dst_subresource.base_layer = 1;
        f.alias(1, from_layer);
        f.run();
        expect(f.c.uploads, 1, "a copy that starts at another layer: uploads");
    }
    {   // Scaling, formats, flags: the upload stays.
        Join j;
        j.rescale = true;
        j.alias(1, j.whole());
        j.run();
        expect(j.c.uploads, 1, "a rescaled join: uploads");
        ops_are(j.c.ops, {"upload", "scaleup", "copy 0<-1"}, "a rescaled join: operations");
        Join k;
        k.new_info.format = PixelFormat::BC1_RGBA_UNORM;
        k.image().info.format = PixelFormat::BC1_RGBA_UNORM;
        k.alias(1, k.whole());
        k.run();
        expect(k.c.uploads, 1, "a compressed format: uploads");
        Join m;
        m.alias(1, m.whole());
        m.c.slot_images.v[1].info.format = PixelFormat::R32_FLOAT;
        m.run();
        expect(m.c.uploads, 1, "another format: uploads");
        Join n;
        n.alias(1, n.whole());
        n.c.slot_images.v[1].info.astc_opaque = true;
        n.run();
        expect(n.c.uploads, 1, "another ASTC opacity: uploads");
        Join t;
        t.alias(1, t.whole());
        t.c.slot_images.v[1].info.type = ImageType::e3D;
        t.run();
        expect(t.c.uploads, 1, "a 3D alias: uploads");
        for (const ImageFlagBits flag : {ImageFlagBits::Rescaled, ImageFlagBits::TrimmedLevels, ImageFlagBits::Unbacked, ImageFlagBits::Sparse}) {
            Join src;
            src.alias(1, src.whole(), flag);
            src.run();
            expect(src.c.uploads, 1, "a rescaled, trimmed, unbacked or sparse alias: uploads");
            Join dst;
            dst.image().flags |= flag;
            dst.alias(1, dst.whole());
            dst.run();
            expect(dst.c.uploads, 1, "a rescaled, trimmed, unbacked or sparse new image: uploads");
        }
        Join s;   // a sparse new image is bound by RefreshContents before the copies run
        s.image().flags |= ImageFlagBits::Sparse;
        s.alias(1, s.whole());
        s.run();
        ops_are(s.c.ops, {"upload", "scaledown", "copy 0<-1"}, "sparse new image: operations");
    }
    {   // An alias that is not copied does not count: unsafe, other sample count, not joined.
        Join j;
        j.alias(1, j.whole(), ImageFlagBits::None, false);
        j.run();
        ops_are(j.c.ops, {"upload", "scaledown"}, "an unsafe alias: uploaded, not copied");
        Join k;
        k.alias(1, k.whole());
        k.c.slot_images.v[1].info.num_samples = 4;
        k.run();
        ops_are(k.c.ops, {"upload", "scaledown"}, "an alias with another sample count: uploaded, not copied");
        Join m;
        m.alias(1, m.whole(), ImageFlagBits::None, true, false);
        m.run();
        ops_are(m.c.ops, {"upload", "scaledown"}, "an alias AddImageAlias rejected: uploaded, not copied");
        Join n;   // a skipped whole copy must not hide an earlier one that is the only valid copy
        n.alias(1, {n.level_copy(0, true)});
        n.alias(2, n.whole(), ImageFlagBits::None, false);
        n.run();
        ops_are(n.c.ops, {"upload", "scaledown", "copy 0<-1"}, "an unsafe whole copy does not skip the upload");
    }
    {   // A full clear keeps its own handling; a whole copy still runs after it.
        Join j;
        j.clear = true;
        j.alias(1, j.whole());
        j.run();
        expect(j.c.uploads, 0, "a clear: uploads");
        ops_are(j.c.ops, {"transition", "scaledown", "copy 0<-1"}, "a clear: operations");
        check(True(j.image().flags & ImageFlagBits::CpuModified), "a clear leaves CpuModified for PrepareImage");
        Join k;
        k.clear = true;
        k.alias(1, {k.level_copy(0, true)});
        k.run();
        ops_are(k.c.ops, {"transition", "scaledown", "copy 0<-1"}, "a clear with a partial copy: operations");
    }
    {   // Non-alias overlaps (GPU-modified ones are copied and deleted) are unchanged under a whole alias copy.
        Join j;
        const u32 gpu_overlap = u32(j.c.slot_images.v.size());
        Image overlap;
        overlap.gpu_addr = 0x100 + gpu_overlap;
        overlap.flags = ImageFlagBits::GpuModified | ImageFlagBits::Tracked;
        overlap.registered = true;
        overlap.cpu_addr = 0x200000;
        overlap.cpu_addr_end = 0x201000;
        overlap.guest_size_bytes = 0x1000;
        overlap.modification_tick = 1;
        j.c.slot_images.v.push_back(overlap);
        j.c.join_copies_to_do.push_back(JoinCopy{false, ImageId{gpu_overlap}});
        j.alias(2, j.whole());
        j.run();
        expect(j.c.uploads, 0, "gpu overlap and whole alias: uploads");
        check(has(j.c.ops, "shrink " + std::to_string(0x100 + gpu_overlap)), "the GPU-modified overlap is still copied");
        check(has(j.c.ops, "untrack " + std::to_string(gpu_overlap)) && has(j.c.ops, "delete " + std::to_string(gpu_overlap)),
              "and untracked and deleted");
        check(has(j.c.ops, "copy 0<-2"), "the whole alias copy runs");
        check(True(j.image().flags & ImageFlagBits::GpuModified), "the image is GpuModified as before");
    }
}

static void whole_copy_helper() {
    Join j(2, 3, 5, 4);
    const ImageBase& dst = j.image();
    Join src_join(2, 3, 5, 4);
    src_join.alias(1, {});
    const ImageBase& src = src_join.c.slot_images.v[1];
    check(CopiesWriteWholeImage(dst, src, j.whole()), "every level and layer, unscaled");
    check(!CopiesWriteWholeImage(dst, src, std::vector<ImageCopy>{}), "no copies");
    auto bigger = j.whole();
    for (auto& copy : bigger) { copy.extent.width += 4; copy.extent.height += 4; copy.dst_subresource.num_layers += 1; }
    check(CopiesWriteWholeImage(dst, src, bigger), "a copy larger than the image is still whole");
}

static void multi_image_copies() {
    {   // Several GPU-modified images each write one layer (and level): together whole, so no upload.
        Join j;
        j.per_layer_overlaps();
        j.run();
        expect(j.c.uploads, 0, "layer overlaps covering the image: uploads");
        check(has(j.c.ops, "shrink 257") && has(j.c.ops, "shrink 262"), "every overlap is still copied");
        check(False(j.image().flags & ImageFlagBits::CpuModified), "layer overlaps: the image is not CpuModified");
        check(True(j.image().flags & ImageFlagBits::Tracked), "layer overlaps: the image is tracked");
        check(True(j.image().flags & ImageFlagBits::GpuModified), "layer overlaps: the image is GpuModified");
        check(has(j.c.ops, "transition") && !has(j.c.ops, "upload"), "layer overlaps: transitioned, not uploaded");
    }
    {   // The same split across mips of one layer set: two overlaps, each a whole level over all layers.
        Join j;
        j.overlap(1, {j.level_copy(0, true)});
        j.overlap(2, {j.level_copy(1, true)});
        j.run();
        expect(j.c.uploads, 0, "one overlap a mip: uploads");
    }
    {   // One layer missing: the upload stays.
        Join j;
        j.per_layer_overlaps({{1, 2}});
        j.run();
        expect(j.c.uploads, 1, "one layer missing: uploads");
        Join k;
        k.per_layer_overlaps({{0, 1}});
        k.run();
        expect(k.c.uploads, 1, "another layer missing: uploads");
    }
    {   // Partial extent, offset, other format, compressed: no mark.
        Join j;
        j.per_layer_overlaps({{1, 0}});
        j.overlap(9, {j.layer_copy(1, 0, false)});
        j.run();
        expect(j.c.uploads, 1, "a partial extent: uploads");
        Join o;
        o.per_layer_overlaps({{1, 0}});
        ImageCopy moved = o.layer_copy(1, 0);
        moved.dst_offset = {1, 0, 0};
        o.overlap(9, {moved});
        o.run();
        expect(o.c.uploads, 1, "a copy at an offset: uploads");
        Join f;
        f.per_layer_overlaps();
        f.c.slot_images.v[3].info.format = PixelFormat::R32_FLOAT;
        f.run();
        expect(f.c.uploads, 1, "one overlap of another format: uploads");
        Join b;
        b.new_info.format = PixelFormat::BC1_RGBA_UNORM;
        b.image().info.format = PixelFormat::BC1_RGBA_UNORM;
        b.per_layer_overlaps();
        b.run();
        expect(b.c.uploads, 1, "a compressed format: uploads");
    }
    {   // Source and destination flags: Rescaled, TrimmedLevels, Unbacked, Sparse.
        for (const ImageFlagBits flag : {ImageFlagBits::Rescaled, ImageFlagBits::TrimmedLevels, ImageFlagBits::Unbacked, ImageFlagBits::Sparse}) {
            Join s;
            s.per_layer_overlaps();
            s.c.slot_images.v[2].flags |= flag;
            s.run();
            expect(s.c.uploads, 1, "a rescaled, trimmed, unbacked or sparse overlap: uploads");
            Join d;
            d.image().flags |= flag;
            d.per_layer_overlaps();
            d.run();
            expect(d.c.uploads, 1, "a rescaled, trimmed, unbacked or sparse new image: uploads");
        }
    }
    {   // Overlaps that do not count: not GPU-modified, multisampled, no base, other type; a rescaled join.
        Join a;
        a.per_layer_overlaps();
        a.c.slot_images.v[2].flags &= ~ImageFlagBits::GpuModified;
        a.run();
        expect(a.c.uploads, 1, "a CPU-only overlap does not count: uploads");
        Join m;
        m.per_layer_overlaps();
        m.c.slot_images.v[2].info.num_samples = 4;
        m.run();
        expect(m.c.uploads, 1, "a multisampled overlap does not count: uploads");
        Join b;
        b.per_layer_overlaps();
        b.c.slot_images.v[2].has_base = false;
        b.run();
        expect(b.c.uploads, 1, "an overlap without a base is skipped, not crashed on: uploads");
        Join t;
        t.per_layer_overlaps();
        t.c.slot_images.v[2].info.type = ImageType::e3D;
        t.run();
        expect(t.c.uploads, 1, "a 3D overlap does not count: uploads");
        Join r;
        r.rescale = true;
        r.per_layer_overlaps();
        r.run();
        expect(r.c.uploads, 1, "a rescaled join: uploads");
        Join n;
        n.new_info.num_samples = 4;
        n.image().info.num_samples = 4;
        n.per_layer_overlaps();
        n.run();
        expect(n.c.uploads, 1, "a multisampled join: uploads");
    }
    {   // An alias copy that is whole keeps its own path; a clear keeps its own handling.
        Join j;
        j.per_layer_overlaps({{1, 2}});
        j.alias(20, j.whole());
        j.run();
        expect(j.c.uploads, 0, "whole alias copy with partial overlaps: uploads");
        Join k;
        k.clear = true;
        k.per_layer_overlaps();
        k.run();
        expect(k.c.uploads, 0, "a clear: uploads");
        check(has(k.c.ops, "transition"), "a clear: transitioned");
    }
    {   // Overlaps and a partial alias copy together cover the image: the alias still copies, no upload.
        Join j;
        j.per_layer_overlaps({{0, 0}});
        j.alias(20, {j.layer_copy(0, 0)});
        j.run();
        expect(j.c.uploads, 1, "a partial alias copy is not an overlap's mark: uploads");
    }
}

static void mark_helper() {
    Join j(1, 3, 5, 4);
    const ImageBase& dst = j.image();
    Join src_join(1, 3, 5, 4);
    src_join.alias(1, {});
    const ImageBase& src = src_join.c.slot_images.v[1];
    std::vector<u8> written(3);
    MarkSubresourcesWrittenWhole(dst, src, std::vector<ImageCopy>{j.layer_copy(0, 0)}, written);
    MarkSubresourcesWrittenWhole(dst, src, std::vector<ImageCopy>{j.layer_copy(0, 2)}, written);
    check(written == std::vector<u8>{1, 0, 1}, "marks add up over several calls");
    Join other(1, 3, 5, 4);
    other.alias(1, {});
    other.c.slot_images.v[1].info.format = PixelFormat::R32_FLOAT;
    MarkSubresourcesWrittenWhole(dst, other.c.slot_images.v[1], std::vector<ImageCopy>{j.layer_copy(0, 1)}, written);
    check(written == std::vector<u8>{1, 0, 1}, "another format sets nothing");
    MarkSubresourcesWrittenWhole(dst, src, std::vector<ImageCopy>{j.layer_copy(0, 1, false)}, written);
    check(written == std::vector<u8>{1, 0, 1}, "a partial extent sets nothing");
    MarkSubresourcesWrittenWhole(dst, src, std::vector<ImageCopy>{j.layer_copy(0, 1)}, written);
    check(written == std::vector<u8>{1, 1, 1}, "the missing layer completes it");
    check(CopiesWriteWholeImage(dst, src, std::vector<ImageCopy>{j.layer_copy(0, 0), j.layer_copy(0, 1), j.layer_copy(0, 2)}),
          "CopiesWriteWholeImage: layer copies of one source add up");
    check(!CopiesWriteWholeImage(dst, src, std::vector<ImageCopy>{j.layer_copy(0, 0), j.layer_copy(0, 2)}),
          "CopiesWriteWholeImage: a layer missing");
}

int main() {
    gpu_written_pages();
    stale_marking();
    stale_refresh();
    stale_clearing();
    join_copies();
    whole_copy_helper();
    mark_helper();
    multi_image_copies();
    std::puts(failures ? "Stale texture uploads FAILED" : "Stale texture uploads: PASS");
    return failures ? 1 : 0;
}
'''
(out / 'stale.cpp').write_text(test)

failed = False


def require(ok, message):
    global failed
    if not ok:
        failed = True
        print('FAIL: ' + message)


if not source_only:
    exe = out / 'stale'
    subprocess.run(['clang++-18', '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
                    '-I' + str(out), '-I' + str(src), str(out / 'stale.cpp'), '-o', str(exe)], check=True)
    failed |= subprocess.run([str(exe)]).returncode != 0

# ------------------------------------------------------------------------------- source checks
require(have_stale_pages, 'stale_pages.h is missing')
require(have_non_image, 'GpuWrittenPages has no MarkImage / AnyNonImage')
require('CopiesWriteWholeImage(' in util, 'util.cpp has no CopiesWriteWholeImage')
require('MarkSubresourcesWrittenWhole(' in util and 'MarkSubresourcesWrittenWhole(' in (src / 'video_core/texture_cache/util.h').read_text(),
        'UB-150: util has no MarkSubresourcesWrittenWhole')
require('CopiesWriteWholeImage(' in (src / 'video_core/texture_cache/util.h').read_text(), 'util.h does not declare it')

collector = function(cache, 'void TextureCache<P>::RunGarbageCollector() {')
require(collector.count('MarkStale(image);') == 1, 'the collector must mark stale pages in exactly one place')

def in_order(text, *needles):
    """Every needle is in text, first occurrences in the given order."""
    positions = [text.find(needle) for needle in needles]
    return -1 not in positions and positions == sorted(positions)


require(in_order(collector, 'const auto Cleanup', 'if (must_download) {', 'SwizzleImage(', 'if (!must_download) {',
                 'UntrackImage(image, image_id);'),
        'the collector: the stale decision follows the download branch and precedes UntrackImage')
# Decided by must_download itself, not by the shape of the download branch: the console build
# (tools/prepare-vulkan-port.py) skips that branch for an image a batch wrote back already, whose
# pages hold its data and must not be marked.
require('        if (!must_download) {\n            MarkStale(image); // before UntrackImage (see MarkStale)\n'
        '        } else {\n            ClearStaleImage(image);\n        }' in collector,
        'the collector marks only images it does not write back, and clears the pages of those it does')
require('if (must_download) {' in collector and collector.count('if (must_download) {') == 1,
        'the collector\'s download branch is the one prepare-vulkan-port.py pins')
# The console build's batched DownloadMemory publishes through its own SwizzleImage.
batch_inc = (root / 'headless/vulkan_download_batch.inc').read_text()
require(in_order(batch_inc, 'SwizzleImage(', 'ClearStaleImage(image);', 'pending.clear();'),
        'headless/vulkan_download_batch.inc does not clear stale pages after its write-back')
require(cache.count('MarkStale(image)') == 1, 'MarkStale is called outside the collector')
for signature in ('void TextureCache<P>::DeleteImage(ImageId image_id, bool immediate_delete) {',
                  'ImageId TextureCache<P>::JoinImages('):
    require('MarkStale' not in function(cache, signature),
            'ordinary deletions must not mark pages stale: ' + signature)

pop = function(cache, 'void TextureCache<P>::PopAsyncFlushes() {')
require(in_order(pop, 'gpu_memory->WriteBlockUnsafe(buffer_info.address',
                 'ClearStaleGpu(buffer_info.address, buffer_info.size);',
                 'slot_buffer_downloads.erase(download_info.object_id);'),
        'the buffer write-back does not clear every device range')
position, swizzles = 0, 0
while True:
    position = pop.find('SwizzleImage(', position)
    if position == -1:
        break
    end = pop.index(';', position) + 1
    require(pop[end:].lstrip().startswith('ClearStaleImage(image);'), 'a PopAsyncFlushes image write-back does not clear stale pages')
    swizzles += 1
    position = end
require(swizzles == 2, 'PopAsyncFlushes has not the two image write-backs the test knows')

refresh = function(cache, 'void TextureCache<P>::RefreshContents(Image& image, ImageId image_id) {')
stale_at = refresh.find('Made where a dropped GPU-written image left stale bytes')
require(stale_at != -1, 'RefreshContents does not skip uploads of stale pages')
if stale_at != -1:
    require(in_order(refresh, 'image.feedback_source = ImageId{};', 'Made where a dropped GPU-written image'),
            '99zzzz2: the feedback copy is forgotten before the skip')
    require(in_order(refresh, 'InvalidateAsyncDecode(image);', 'Made where a dropped GPU-written image'),
            'the async decode invalidation precedes the skip')
    for upload in ('if (!image.dirty_layers.empty() && UploadWrittenLayers(image))', 'QueueAsyncDecode(',
                   'UploadConvertedInChunks(', 'UploadInChunks('):
        require(in_order(refresh, 'Made where a dropped GPU-written image', upload), 'the stale skip comes after ' + upload)
    require('Tegra::g_nx2_ampere' in refresh[stale_at:stale_at + 600], 'the stale skip is not Switch 2 only')
require('GpuWrittenPages::Mark(' not in cache, 'the texture cache marks image writes with the non-image Mark')

join = function(cache, 'ImageId TextureCache<P>::JoinImages(')
if 'const auto alias_copy' in join:
    require(in_order(join, 'join_alias_indices.emplace(aliased_id, alias_index);', 'RefreshContents(new_image, new_image_id);'),
            'the upload precedes the alias bookkeeping it depends on')
    require(in_order(join, 'std::ranges::sort(join_copies_to_do', 'const auto alias_copy'), 'the copies are not sorted first')
    require('!can_rescale && index-- > 0' in join, 'the whole-copy search is not 1x only')
if 'MarkSubresourcesWrittenWhole(' in join:
    require(in_order(join, 'CopiesWriteWholeImage(new_image', 'MarkSubresourcesWrittenWhole(new_image', 'if (overwritten_by_clear()) {'),
            'UB-150: the accumulation follows the alias search and precedes the upload')
    require('!can_rescale && !copied_whole && new_info.num_samples == 1' in join, 'UB-150: the accumulation is not 1x only')
    accumulation = join[join.index('!can_rescale && !copied_whole'):]
    accumulation = accumulation[:accumulation.index('copied_whole = std::ranges::all_of')]
    require('.value()' not in accumulation and 'if (!base)' in accumulation, 'UB-150: the accumulation does not skip an overlap without a base')
require('MarkSubresourcesWrittenWhole(' in join, 'UB-150: JoinImages does not accumulate copies from several images')
require('runtime.FlushDeferredClear();' in function(cache, 'void TextureCache<P>::CopyImage('), '99zw\'s deferred clear flush is gone')
require('Settings::values.gpu_unswizzle_enabled' in refresh, 'RefreshContents changed beyond the stale skip')
print('Source checks ' + ('FAILED' if failed else 'PASS'))
sys.exit(1 if failed else 0)
