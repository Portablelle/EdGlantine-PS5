"""UB-097: a draw that samples its own colour target through an alias copies it once per barrier.

Donkey Kong Bananza binds a G-buffer target as 2112x1179 and samples the same memory as a 2095x1179
texture; main's TextureCache::SynchronizeAliases copied the whole target before every draw that
sampled it (UpdateRenderTargets marks the target modified at each draw). Compiled with the PRODUCTION
SynchronizeAliases, InvalidateAsyncDecode, the first part of RefreshContents (up to the statistics:
the CpuModified early return and the forgetting of the remembered copy before any upload path), the
deleted-image hook and texture_barrier_epoch.h, over a recording backend: repeated writes and samples
of the same bound target with no barrier, target change or other write copy ONCE; a guest texture
barrier, a changed render target set or source, a source id reused after deletion, compute and
non-feedback reads, format NONE, an unbound, differently mapped or out of range target copy what
they need. Anything else that wrote the sampled image after the remembered copy (a CPU upload through
RefreshContents, a background decode, a GPU write, another alias copied in, a second newer alias)
makes the next sample copy again, and a skipped copy leaves the image older than the target.
EDEN_NX2_FEEDBACK_COPIES=exact and 0 copy before every draw, 1 behaves as the default. Then source
checks that Maxwell3D notes the three barrier registers, that the forgetting precedes every upload
call of RefreshContents, that FillImageViews marks only graphics preparation and that 99zw's switch
is kept. Fails on main by behavior (a copy per draw). NOT run where no compiler exists.

Usage: check-feedback-alias-copies.py [SOURCE_DIR]   SOURCE_DIR is the tree that contains src/
(default: this checkout's prepared build cache). Negative control: run this script against the
prepared source of main (a tree without layer 99zzzz2).
"""
from pathlib import Path
import os
import platform
import subprocess
import sys

assert platform.system() == 'Linux', 'Run on the Linux build server'
root = Path(__file__).resolve().parents[1]
if len(sys.argv) > 1:
    source = Path(sys.argv[1]).resolve()
else:
    source = Path((root / '.local/headless-cache').read_text().strip()) / 'source'
src = source / 'src'
cache = (src / 'video_core/texture_cache/texture_cache.h').read_text()
out = root / 'build/nx2-tests/feedback-alias-copies'
(out / 'common').mkdir(parents=True, exist_ok=True)


def function(text, signature):
    assert text.count(signature) == 1, 'Missing production code: ' + signature
    start = text.index(signature)
    end = text.index('{', start) + 1
    depth = 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end] + '\n'


sync = function(cache, 'void TextureCache<P>::SynchronizeAliases(ImageId image_id) {')
invalidate = function(cache, 'inline void InvalidateAsyncDecode(ImageBase& image) noexcept {')
refresh_signature = 'void TextureCache<P>::RefreshContents(Image& image, ImageId image_id) {'
refresh_full = function(cache, refresh_signature)
# The part of RefreshContents that runs before any upload: the CpuModified early return, the
# async decode invalidation and (with this layer) the forgetting of the remembered feedback copy.
refresh_cut = 'if (refresh_counts.size() < 4096'
assert refresh_cut in refresh_full, 'RefreshContents changed: ' + refresh_cut
refresh_head = refresh_full[:refresh_full.index(refresh_cut)] + '}\n'
# Main has no such hook: the stand-in is empty and the behavior checks fail on their own.
hook_opening = 'if (other_image.feedback_source == image_id) {'
hook = function(cache, hook_opening) if hook_opening in cache else ''

(out / 'common/common_types.h').write_text(
    '#pragma once\n#include <cstddef>\n#include <cstdint>\n'
    'using u8 = std::uint8_t; using u32 = std::uint32_t; using u64 = std::uint64_t;\n')

test = r'''
#include "common/common_types.h"
#include <algorithm>
#include <array>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <string_view>
#include <utility>
#include <vector>
#if __has_include("video_core/texture_barrier_epoch.h")
#include "video_core/texture_barrier_epoch.h"
#else
namespace VideoCommon {
inline std::atomic<u64> texture_barrier_epoch{};
inline void NoteTextureBarrier() { texture_barrier_epoch.fetch_add(1, std::memory_order_relaxed); }
}
#endif
namespace boost::container { template <class T, size_t N> using small_vector = std::vector<T>; }
namespace Tegra { enum class RenderTargetFormat : u32 { NONE = 0, RGBA8 = 1 }; }
namespace Settings { struct R { bool active = false; }; struct V { R resolution_info; }; inline V values; }
namespace VideoCommon {
constexpr size_t NUM_RT = 8;
namespace GpuWrittenPages { inline void Mark(u64, u64) {} }
namespace Dirty { constexpr size_t RenderTargets = 0; }
struct ImageId {
    u32 index = ~0u;
    explicit operator bool() const { return index != ~0u; }
    bool operator==(const ImageId&) const = default;
};
struct ImageViewId {
    u32 index = ~0u;
    explicit operator bool() const { return index != ~0u; }
};
enum class ImageFlagBits : u32 { None = 0, GpuModified = 1, Rescaled = 2, IsDecoding = 4, CpuModified = 8 };
constexpr ImageFlagBits operator|(ImageFlagBits a, ImageFlagBits b) { return ImageFlagBits(u32(a) | u32(b)); }
constexpr ImageFlagBits operator&(ImageFlagBits a, ImageFlagBits b) { return ImageFlagBits(u32(a) & u32(b)); }
constexpr ImageFlagBits operator~(ImageFlagBits a) { return ImageFlagBits(~u32(a)); }
inline ImageFlagBits& operator|=(ImageFlagBits& a, ImageFlagBits b) { return a = a | b; }
inline ImageFlagBits& operator&=(ImageFlagBits& a, ImageFlagBits b) { return a = a & b; }
constexpr bool True(ImageFlagBits f) { return u32(f) != 0; }
constexpr bool False(ImageFlagBits f) { return u32(f) == 0; }
struct AliasedImage { ImageId id; int copies; };
struct ImageBase {
    u64 modification_tick = 0;
    ImageFlagBits flags = ImageFlagBits::None;
    u64 cpu_addr = 0, cpu_addr_end = 0;
    u64 async_decode_generation = 0;
    std::vector<AliasedImage> aliased_images;
    ImageId feedback_source{};
    u64 feedback_barrier_epoch = 0;
    u64 feedback_rt_serial = 0;
    u64 feedback_tick = 0;
};
using Image = ImageBase;
struct ImageViewBase { ImageId image_id; };
struct Maxwell3D {
    struct RT { Tegra::RenderTargetFormat format = Tegra::RenderTargetFormat::NONE; };
    struct RtControl {
        u32 count = 0;
        std::array<u32, 8> maps{};
        u32 Map(size_t index) const { return maps.at(index); }   // the engine's Map asserts index < 8
    };
    struct Regs { RtControl rt_control; std::array<RT, 8> rt{}; } regs;
    struct DirtyState { std::array<bool, 8> flags{}; } dirty;
};
struct RenderTargetsMock { std::array<ImageViewId, NUM_RT> color_buffer_ids{}; };
'''
test += invalidate
test += r'''
template <class P>
struct TextureCache {
    struct Images { std::vector<Image> v; Image& operator[](ImageId id) { return v.at(id.index); } } slot_images;
    struct Views { std::vector<ImageViewBase> v; ImageViewBase& operator[](ImageViewId id) { return v.at(id.index); } } slot_image_views;
    RenderTargetsMock render_targets;
    Maxwell3D maxwell;
    Maxwell3D* maxwell3d = &maxwell;
    u64 render_targets_serial = 0;
    bool feedback_sampling = false;
    std::vector<std::pair<u32, u32>> copy_log;
    int uploads = 0;
    bool ImageCanRescale(Image&) { return false; }
    void ScaleUp(Image&) {}
    void ScaleDown(Image&) {}
    void CopyImage(ImageId dst, ImageId src, int) { copy_log.emplace_back(dst.index, src.index); }
    void SynchronizeAliases(ImageId image_id);
    void RefreshContents(Image& image, ImageId image_id);
};
'''
test += 'template <class P>\n' + sync
# The production prefix of RefreshContents, then a stand-in for the uploads that follow it.
test += 'template <class P>\n' + refresh_head.rstrip()[:-1] + '    ++uploads;\n}\n'
test += '\nvoid DropFeedbackSource(ImageBase& other_image, ImageId image_id) {\n' + hook + r'''}
} // namespace VideoCommon
using namespace VideoCommon;

static int failures = 0;
static void expect(size_t got, size_t want, const char* what) {
    if (got != want) {
        ++failures;
        std::printf("FAIL: %s: %zu, expected %zu\n", what, got, want);
    }
}
static void check(bool ok, const char* what) {
    if (!ok) {
        ++failures;
        std::printf("FAIL: %s\n", what);
    }
}

// Image 0 is the sampled alias, 1 the bound colour target, 2 another alias of the same memory.
struct Fixture {
    TextureCache<int> c;
    u64 tick = 0;
    Fixture() {
        c.slot_images.v.resize(3);
        c.slot_image_views.v.resize(3);
        c.slot_images.v[0].aliased_images = {{ImageId{1}, 0}, {ImageId{2}, 0}};
        for (u32 i = 0; i < 3; ++i) c.slot_image_views.v[i].image_id = ImageId{i};
        c.maxwell.regs.rt_control.count = 1;
        c.maxwell.regs.rt[0].format = Tegra::RenderTargetFormat::RGBA8;
        c.render_targets.color_buffer_ids[0] = ImageViewId{1};
        c.feedback_sampling = true;
        c.render_targets_serial = 1;
    }
    Image& sampled() { return c.slot_images.v[0]; }
    void write(u32 id) { c.slot_images.v[id].modification_tick = ++tick; }
    u64 at(u32 id) { return c.slot_images.v[id].modification_tick; }
    size_t copies() const { return c.copy_log.size(); }
    std::pair<u32, u32> last() const { return c.copy_log.back(); }
    size_t sync() {
        const size_t before = c.copy_log.size();
        c.SynchronizeAliases(ImageId{0});
        return c.copy_log.size() - before;
    }
    // One draw: the target is written, then the draw's texture views are prepared.
    size_t draw() {
        write(1);
        return sync();
    }
    size_t draws(int count) {
        size_t total = 0;
        for (int n = 0; n < count; ++n) total += draw();
        return total;
    }
    // The guest rewrote the sampled image's memory and PrepareImage refreshes it (RefreshContents).
    void cpu_upload() {
        sampled().flags |= ImageFlagBits::CpuModified;
        c.RefreshContents(sampled(), ImageId{0});
    }
};

int main(int argc, char**) {
    if (argc > 1) {
        // EDEN_NX2_FEEDBACK_COPIES=exact or 0: a copy before every draw.
        Fixture f;
        expect(f.draws(5), 5, "exact mode: copies for five draws");
        std::puts(failures ? "exact mode FAILED" : "exact mode: a copy before every draw PASS");
        return failures ? 1 : 0;
    }
    {   // Repeated writes and samples, no barrier: one copy; the image stays older than the target.
        Fixture f;
        expect(f.draw(), 1, "first sample copies the target");
        const u64 copied_tick = f.at(0);
        expect(f.draws(4), 0, "later samples with no barrier copy");
        check(f.at(0) == copied_tick && f.at(0) < f.at(1),
              "a skipped copy advanced the image's tick");
        std::printf("same target, no barrier: %zu copies for 5 draws\n", f.copies());
        expect(f.copies(), 1, "copies for five draws");
        // A guest texture barrier: the pending target is copied once, then coalesced again.
        VideoCommon::NoteTextureBarrier();
        expect(f.sync(), 1, "copies after a barrier");
        expect(f.draws(2), 0, "copies after the barrier's copy");
        // A changed render target set.
        ++f.c.render_targets_serial;
        expect(f.draw(), 1, "copies after a render target set change");
        expect(f.draw(), 0, "copies once coalescing resumes");
    }
    {   // RenderTargets dirty: the set is not known yet; exact copies, nothing recorded.
        Fixture f;
        f.c.maxwell.dirty.flags[Dirty::RenderTargets] = true;
        expect(f.draws(3), 3, "dirty render targets: copies for three draws");
        f.c.maxwell.dirty.flags[Dirty::RenderTargets] = false;
        expect(f.draw(), 1, "first clean draw");
        expect(f.draw(), 0, "second clean draw");
    }
    {   // Compute and non-feedback reads copy; a deferred copy is still pending for them.
        Fixture f;
        f.draws(2);
        check(f.at(0) < f.at(1), "deferred copy is not pending");
        f.c.feedback_sampling = false;
        expect(f.sync(), 1, "a non-feedback read copies the pending target");
        check(f.at(0) == f.at(1), "the image is not current after that copy");
        expect(f.draws(3), 3, "compute / non-feedback: copies for three writes");
        f.c.feedback_sampling = true;
        expect(f.draw(), 1, "first feedback sample after non-feedback copies");
        expect(f.draw(), 0, "then coalesces");
    }
    {   // Format NONE, no targets, mapped, unmapped and out of range targets.
        Fixture f;
        f.c.maxwell.regs.rt[0].format = Tegra::RenderTargetFormat::NONE;
        expect(f.draws(3), 3, "format NONE: copies for three draws");
        Fixture g;
        g.c.maxwell.regs.rt_control.count = 0;
        expect(g.draws(3), 3, "no bound targets: copies for three draws");
        Fixture m;   // rt_control maps shader output 0 to render target 3, which holds the target.
        m.c.maxwell.regs.rt_control.maps[0] = 3;
        m.c.render_targets.color_buffer_ids[0] = ImageViewId{};
        m.c.render_targets.color_buffer_ids[3] = ImageViewId{1};
        m.c.maxwell.regs.rt[0].format = Tegra::RenderTargetFormat::NONE;
        m.c.maxwell.regs.rt[3].format = Tegra::RenderTargetFormat::RGBA8;
        expect(m.draws(3), 1, "mapped render target index: copies for three draws");
        Fixture u;   // the target sits in slot 0 but the draw maps output 0 to the empty slot 2.
        u.c.maxwell.regs.rt_control.maps[0] = 2;
        expect(u.draws(3), 3, "target not reached through the mapping: copies for three draws");
        Fixture w;   // a count above the eight targets must not read past the arrays.
        w.c.maxwell.regs.rt_control.count = 12;
        w.c.render_targets.color_buffer_ids[0] = ImageViewId{};
        expect(w.draws(3), 3, "control count above the target count, none bound: copies for three draws");
        Fixture o;   // a mapping outside the eight targets binds nothing.
        o.c.maxwell.regs.rt_control.maps[0] = 9;
        expect(o.draws(3), 3, "mapping out of range: copies for three draws");
    }
    {   // Source replaced: a new image at the id of the deleted target, then a changed source.
        Fixture f;
        f.draws(2);
        f.c.slot_images.v[1] = Image{};
        DropFeedbackSource(f.c.slot_images.v[0], ImageId{1});
        expect(f.draw(), 1, "source id reused after deletion");
        expect(f.draw(), 0, "after the reused id's copy");
        Fixture g;
        g.draws(2);
        g.c.render_targets.color_buffer_ids[0] = ImageViewId{2};   // the other alias is now bound
        g.write(2);
        expect(g.sync(), 2, "a different source copies both newer aliases");
        g.write(2);
        expect(g.sync(), 1, "the new source's first sample after that");
        g.write(2);
        expect(g.sync(), 0, "the new source after its copy");
    }
    {   // A CPU upload into the sampled image forgets the remembered copy; so does a background decode.
        Fixture f;
        f.draws(2);
        f.cpu_upload();
        expect(size_t(f.c.uploads), 1, "the upload ran");
        expect(f.draw(), 1, "target copied again after a CPU upload");
        expect(f.draw(), 0, "and coalesced again");
        Fixture g;   // a refresh with nothing to upload leaves it as it was
        g.draws(2);
        g.c.RefreshContents(g.sampled(), ImageId{0});
        expect(g.draw(), 0, "a refresh with nothing to upload");
        Fixture d;
        d.draws(2);
        d.sampled().flags |= ImageFlagBits::IsDecoding;   // a decode will land over the image
        expect(d.draws(3), 3, "image decoding in the background: copies for three draws");
        d.sampled().flags &= ~ImageFlagBits::IsDecoding;
        expect(d.draw(), 1, "first sample after the decode landed");
        expect(d.draw(), 0, "then coalesces");
    }
    {   // Anything else that wrote the sampled image after the remembered copy.
        Fixture a;   // a GPU write into it (MarkModification moved its tick)
        a.draw();
        a.sampled().modification_tick = ++a.tick;
        expect(a.draw(), 1, "target copied again after a GPU write to the sampled image");
        expect(a.draw(), 0, "and coalesced again");
        Fixture b;   // an unrelated alias copied in while the target was not newer
        b.draw();
        b.write(2);
        expect(b.sync(), 1, "the unrelated alias");
        check(b.last() == std::make_pair(0u, 2u), "the unrelated alias was not the one copied");
        expect(b.draw(), 1, "target sampled again after the unrelated alias overwrote the image");
        check(b.last() == std::make_pair(0u, 1u), "the target was not the one copied");
        expect(b.draw(), 0, "and coalesced again");
        Fixture e;   // the target was skipped, then a third alias and the target are both newer
        e.draws(2);
        e.write(2);
        expect(e.sync(), 2, "two newer aliases copy both");
        check(e.c.copy_log[e.copies() - 2] == std::make_pair(0u, 1u) && e.last() == std::make_pair(0u, 2u),
              "copies not in tick order");
        check(e.at(0) == e.at(2), "the image is not current after the third alias");
        expect(e.draw(), 1, "target sampled again in the same epoch after a third alias");
        check(e.last() == std::make_pair(0u, 1u), "the target was not the one copied");
        expect(e.draw(), 0, "and coalesced again");
    }
    {   // An older unrelated alias and the target are both newer: nothing is skipped.
        Fixture g;
        g.draw();
        g.write(2);   // the unrelated alias is older than the target's next write
        g.write(1);
        expect(g.sync(), 2, "an older unrelated alias and the target: copies");
        check(g.c.copy_log[g.copies() - 2] == std::make_pair(0u, 2u) && g.last() == std::make_pair(0u, 1u),
              "copies not in tick order");
        check(g.at(0) == g.at(1), "the target was skipped while another alias overwrote the image");
        expect(g.draw(), 1, "the target sampled once more");
        expect(g.draw(), 0, "then coalesced");
        Fixture f;   // the unbound alias is the newest
        f.draw();
        f.write(1);
        f.write(2);
        expect(f.sync(), 2, "a newer unrelated alias: copies");
        Fixture h;   // a tie for the newest
        h.draw();
        h.write(1);
        h.c.slot_images.v[2].modification_tick = h.at(1);
        expect(h.sync(), 2, "a tie for the newest alias: copies");
    }
    {   // Rescaled images keep the exact copies.
        Fixture f;
        f.c.slot_images.v[1].flags = ImageFlagBits::Rescaled;
        expect(f.draws(3), 3, "rescaled target: copies for three draws");
    }
    std::puts(failures ? "Feedback alias copies FAILED" : "Feedback alias copies: PASS");
    return failures ? 1 : 0;
}
'''
(out / 'feedback.cpp').write_text(test)
exe = out / 'feedback'
subprocess.run(['clang++-18', '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
                '-I' + str(out), '-I' + str(src), str(out / 'feedback.cpp'), '-o', str(exe)], check=True)

failed = False
# 'default' and '1' take the coalescing path, 'exact' and '0' the copy before every draw.
for value, args in ((None, []), ('1', []), ('exact', ['exact']), ('0', ['exact'])):
    env = {k: v for k, v in os.environ.items() if k != 'EDEN_NX2_FEEDBACK_COPIES'}
    if value is not None:
        env['EDEN_NX2_FEEDBACK_COPIES'] = value
    print('== EDEN_NX2_FEEDBACK_COPIES=' + (value if value is not None else '(unset)'))
    sys.stdout.flush()
    failed |= subprocess.run([str(exe)] + args, env=env).returncode != 0


def require(ok, message):
    global failed
    if not ok:
        failed = True
        print('FAIL: ' + message)


# Source: what the compiled test cannot reach.
maxwell = (src / 'video_core/engines/maxwell_3d.cpp').read_text()
process = function(maxwell, 'void Maxwell3D::ProcessMethodCall(')
for register in ('fragment_barrier', 'invalidate_texture_data_cache', 'tiled_cache_barrier'):
    start = process.index('case MAXWELL3D_REG_INDEX(' + register + '):')
    end = process.find('case MAXWELL3D_REG_INDEX', start + 1)
    require('VideoCommon::NoteTextureBarrier();' in process[start:end if end != -1 else None],
            register + ' does not count a guest texture barrier')
require((src / 'video_core/texture_barrier_epoch.h').exists(), 'texture_barrier_epoch.h is missing')
image_base = (src / 'video_core/texture_cache/image_base.h').read_text()
for field in ('ImageId feedback_source', 'u64 feedback_barrier_epoch', 'u64 feedback_rt_serial',
              'u64 feedback_tick'):
    require(field in image_base, 'ImageBase has no ' + field)
# The forgetting is in the production path, in front of every way RefreshContents overwrites the image.
forget = 'image.feedback_source = ImageId{};'
require(forget in refresh_full, 'RefreshContents does not forget the remembered feedback copy')
if forget in refresh_full:
    at = refresh_full.index(forget)
    require(refresh_full.index('InvalidateAsyncDecode(image);') < at, 'the forgetting precedes the async decode invalidation')
    for upload in ('RefreshPartialContents(', 'UploadWrittenLayers(', 'QueueAsyncDecode(', 'QueueAsyncUnswizzle(',
                   'UploadConvertedInChunks(', 'UploadInChunks(', 'UploadImageContents('):
        found = refresh_full.find(upload)
        if found != -1:
            require(at < found, 'RefreshContents calls ' + upload + ' before it forgets the feedback copy')
fill = function(cache, 'void TextureCache<P>::FillImageViews(')
require('feedback_sampling = !compute;' in fill and 'feedback_sampling = false;' in fill and
        fill.index('feedback_sampling = !compute;') < fill.index('VisitImageView(') <
        fill.index('feedback_sampling = false;') < fill.index('ReplaceColorFeedbackViews(views)'),
        'FillImageViews does not mark exactly the graphics view preparation')
require("value == nullptr || value[0] != '0'" in function(
    cache, 'void TextureCache<P>::ReplaceColorFeedbackViews('), "99zw's EDEN_NX2_FEEDBACK_COPIES=0 switch is gone")
print('Source checks ' + ('FAILED' if failed else 'PASS'))
sys.exit(1 if failed else 0)
