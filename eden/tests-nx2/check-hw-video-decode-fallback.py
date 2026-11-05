"""Compile standalone production session and the real PS5 backend on dedie.

Only external frame storage/allocation and Sony exports are recording dependencies.
No production declarations, functions or translation units are reconstructed.
"""
from pathlib import Path
import os
import platform
import subprocess
import tempfile

assert platform.system() == 'Linux', 'Compile on dedie'
root = Path(__file__).resolve().parents[1]
source = Path((root / '.local/headless-cache').read_text().strip()) / 'source/src'
host1x = source / 'video_core/host1x'
native = (source / 'core/hle/service/am/service/native_video_decoder.cpp').read_text()
assert 'h264_backend.Decode(' in native, 'native video hardware selection hook missing'
assert (host1x / 'hardware_video_decoder.cpp').is_file(), 'standalone hardware session missing'
# Integration points requiring the full emulator/FFmpeg build remain presence checks only.
for hook in ('h264_backend.Reset(', 'h264_backend.Finish(', 'h264_backend.TakeRestartPacket(',
             'h264_backend.SoftwareResult(', 'h264_backend.ConfigureH264('):
    assert hook in native, hook
ffmpeg_source = (host1x / 'ffmpeg.cpp').read_text()
for hook in ('m_backend.Decode(', 'm_backend.Reset(', 'm_backend.TakeRestartPacket(',
             'm_backend.SoftwareResult(', 'bool IsBackendFrameValid('):
    assert hook in ffmpeg_source, hook
cmake = (source / 'video_core/CMakeLists.txt').read_text()
for unit in ('hardware_video_decoder.cpp', 'hardware_video_decoder.h', 'video_decode.h'):
    assert 'host1x/' + unit in cmake, unit
# The sceVideodec2 functions are imports of the firmware module (as in EVO): loading it by path
# and resolving with sceKernelDlsym found no symbol on the console (0x80020003).
assert 'libSceVideodec2.so' in (root / 'headless/CMakeLists.txt').read_text()
assert 'build-videodec2-stub.sh' in (root / 'tools/prepare-build.sh').read_text()
assert 'libSceVideodec2.so' in (root / 'tools/package-headless-native.sh').read_text()
assert 'libSceVideodec2.sprx' not in (root / 'headless/check_package.py').read_text()
stub = (root / 'tools/stubs/libSceVideodec2.c').read_text()
for function in ('QueryComputeMemoryInfo', 'AllocateComputeQueue', 'ReleaseComputeQueue',
                 'QueryDecoderMemoryInfo', 'CreateDecoder', 'DeleteDecoder', 'MapDirectMemory',
                 'Reset', 'Decode', 'Flush'):
    assert f'int sceVideodec2{function}(void)' in stub, function
decoder = (root / 'headless/ps5_video_decoder.cpp').read_text()
assert 'sceKernelDlsym(' not in decoder and 'sceKernelLoadStartModule(' not in decoder

ffmpeg = r'''#pragma once
#include <array>
#include "video_core/host1x/hardware_video_decoder.h"
constexpr int AV_PIX_FMT_NV12 = 1, AV_PIX_FMT_YUV420P = 2, AV_PIX_FMT_YUVJ420P = 3;
using AVColorSpace = int;
constexpr int AVCOL_SPC_UNSPECIFIED = 2, AVCOL_RANGE_JPEG = 2, AVCOL_RANGE_MPEG = 1;
struct AVFrame {
    int width{}, height{}, format{}, colorspace = 1, color_range{};
    s64 pts{};
    size_t crop_top{}, crop_bottom{}, crop_left{}, crop_right{};
    std::array<u8*, 3> data{};
    std::array<int, 3> linesize{};
};
inline int av_frame_get_buffer(AVFrame*, int) { return 0; } // Recording Frame already owns planes.
namespace FFmpeg {
class Frame {
public:
    Frame() {
        width = 64; height = 32; format = AV_PIX_FMT_NV12; strides = {80, 80, 40};
        planes[0].fill(0x11); planes[1].fill(0x22); planes[2].fill(0x33);
    }
    mutable AVFrame native;
    int& width = native.width;
    int& height = native.height;
    int& format = native.format;
    bool hardware = false, missing_plane = false;
    std::array<int, 3>& strides = native.linesize;
    std::array<std::array<u8, 4096>, 3> planes{};
    int GetWidth() const { return width; }
    int GetHeight() const { return height; }
    int GetPixelFormat() const { return format; }
    int GetStride(int plane) const { return strides[plane]; }
    const u8* GetPlane(int plane) const {
        return missing_plane && plane == 1 ? nullptr : planes[plane].data();
    }
    AVFrame* GetFrame() const {
        native.width = width; native.height = height; native.format = format;
        native.linesize = strides;
        for (int i = 0; i < 3; ++i) native.data[i] = const_cast<u8*>(GetPlane(i));
        return &native;
    }
    bool IsHardwareDecoded() const { return hardware; }
};
}
'''

cpp = r'''
#include <algorithm>
#include <cstdio>
#include <array>
#include <atomic>
#include <cassert>
#include <cstdlib>
#include <cstdint>
#include <cstring>
#include <chrono>
#include <deque>
#include <map>
#include <string>
#include <thread>
#include <set>
#include <unistd.h>
#include <memory>
#include <optional>
#include <queue>
#include <span>
#include <string_view>
#include <utility>
#include <vector>
#include "video_core/host1x/ffmpeg.h"
#include "ps5_video_decoder.h"
#include "ps5_video_helpers.h"
#include "ps5_videodec2_abi.h"

struct Counts { int factories{}, supports{}, opens{}, decodes{}, closes{}, software{}; } counts;
int warnings{};
std::vector<u8> last_software_packet, last_hardware_extradata;
namespace FFmpeg {
void HardwareVideoDecoder::ReportFallback(const char*) { ++warnings; }
// Recording FFmpeg frame facade delegates to the production validator.
bool IsBackendFrameValid(const Frame& frame, const FrameDimensions& dimensions, s64 pts) {
    return Eden::VideoDecode::ValidFrame(frame, dimensions.width, dimensions.height, pts,
                                         AV_PIX_FMT_NV12, AV_PIX_FMT_YUV420P);
}
}

using namespace FFmpeg;
using Tegra::Host1x::NvdecCommon::VideoCodec;
bool fail_open = false, fail_decode = false, no_frame = false, null_factory = false;
int bad_frame = 0;
struct MockBackend : HardwareVideoDecoder {
    bool Supports(VideoCodec codec, const FrameDimensions& d) const override {
        ++counts.supports;
        return ((codec == VideoCodec::H264 && d.profile == 100) ||
                (codec == VideoCodec::VP9 && d.profile == 0)) && d.width <= 4096 && d.height <= 2160;
    }
    bool Open(VideoCodec, const FrameDimensions&, std::span<const u8> extradata) override {
        ++counts.opens;
        last_hardware_extradata.assign(extradata.begin(), extradata.end());
        return !fail_open;
    }
    bool Decode(std::span<const u8>, s64 pts, std::shared_ptr<Frame>& out) override {
        ++counts.decodes;
        if (fail_decode) return false;
        if (no_frame) return true;
        out = std::make_shared<Frame>();
        out->native.pts = pts;
        out->native.colorspace = 9;
        out->native.color_range = AVCOL_RANGE_JPEG;
        switch (bad_frame) {
        case 1: out->format = 999; break;
        case 2: out->strides[1] = 1; break;
        case 3: out->native.crop_left = 1; break;
        case 4: out->width = 63; break;
        case 5: out->missing_plane = true; break;
        case 6: out->hardware = true; break;
        case 7: out->format = AV_PIX_FMT_YUV420P; break;
        case 8: out->native.pts = pts + 1; break;
        }
        if (out->format == AV_PIX_FMT_NV12)
            for (size_t i = 1; i < out->planes[1].size(); i += 2) out->planes[1][i] = 0x33;
        return true;
    }
    void Close() override { ++counts.closes; }
};
std::unique_ptr<HardwareVideoDecoder> Factory() {
    ++counts.factories;
    return null_factory ? nullptr : std::make_unique<MockBackend>();
}
const std::array<u8, 6> idr{0, 0, 0, 1, 0x65, 0xb8}, inter{0, 0, 0, 1, 0x41, 0xc0};
const std::array<u8, 1> vp9_key{0x82}, vp9_inter{0x86};
const FrameDimensions high{64, 32, 100}, vp9{64, 32, 0};
FrameOffsets Offsets(u64 luma = 42) { FrameOffsets o; o.luma = luma; return o; }
void Setup(bool registered = true) {
    counts = {}; warnings = 0;
    last_software_packet.clear(); last_hardware_extradata.clear();
    fail_open = fail_decode = no_frame = null_factory = false; bad_frame = 0;
    unsetenv("EDEN_PS5_HW_VIDEODEC");
    RegisterHardwareVideoDecoder(registered ? Factory : nullptr);
}

using Route = HardwareVideoDecoderSession::Route;
using State = HardwareVideoDecoderSession::State;
Route Submit(HardwareVideoDecoderSession& session, std::span<const u8> packet,
             VideoCodec codec = VideoCodec::H264, std::optional<FrameDimensions> dimensions = high,
             FrameOffsets offsets = {}, s64 pts = 1) {
    std::shared_ptr<Frame> frame;
    const auto route = session.Decode(codec, packet, offsets, dimensions, pts, {}, frame);
    if (route == Route::Software) {
        ++counts.software;
        last_software_packet = session.TakeRestartPacket();
        if (last_software_packet.empty()) last_software_packet.assign(packet.begin(), packet.end());
    } else if (route == Route::Hardware && !offsets.hidden) assert(frame && frame->GetFrame()->pts == pts);
    else assert(!frame || offsets.hidden);
    return route;
}
void CheckSession() {
    Setup(false);
    { HardwareVideoDecoderSession session;
      assert(session.GetState() == State::Selection);
      assert(Submit(session, idr) == Route::Software && session.GetState() == State::Software);
      assert(counts.factories == 0 && !session.SoftwareResult(false));
      session.Finish(); assert(session.GetState() == State::Software);
      session.Reset(); assert(session.GetState() == State::Selection); }
    for (auto codec : {VideoCodec::H264, VideoCodec::VP9}) {
        Setup(); HardwareVideoDecoderSession session;
        assert(Submit(session, codec == VideoCodec::H264 ? std::span<const u8>{idr} : vp9_key,
                      codec, codec == VideoCodec::H264 ? high : vp9) == Route::Hardware);
        assert(session.GetState() == State::Hardware && counts.opens == 1 && !counts.software);
        session.Finish(); assert(session.GetState() == State::Recovery && counts.closes == 1);
        session.Finish(); assert(counts.closes == 1);
    }
    for (int mode = 0; mode < 8; ++mode) {
        Setup(); HardwareVideoDecoderSession session;
        auto d = high; auto offsets = Offsets();
        if (mode == 1) d.profile = 244;
        if (mode == 2) d.width = 8192;
        if (mode == 3) d.profile = -1;
        if (mode == 4) d.height = 0;
        if (mode == 6) offsets.interlaced = true;
        if (mode == 7) d.height = 8192;
        assert(Submit(session, idr, mode == 0 ? VideoCodec::VP8 : VideoCodec::H264,
                      mode == 5 ? std::nullopt : std::optional{d}, offsets) == Route::Software);
        assert(counts.opens == 0 && session.GetState() == State::Software);
    }
    Setup(); setenv("EDEN_PS5_HW_VIDEODEC", "0", 1);
    { HardwareVideoDecoderSession session;
      assert(Submit(session, idr) == Route::Software && !counts.factories); }
    Setup(); null_factory = true;
    { HardwareVideoDecoderSession session; assert(Submit(session, idr) == Route::Software); }
    Setup(); fail_open = true;
    { HardwareVideoDecoderSession session;
      assert(Submit(session, inter) == Route::Software); // Open failure needs no IDR wait.
      assert(session.GetState() == State::Fallback && counts.closes == 1 && warnings == 1);
      fail_open = false;
      assert(Submit(session, inter) == Route::Software && counts.opens == 1);
      assert(!counts.decodes); }
    for (auto codec : {VideoCodec::H264, VideoCodec::VP9}) {
        Setup(); HardwareVideoDecoderSession session;
        auto key = codec == VideoCodec::H264 ? std::span<const u8>{idr} : vp9_key;
        auto delta = codec == VideoCodec::H264 ? std::span<const u8>{inter} : vp9_inter;
        auto d = codec == VideoCodec::H264 ? high : vp9;
        assert(Submit(session, key, codec, d) == Route::Hardware);
        fail_decode = true;
        assert(Submit(session, delta, codec, d) == Route::Skipped);
        assert(session.GetState() == State::Recovery && !session.IsActive());
        fail_decode = false;
        assert(Submit(session, delta, codec, d) == Route::Skipped && !counts.software);
        assert(Submit(session, key, codec, d) == Route::Software);
        assert(session.GetState() == State::Fallback);
        for (int i = 0; i < 4; ++i) assert(Submit(session, delta, codec, d) == Route::Software);
        assert(counts.opens == 1 && counts.decodes == 2 && counts.closes == 1 && warnings == 1);
        assert(session.SoftwareResult(false) && session.GetState() == State::Recovery);
        assert(Submit(session, delta, codec, d) == Route::Skipped);
        assert(Submit(session, key, codec, d) == Route::Software);
        assert(session.SoftwareResult(true) && session.GetState() == State::Fallback);
        session.Reset(); assert(session.GetState() == State::Selection);
        assert(Submit(session, key, codec, d) == Route::Hardware && counts.opens == 2);
    }
    for (int mode = 0; mode < 9; ++mode) {
        Setup(); no_frame = mode == 0; bad_frame = mode;
        HardwareVideoDecoderSession session;
        const auto route = Submit(session, idr);
        assert(route == (mode == 7 ? Route::Hardware : Route::Software));
        assert(counts.closes == (mode == 7 ? 0 : 1));
    }
    Setup(); no_frame = true;
    { HardwareVideoDecoderSession session; auto hidden = Offsets(); hidden.hidden = true;
      assert(Submit(session, vp9_key, VideoCodec::VP9, vp9, hidden) == Route::Hardware);
      assert(!counts.software && !warnings); }
    Setup();
    { HardwareVideoDecoderSession session; assert(Submit(session, idr) == Route::Hardware);
      auto changed = high; changed.profile = 244;
      assert(Submit(session, idr, VideoCodec::H264, changed) == Route::Software);
      assert(counts.closes == 1 && counts.decodes == 1); }
}

namespace Sony {
constexpr int Error = static_cast<int>(0x811d0200U);
struct Allocation { void* address{}; size_t bytes{}, alignment{}; };
struct State {
    std::string failure;
    std::vector<std::string> calls;
    std::vector<u8> last_au;
    std::map<int64_t, Allocation> direct;
    std::set<void*> flexible;
    int64_t next = 0x4000;
    unsigned decodes{}, creates{}, deletes{}, queues{}, releases{};
    unsigned direct_count{}, fail_direct_index{};
    u32 codec{};
    bool no_picture{}, buffered{}, pending{}, bad_pitch{}, bad_bounds{}, bad_size{}, output_error{};
    int Call(const char* name) { calls.push_back(name); return failure == name ? Error : 0; }
} state;
void Clean() {
    assert(state.direct.empty() && state.flexible.empty());
    assert(state.queues == state.releases);
}
void Setup() { Clean(); state = {}; }
// Independent of per-stream decoder state: the production loader lives for this process.
struct LoaderState {
    unsigned sysmodule_loads{};
    int rc{};
} loader;
void Fill(SceVideodec2FrameBuffer* fb, SceVideodec2OutputInfo* out) {
    fb->accepted = 1;
    out->valid = 1; out->picture_count = 1; out->codec = state.codec;
    out->width = 64; out->height = 32; out->pitch = 80; out->pitch_bytes = 80;
    out->buffer = static_cast<u8*>(fb->buffer) + 64;
    out->buffer_size = fb->buffer_size - 64;
    auto* p = static_cast<u8*>(out->buffer);
    std::memset(p, state.decodes == 1 ? 0x11 : 0x44, 80 * 32);
    for (unsigned i = 0; i < 80 * 16; ++i) p[80 * 32 + i] = i % 2 ? 0x33 : 0x22;
    if (state.bad_pitch) out->pitch_bytes = 79;
    if (state.bad_bounds) out->buffer_size = 1;
    if (state.bad_size) out->size = 1;
    if (state.output_error) out->error = 1;
}
}
extern "C" {
// The module comes from the system module service; its functions are linked imports.
int sceSysmoduleLoadModule(uint16_t id) {
    assert(id == 207);
    ++Sony::loader.sysmodule_loads;
    return Sony::loader.rc;
}
int64_t sceKernelGetDirectMemorySize() { return 512 * 1024 * 1024; }
int sceKernelAllocateDirectMemory(int64_t from, int64_t to, size_t size, size_t align, int type, int64_t* start) {
    assert(from == 0 && to == sceKernelGetDirectMemorySize() && type == 12);
    assert(align >= 0x4000 && size && size % align == 0);
    const auto rc = Sony::state.Call("allocate-direct");
    ++Sony::state.direct_count;
    if (rc || Sony::state.direct_count == Sony::state.fail_direct_index) return Sony::Error;
    *start = Sony::state.next; Sony::state.next += size;
    Sony::state.direct[*start] = {nullptr, size, align};
    return 0;
}
int sceKernelMapDirectMemory(void** address, size_t size, int prot, int flags, int64_t start, size_t alignment) {
    assert(prot == 0x33 && flags == 0);
    auto& allocation = Sony::state.direct.at(start);
    assert(size == allocation.bytes && alignment == allocation.alignment);
    const auto rc = Sony::state.Call("map-direct");
    if (rc) return rc;
    *address = allocation.address = std::aligned_alloc(alignment, size);
    assert(*address); return 0;
}
int sceKernelReleaseDirectMemory(int64_t start, size_t size) {
    Sony::state.Call("release-direct");
    auto it = Sony::state.direct.find(start);
    assert(it != Sony::state.direct.end() && it->second.bytes == size && !it->second.address);
    Sony::state.direct.erase(it); return 0;
}
int sceKernelMunmap(void* address, size_t size) {
    for (auto& [start, allocation] : Sony::state.direct) {
        if (allocation.address != address) continue;
        assert(size == allocation.bytes); std::free(address); allocation.address = nullptr; return 0;
    }
    assert(Sony::state.flexible.erase(address) == 1);
    std::free(address); return 0;
}
int sceKernelMapNamedFlexibleMemory(void** address, size_t size, int prot, int flags, const char*) {
    assert(prot == 3 && flags == 0 && size % 0x4000 == 0);
    const auto rc = Sony::state.Call("cpu-memory");
    if (rc) return rc;
    *address = std::aligned_alloc(0x4000, size); assert(*address);
    Sony::state.flexible.insert(*address); return 0;
}
int sceKernelReleaseFlexibleMemory(void* address, size_t) {
    Sony::state.Call("release-flexible"); assert(Sony::state.flexible.contains(address)); return 0;
}
int sceKernelAvailableFlexibleMemorySize(size_t* available) { *available = 100 * 1024 * 1024; return 0; }
int32_t MockVideodec2QueryComputeMemoryInfo(SceVideodec2ComputeMemoryInfo* memory) {
    assert(memory->size == sizeof(*memory)); memory->cpu_gpu_size = 1;
    return Sony::state.Call("compute-memory-query");
}
int32_t MockVideodec2AllocateComputeQueue(const SceVideodec2ComputeConfigInfo* config,
                                       const SceVideodec2ComputeMemoryInfo* memory, void** queue) {
    assert(config->size == sizeof(*config) && config->pipe_id == 0 && config->queue_id == 0);
    assert(memory->cpu_gpu && memory->cpu_gpu_size == 0x4000);
    const auto rc = Sony::state.Call("compute-queue");
    if (!rc) { *queue = reinterpret_cast<void*>(1); ++Sony::state.queues; }
    return rc;
}
int32_t MockVideodec2ReleaseComputeQueue(void* queue) {
    assert(queue); Sony::state.Call("release-queue"); ++Sony::state.releases; return 0;
}
int32_t MockVideodec2QueryDecoderMemoryInfo(const SceVideodec2DecoderConfigInfo* config,
                                         SceVideodec2DecoderMemoryInfo* memory) {
    assert(config->size == sizeof(*config) && memory->size == sizeof(*memory));
    assert(config->resource_type == 1 && config->max_dpb_frames == 4 && config->pipeline_depth == 1);
    assert(config->cpu_priority == 700 && config->cpu_affinity == 0x3f && config->optimize_progressive == 1);
    assert(config->max_width == 64 && config->max_height == 32);
    Sony::state.codec = config->codec_type;
    assert((config->codec_type == 1 && config->profile == 100 && config->max_level == 51) ||
           (config->codec_type == 2382845 && config->profile == 0 && config->max_level == 41));
    memory->cpu_size = 123; memory->gpu_size = 234; memory->cpu_gpu_size = 345;
    memory->max_frame_size = 4096; memory->frame_alignment = 0x8000; // Must honour >16K.
    return Sony::state.Call("decoder-memory-query");
}
int32_t MockVideodec2CreateDecoder(const SceVideodec2DecoderConfigInfo*,
                                 const SceVideodec2DecoderMemoryInfo* memory, void** decoder) {
    ++Sony::state.creates;
    assert(memory->cpu && memory->gpu && memory->cpu_gpu);
    assert(memory->gpu_size == 0x4000 && memory->cpu_gpu_size == 0x4000);
    const auto rc = Sony::state.Call("create");
    if (!rc) *decoder = reinterpret_cast<void*>(2);
    return rc;
}
int32_t MockVideodec2DeleteDecoder(void* decoder) {
    assert(decoder); Sony::state.Call("delete"); ++Sony::state.deletes; return 0;
}
int32_t MockVideodec2Reset(void* decoder) { assert(decoder); return Sony::state.Call("reset"); }
int32_t MockVideodec2Decode(void* decoder, SceVideodec2InputData* input,
                          SceVideodec2FrameBuffer* fb, SceVideodec2OutputInfo* output) {
    assert(decoder && input->size == sizeof(*input) && fb->size == sizeof(*fb) && output->size == sizeof(*output));
    assert(input->dts == UINT64_MAX && input->attached == 0 && input->au_size);
    assert(reinterpret_cast<uintptr_t>(fb->buffer) % 0x8000 == 0 && fb->buffer_size == 0x8000);
    ++Sony::state.decodes;
    const auto* begin = static_cast<const u8*>(input->au);
    Sony::state.last_au.assign(begin, begin + input->au_size);
    const auto rc = Sony::state.Call("decode");
    if (rc) return rc;
    Sony::Fill(fb, output);
    if (Sony::state.no_picture || Sony::state.buffered) output->valid = 0;
    Sony::state.pending = Sony::state.buffered && !Sony::state.no_picture;
    if (Sony::state.codec == 2382845) {
        auto header = Eden::VideoDecode::ParseVp9(Sony::state.last_au);
        if (header && !header->shown) { output->valid = 0; fb->accepted = 0; }
    }
    return 0;
}
int32_t MockVideodec2Flush(void* decoder, SceVideodec2FrameBuffer* fb, SceVideodec2OutputInfo* output) {
    assert(decoder && fb->size == sizeof(*fb) && output->size == sizeof(*output));
    const auto rc = Sony::state.Call("flush");
    if (rc) return rc;
    if (Sony::state.pending) { Sony::Fill(fb, output); Sony::state.pending = false; }
    return 0;
}
int32_t MockVideodec2MapDirectMemory(void*, const SceVideodec2DirectMemory*) { return Sony::Error; }
// The firmware module's functions, as the packaged imports reach them.
int32_t sceVideodec2QueryComputeMemoryInfo(SceVideodec2ComputeMemoryInfo* memory) {
    return MockVideodec2QueryComputeMemoryInfo(memory);
}
int32_t sceVideodec2AllocateComputeQueue(const SceVideodec2ComputeConfigInfo* config,
                                         const SceVideodec2ComputeMemoryInfo* memory, void** queue) {
    return MockVideodec2AllocateComputeQueue(config, memory, queue);
}
int32_t sceVideodec2ReleaseComputeQueue(void* queue) { return MockVideodec2ReleaseComputeQueue(queue); }
int32_t sceVideodec2QueryDecoderMemoryInfo(const SceVideodec2DecoderConfigInfo* config,
                                           SceVideodec2DecoderMemoryInfo* memory) {
    return MockVideodec2QueryDecoderMemoryInfo(config, memory);
}
int32_t sceVideodec2CreateDecoder(const SceVideodec2DecoderConfigInfo* config,
                                  const SceVideodec2DecoderMemoryInfo* memory, void** decoder) {
    return MockVideodec2CreateDecoder(config, memory, decoder);
}
int32_t sceVideodec2DeleteDecoder(void* decoder) { return MockVideodec2DeleteDecoder(decoder); }
int32_t sceVideodec2MapDirectMemory(void* decoder, const SceVideodec2DirectMemory* memory) {
    return MockVideodec2MapDirectMemory(decoder, memory);
}
int32_t sceVideodec2Reset(void* decoder) { return MockVideodec2Reset(decoder); }
int32_t sceVideodec2Decode(void* decoder, SceVideodec2InputData* input, SceVideodec2FrameBuffer* fb,
                           SceVideodec2OutputInfo* output) {
    return MockVideodec2Decode(decoder, input, fb, output);
}
int32_t sceVideodec2Flush(void* decoder, SceVideodec2FrameBuffer* fb, SceVideodec2OutputInfo* output) {
    return MockVideodec2Flush(decoder, fb, output);
}
}

struct CaptureLog {
    FILE* file = std::tmpfile();
    int saved{};
    CaptureLog() {
        assert(file); std::fflush(stderr); saved = dup(fileno(stderr)); assert(saved >= 0);
        assert(dup2(fileno(file), fileno(stderr)) >= 0);
    }
    std::string Read() {
        std::fflush(stderr); assert(std::fseek(file, 0, SEEK_SET) == 0);
        std::string result; std::array<char, 4096> bytes;
        while (const auto count = std::fread(bytes.data(), 1, bytes.size(), file)) result.append(bytes.data(), count);
        return result;
    }
    ~CaptureLog() { std::fflush(stderr); assert(dup2(saved, fileno(stderr)) >= 0); close(saved); std::fclose(file); }
};
struct BitWriter {
    std::vector<u8> bytes;
    unsigned pos{};
    void U(u32 value, unsigned count) {
        while (count--) {
            if (pos % 8 == 0) bytes.push_back(0);
            bytes.back() |= ((value >> count) & 1) << (7 - pos % 8); ++pos;
        }
    }
    void UE(u32 value) {
        unsigned count = 0; for (auto v = value + 1; v >>= 1;) ++count;
        U(0, count); U(value + 1, count + 1);
    }
};
std::vector<u8> Sps(bool crop = false, unsigned reorder = 0, bool vui = true,
                    bool restriction = true, unsigned buffering = 4, bool hrd = false, unsigned profile = 100) {
    BitWriter w;
    w.U(profile, 8); w.U(0, 8); w.U(31, 8); w.UE(0);
    if (profile == 100) { w.UE(1); w.UE(0); w.UE(0); w.U(0, 1); w.U(0, 1); }
    w.UE(0); w.UE(0); w.UE(0); w.UE(1); w.U(0, 1);
    w.UE(3); w.UE(1); w.U(1, 1); w.U(1, 1); w.U(crop, 1);
    if (crop) { w.UE(0); w.UE(0); w.UE(0); w.UE(1); }
    w.U(vui, 1);
    if (vui) {
        w.U(0, 1); w.U(0, 1); w.U(1, 1); w.U(5, 3); w.U(1, 1);
        w.U(1, 1); w.U(1, 8); w.U(1, 8); w.U(1, 8);
        w.U(0, 1); // chroma_loc_info_present_flag
        w.U(hrd, 1); // timing_info_present_flag
        if (hrd) { w.U(1, 32); w.U(60, 32); w.U(1, 1); }
        w.U(hrd, 1); // nal_hrd_parameters_present_flag
        if (hrd) { w.UE(0); w.U(0, 8); w.UE(0); w.UE(0); w.U(0, 1); w.U(0, 20); }
        w.U(0, 1); // vcl_hrd_parameters_present_flag
        if (hrd) w.U(1, 1); // low_delay_hrd_flag
        w.U(0, 1); w.U(restriction, 1); // pic_struct_present, bitstream_restriction
        if (restriction) {
            w.U(1, 1); w.UE(2); w.UE(1); w.UE(16); w.UE(16);
            w.UE(reorder); w.UE(buffering);
        }
    }
    w.U(1, 1); // rbsp_stop_one_bit
    std::vector<u8> nal{0x67}; unsigned zeros = 0;
    for (auto byte : w.bytes) {
        if (zeros >= 2 && byte <= 3) { nal.push_back(3); zeros = 0; }
        nal.push_back(byte); zeros = byte == 0 ? zeros + 1 : 0;
    }
    return nal;
}
std::vector<u8> ParameterData(bool crop = false) {
    std::vector<u8> result{0, 0, 0, 1}; const auto sps = Sps(crop);
    result.insert(result.end(), sps.begin(), sps.end());
    result.insert(result.end(), {0, 0, 1, 0x68, 0xce, 0x3c, 0x80});
    return result;
}
std::vector<u8> AccessUnit(bool crop = false) {
    std::vector<u8> bytes{0, 0, 0, 1}; auto sps = Sps(crop);
    bytes.insert(bytes.end(), sps.begin(), sps.end());
    bytes.insert(bytes.end(), {0, 0, 1, 0x68, 0xce, 0x3c, 0x80, 0, 0, 0, 1, 0x65, 0xb8});
    return bytes;
}
std::vector<u8> Vp9Frame(bool key = true, unsigned space = 2, bool full = true,
                         bool shown = true, bool intra = false) {
    BitWriter w;
    w.U(2, 2); w.U(0, 2); w.U(0, 1); w.U(!key, 1); w.U(shown, 1); w.U(1, 1);
    if (!key && !shown) w.U(intra, 1);
    if (key || intra) {
        w.U(0x498342, 24);
        if (key) { w.U(space, 3); w.U(full, 1); }
    }
    return w.bytes;
}
std::vector<u8> ParameterNal(bool sps, u32 id, u32 parent = 0) {
    BitWriter w;
    if (sps) { w.U(100, 8); w.U(0, 8); w.U(40, 8); }
    w.UE(id); if (!sps) w.UE(parent); w.U(1, 1);
    std::vector<u8> result{0, 0, 0, 1, u8(sps ? 0x67 : 0x68)};
    unsigned zeros = 0;
    for (auto byte : w.bytes) {
        if (zeros >= 2 && byte <= 3) { result.push_back(3); zeros = 0; }
        result.push_back(byte); zeros = byte == 0 ? zeros + 1 : 0;
    }
    return result;
}
void CheckPacketHelpers() {
    using namespace Eden::VideoDecode;
    H264ParameterSets sets;
    for (u32 id = 0; id < 32; ++id) sets.Observe(ParameterNal(true, id));
    for (u32 id = 0; id < 256; ++id) sets.Observe(ParameterNal(false, id, id % 32));
    const auto saved = sets.Restore({});
    assert(AnnexBNals(saved).size() == 32 + 256);
    // Out-of-range IDs, truncated/overflowing Exp-Golomb codes and invalid EPB never evict IDs.
    sets.Observe(ParameterNal(true, 32)); sets.Observe(ParameterNal(false, 256));
    sets.Observe(ParameterNal(false, 0, 32));
    for (const std::vector<u8> bytes : {
        std::vector<u8>{0,0,1,0x67,100,0,40},
        std::vector<u8>{0,0,1,0x68,0,0,3,0,0,3,0,0,3,0,0,0x80},
        std::vector<u8>{0,0,1,0x68,0,0,3,4}}) sets.Observe(bytes);
    assert(sets.Restore({}) == saved);
    assert(sets.sps.size() == 32 && sets.pps.size() == 256);
    H264ParameterSets escaped;
    escaped.Observe(std::array<u8, 12>{0,0,1,0x67,100,0,40,0x80,0,0,3,1});
    assert(escaped.profile == 100 && !escaped.sps[0].empty()); // Valid EPB preserves the parameter-set ID.
    const std::vector<u8> framed{0,0,0,0,1,0x67,100,0,40,0x80,0,0,1,0x65,0xb8,0,0};
    assert(AnnexBNals(framed).size() == 2 && IsIdr(framed));
    H264ParameterSets framed_sets; framed_sets.Observe(framed);
    assert(!framed_sets.sps[0].empty());
    for (const std::vector<u8> bytes : {
        std::vector<u8>{}, std::vector<u8>{0}, std::vector<u8>{0,0,1},
        std::vector<u8>{0,0,0,1,0x65}, // Header only.
        std::vector<u8>{0,0,1,0x65,0xb8,0,0,1}, // Truncated final NAL invalidates whole packet.
        std::vector<u8>{0,0,1,0,0,1,0x65,0xb8}, // Empty NAL.
        std::vector<u8>{9,0,0,1,0x65,0xb8}, // Nonzero leading garbage.
        std::vector<u8>{0,0,1,0xe5,0xb8}}) {
        assert(AnnexBNals(bytes).empty() && !IsIdr(bytes));
        H264ParameterSets rejected; rejected.Observe(bytes); assert(rejected.Restore({}).empty());
        Sony::Setup(); CaptureLog log;
        auto backend = Eden::CreatePs5VideoDecoder(); assert(backend->Open(VideoCodec::H264, high, ParameterData()));
        std::shared_ptr<Frame> frame; assert(!backend->Decode(bytes, 1, frame));
        assert(Sony::state.decodes == 0); backend->Close(); Sony::Clean();
        Setup();
        HardwareVideoDecoderSession session;
        assert(Submit(session, idr) == Route::Hardware);
        fail_decode = true; assert(Submit(session, inter) == Route::Skipped);
        fail_decode = false;
        assert(Submit(session, bytes) == Route::Skipped && !counts.software);
    }
    Setup();
    { HardwareVideoDecoderSession session;
      session.ConfigureH264(ParameterData());
      auto unknown = high; unknown.profile = -1;
      assert(Submit(session, idr, VideoCodec::H264, unknown) == Route::Hardware);
      assert(Eden::VideoDecode::AnnexBNals(last_hardware_extradata).size() == 2); }
    // IDR refers to older PPS 0 after SPS/PPS 1 were introduced; both ID spaces survive.
    Setup();
    { HardwareVideoDecoderSession session;
      auto headers = ParameterNal(true, 0); const auto pps0 = ParameterNal(false, 0);
      const auto sps1 = ParameterNal(true, 1), pps1 = ParameterNal(false, 1, 1);
      headers.insert(headers.end(), pps0.begin(), pps0.end());
      headers.insert(headers.end(), sps1.begin(), sps1.end());
      headers.insert(headers.end(), pps1.begin(), pps1.end());
      headers.insert(headers.end(), idr.begin(), idr.end());
      assert(Submit(session, headers) == Route::Hardware);
      assert(AnnexBNals(last_hardware_extradata).size() == 4);
      fail_decode = true; assert(Submit(session, inter) == Route::Skipped);
      fail_decode = false; assert(Submit(session, idr) == Route::Software);
      auto expected = ParameterNal(true, 0);
      for (const auto& nal : {sps1, pps0, pps1}) expected.insert(expected.end(), nal.begin(), nal.end());
      expected.insert(expected.end(), idr.begin(), idr.end());
      assert(last_software_packet == expected); }
    for (auto space : {0U, 1U, 2U, 3U, 4U, 5U}) {
        const auto h = ParseVp9(Vp9Frame(true, space));
        constexpr unsigned expected[]{2, 5, 1, 6, 7, 9};
        assert(h && h->full_range && h->matrix == expected[space] && h->color_config);
    }
    assert(!ParseVp9(Vp9Frame(true, 6)) && !ParseVp9(Vp9Frame(true, 7)));
    assert(!ParseVp9(std::array<u8, 1>{0x82})); // Truncated keyframe sync/color config.
    auto intra = ParseVp9(Vp9Frame(false, 0, true, false, true));
    assert(intra && intra->color_config && intra->matrix == 5 && !intra->full_range);
}
std::vector<u8> WithSps(std::span<const u8> sps) {
    std::vector<u8> result{0, 0, 0, 1}; result.insert(result.end(), sps.begin(), sps.end());
    result.insert(result.end(), {0, 0, 1, 0x68, 0xce, 0x3c, 0x80});
    result.insert(result.end(), idr.begin(), idr.end());
    return result;
}
void CheckSpsAdmission() {
    using namespace Eden::VideoDecode;
    auto malformed = Sps(); malformed.pop_back();
    assert(!H264Sps(malformed));
    assert(H264Sps(Sps())->no_reordering);
    assert(H264Sps(Sps(false, 0, true, true, 4, true))->no_reordering); // Timing + bounded HRD.
    assert(!H264Sps(Sps(false, 1))->no_reordering);
    assert(!H264Sps(Sps(false, 0, false))->no_reordering);
    assert(!H264Sps(Sps(false, 0, true, false))->no_reordering);
    assert(!H264Sps(Sps(false, 0, true, true, 0))); // Buffering < max_num_ref_frames.
    assert(!H264Sps(Sps(false, 0, true, true, 5))); // Beyond the configured four-frame DPB.
    const auto baseline = Sps(false, 0, false, true, 4, false, 66);
    assert(H264Sps(baseline) && !H264Sps(baseline)->no_reordering);
    unsigned index = 0;
    for (const auto& sps : {Sps(), Sps(false, 1), Sps(false, 0, false), malformed,
                            Sps(false, 0, true, false), Sps(false, 0, true, true, 0), baseline}) {
        Sony::Setup(); CaptureLog log; Eden::RegisterPs5VideoDecoder();
        HardwareVideoDecoderSession session; std::shared_ptr<Frame> frame;
        const auto route = session.Decode(VideoCodec::H264, WithSps(sps), {}, high, 51, {}, frame);
        if (index++ == 0) {
            assert(route == Route::Hardware && frame && frame->GetFrame()->pts == 51);
            assert(Sony::state.decodes == 1);
        } else {
            assert(route == Route::Software && !frame && session.GetState() == State::Fallback);
            assert(!Sony::state.creates && !Sony::state.decodes);
            const auto text = log.Read();
            assert(text.find("EDEN_HW_VIDEODEC fallback reason=h264-") != std::string::npos);
            assert(text.find("fallback reason=") == text.rfind("fallback reason="));
        }
        session.Finish(); Sony::Clean();
    }
    Sony::Setup();
    { CaptureLog log; Eden::RegisterPs5VideoDecoder();
      HardwareVideoDecoderSession session; std::shared_ptr<Frame> frame;
      assert(session.Decode(VideoCodec::H264, AccessUnit(), {}, high, 61, {}, frame) == Route::Hardware);
      const auto unsafe = Sps(false, 1);
      std::vector<u8> change{0,0,0,1}; change.insert(change.end(), unsafe.begin(), unsafe.end());
      change.insert(change.end(), inter.begin(), inter.end());
      assert(session.Decode(VideoCodec::H264, change, {}, high, 62, {}, frame) == Route::Skipped);
      assert(!frame && session.GetState() == State::Recovery && Sony::state.decodes == 1);
      assert(session.Decode(VideoCodec::H264, idr, {}, high, 63, {}, frame) == Route::Software);
      const auto restored = session.TakeRestartPacket();
      const auto nals = AnnexBNals(restored); assert(!nals.empty());
      assert(std::vector<u8>(nals[0].begin(), nals[0].end()) == unsafe);
      assert(Sony::state.decodes == 1 && Sony::state.deletes == 1);
      const auto text = log.Read();
      assert(text.find("EDEN_HW_VIDEODEC fallback reason=h264-reordering") != std::string::npos);
      assert(text.find("fallback reason=") == text.rfind("fallback reason="));
      Sony::Clean(); }
    Sony::Setup();
    { CaptureLog log; auto backend = Eden::CreatePs5VideoDecoder();
      assert(!backend->Open(VideoCodec::H264, high)); // Missing SPS cannot establish admission.
      assert(!Sony::state.creates && !Sony::state.decodes); Sony::Clean(); }
}
void CheckVideodecApi() {
    using namespace Eden::VideoDecode;
    CheckPacketHelpers();
    CheckSpsAdmission();
    const auto au = AccessUnit();
    assert(AnnexBNals(au).size() == 3 && IsIdr(au));
    assert(AnnexBNals(std::array<u8, 3>{0, 0, 1}).empty());
    assert(!IsIdr(std::array<u8, 5>{0, 0, 1, 0x41, 0x65}));
    auto parsed = H264Sps(Sps(true));
    assert(parsed && parsed->width == 64 && parsed->height == 30 && parsed->coded_height == 32);
    assert(parsed->full_range && parsed->matrix == 1);
    assert(*IsBSlice(std::array<u8, 2>{0x41, 0xa0}));
    assert(!*IsBSlice(std::array<u8, 2>{0x65, 0xb8}));
    assert(!H264Sps(std::array<u8, 1>{0x67}));
    const auto sps = Sps();
    std::vector<u8> avcc{1, 100, 0, 31, 0xff, 0xe1, 0, static_cast<u8>(sps.size())};
    avcc.insert(avcc.end(), sps.begin(), sps.end()); avcc.insert(avcc.end(), {1, 0, 2, 0x68, 0x80});
    auto extra = H264Extradata(avcc); assert(extra && AnnexBNals(*extra).size() == 2);
    avcc.pop_back(); assert(!H264Extradata(avcc));
    assert(!Align(UINT64_MAX)); assert(Align(1) == 0x4000);
    const auto hidden = Vp9Frame(false, 0, false, false);
    const auto key = Vp9Frame();
    auto super = hidden; super.insert(super.end(), key.begin(), key.end());
    super.insert(super.end(), {0xc1, static_cast<u8>(hidden.size()), static_cast<u8>(key.size()), 0xc1});
    auto split = SplitVp9(super); assert(split && split->count == 2);
    assert(split->frames[0].size() == hidden.size() && split->frames[1].size() == key.size());
    assert(SplitVp9(std::array<u8, 1>{0x82})->count == 1);
    assert(!SplitVp9({}));
    assert(!SplitVp9(std::array<u8, 1>{0xc1})); // Truncated index.
    assert(!SplitVp9(std::array<u8, 4>{0x82, 0xc0, 2, 0xc0})); // Size beyond payload.
    assert(!SplitVp9(std::array<u8, 4>{0x82, 0xc1, 0, 0xc1})); // Marker/count mismatch.
    assert(!ParseVp9({}));
    assert(!ParseVp9(std::array<u8, 1>{0xff}));
    assert(!ParseVp9(hidden)->shown);
    assert(ParseVp9(std::array<u8, 1>{0x88})->existing && ParseVp9(std::array<u8, 1>{0x88})->shown);
    auto supported = Eden::CreatePs5VideoDecoder();
    for (int profile : {66, 77, 100}) assert(supported->Supports(VideoCodec::H264, {3840, 2160, profile}));
    assert(supported->Supports(VideoCodec::VP9, {3840, 2160, 0}));
    assert(!supported->Supports(VideoCodec::VP9, {3840, 2160, 2})); // P010 excluded explicitly.
    assert(!supported->Supports(VideoCodec::H264, {3840, 2160, 110}));
    assert(!supported->Supports(VideoCodec::H264, {4096, 2160, 100}));
    assert(!supported->Supports(VideoCodec::VP8, high));
    Sony::Setup(); setenv("EDEN_PS5_HW_VIDEODEC", "0", 1); Eden::RegisterPs5VideoDecoder();
    { HardwareVideoDecoderSession session; std::shared_ptr<Frame> frame;
      assert(session.Decode(VideoCodec::H264, au, {}, high, 1, {}, frame) == HardwareVideoDecoderSession::Route::Software);
      assert(Sony::state.calls.empty()); }
    unsetenv("EDEN_PS5_HW_VIDEODEC");
    // Real backend + real shared selection state, only Sony and FFmpeg allocations shimmed.
    for (const auto& [stage, reason] : std::array<std::pair<const char*, const char*>, 8>{{
        {"compute-memory-query", "compute-memory-query"},
        {"allocate-direct", "compute-memory"}, {"map-direct", "compute-memory"},
        {"compute-queue", "compute-queue"}, {"decoder-memory-query", "decoder-memory-query"},
        {"cpu-memory", "cpu-memory"}, {"create", "create"}, {"reset", "reset"}}}) {
        Sony::Setup(); Sony::state.failure = stage; CaptureLog log;
        Eden::RegisterPs5VideoDecoder();
        { HardwareVideoDecoderSession session; std::shared_ptr<Frame> frame;
          assert(session.Decode(VideoCodec::H264, au, {}, high, 1, {}, frame) == HardwareVideoDecoderSession::Route::Software);
          assert(!frame && session.HasFallenBack());
          const auto calls = Sony::state.calls.size();
          Sony::state.failure.clear();
          assert(session.Decode(VideoCodec::H264, au, {}, high, 2, {}, frame) == HardwareVideoDecoderSession::Route::Software);
          assert(Sony::state.calls.size() == calls); }
        Sony::Clean();
        const auto text = log.Read();
        assert(text.find(std::string("EDEN_HW_VIDEODEC fallback reason=") + reason + " rc=0x811d0200") != std::string::npos);
        assert(text.find("fallback reason=") == text.rfind("fallback reason="));
    }
    Sony::Setup();
    { CaptureLog log; Sony::state.failure = "decode"; Eden::RegisterPs5VideoDecoder();
      HardwareVideoDecoderSession session; std::shared_ptr<Frame> frame;
      assert(session.Decode(VideoCodec::H264, au, {}, high, 1, {}, frame) == HardwareVideoDecoderSession::Route::Software);
      assert(Sony::state.creates == 1 && Sony::state.decodes == 1 && Sony::state.deletes == 1);
      Sony::Clean();
      const auto text = log.Read();
      assert(text.find("EDEN_HW_VIDEODEC create rc=0x00000000") != std::string::npos);
      assert(text.find("EDEN_HW_VIDEODEC first-decode rc=0x811d0200") != std::string::npos);
      assert(text.find("EDEN_HW_VIDEODEC fallback reason=decode rc=0x811d0200") != std::string::npos); }
    Sony::Setup();
    { CaptureLog log; auto backend = Eden::CreatePs5VideoDecoder(); avcc.push_back(0x80);
      assert(backend->Open(VideoCodec::H264, high, avcc));
      const std::array<u8, 5> slice{0, 0, 1, 0x65, 0xb8}; std::shared_ptr<Frame> frame;
      assert(backend->Decode(slice, 1, frame) && frame);
      assert(AnnexBNals(Sony::state.last_au).size() == 3); // CSD injected before first IDR.
      backend->Close(); Sony::Clean(); }
    for (unsigned allocation = 2; allocation <= 5; ++allocation) {
        Sony::Setup(); Sony::state.fail_direct_index = allocation; CaptureLog log;
        auto backend = Eden::CreatePs5VideoDecoder(); assert(!backend->Open(VideoCodec::H264, high, ParameterData()));
        backend->Close(); Sony::Clean();
        assert(Sony::state.queues == Sony::state.releases);
    }
    Sony::Setup();
    { CaptureLog log; Eden::RegisterPs5VideoDecoder(); HardwareVideoDecoderSession session;
      std::shared_ptr<Frame> frame;
      assert(session.Decode(VideoCodec::H264, au, {}, high, 5, {}, frame) == HardwareVideoDecoderSession::Route::Hardware);
      assert(frame && frame->GetFrame()->pts == 5 && frame->GetFrame()->colorspace == 1);
      assert(frame->GetFrame()->color_range == AVCOL_RANGE_JPEG && frame->GetPlane(0)[0] == 0x11);
      auto retained = frame;
      const std::array<u8, 5> p{0, 0, 1, 0x41, 0xc0};
      assert(session.Decode(VideoCodec::H264, p, {}, high, 6, {}, frame) == HardwareVideoDecoderSession::Route::Hardware);
      assert(frame->GetPlane(0)[0] == 0x44 && retained->GetPlane(0)[0] == 0x11);
      Sony::state.failure = "decode";
      assert(session.Decode(VideoCodec::H264, p, {}, high, 7, {}, frame) == HardwareVideoDecoderSession::Route::Skipped);
      Sony::state.failure.clear();
      assert(session.Decode(VideoCodec::H264, p, {}, high, 8, {}, frame) == HardwareVideoDecoderSession::Route::Skipped);
      assert(session.Decode(VideoCodec::H264, au, {}, high, 9, {}, frame) == HardwareVideoDecoderSession::Route::Software);
      assert(Sony::state.decodes == 3 && Sony::state.creates == 1 && Sony::state.deletes == 1);
      Sony::Clean(); assert(retained->GetPlane(0)[0] == 0x11);
      const auto text = log.Read();
      for (const auto* line : {"compute-queue rc=0x00000000", "create rc=0x00000000",
                              "first-decode rc=0x00000000", "fallback reason=decode rc=0x811d0200"})
          assert(text.find(std::string("EDEN_HW_VIDEODEC ") + line) != std::string::npos);
      assert(text.find("first-decode") == text.rfind("first-decode"));
      assert(text.find("fallback reason=") == text.rfind("fallback reason="));
      const auto& calls = Sony::state.calls;
      const auto deleted = std::find(calls.begin(), calls.end(), "delete");
      const auto cpu_freed = std::find(calls.begin(), calls.end(), "release-flexible");
      const auto queue_freed = std::find(calls.begin(), calls.end(), "release-queue");
      assert(deleted < cpu_freed && cpu_freed < queue_freed); }
    for (int mode = 0; mode < 5; ++mode) {
        Sony::Setup(); CaptureLog log;
        auto backend = Eden::CreatePs5VideoDecoder(); assert(backend->Open(VideoCodec::H264, high, ParameterData()));
        Sony::state.no_picture = mode == 0; Sony::state.bad_pitch = mode == 1;
        Sony::state.bad_bounds = mode == 2; Sony::state.bad_size = mode == 3;
        Sony::state.output_error = mode == 4;
        std::shared_ptr<Frame> frame; assert(!backend->Decode(au, 1, frame));
        assert(!frame); backend->Close(); Sony::Clean();
        const auto text = log.Read();
        const std::array<const char*, 5> reasons{"no-picture", "pitch-size", "frame-bounds", "decode-output", "decode-output"};
        assert(text.find(std::string("fallback reason=") + reasons[mode]) != std::string::npos);
    }
    Sony::Setup();
    { CaptureLog log; auto backend = Eden::CreatePs5VideoDecoder();
      assert(backend->Open(VideoCodec::H264, {64, 30, 100}, ParameterData(true)));
      Sony::state.buffered = true;
      std::shared_ptr<Frame> frame; assert(backend->Decode(AccessUnit(true), 11, frame));
      assert(frame->GetWidth() == 64 && frame->GetHeight() == 30 && frame->GetPlane(1)[0] == 0x22);
      backend->Close(); Sony::Clean(); assert(frame->GetPlane(1)[1] == 0x33); }
    Sony::Setup();
    { CaptureLog log; auto backend = Eden::CreatePs5VideoDecoder(); assert(backend->Open(VideoCodec::VP9, vp9));
      std::shared_ptr<Frame> frame;
      assert(backend->Decode(super, 12, frame) && frame && Sony::state.decodes == 2);
      assert(frame->GetFrame()->colorspace == 1 && frame->GetFrame()->color_range == AVCOL_RANGE_JPEG);
      assert(backend->Decode(Vp9Frame(false), 13, frame) && frame);
      assert(frame->GetFrame()->colorspace == 1 && frame->GetFrame()->color_range == AVCOL_RANGE_JPEG);
      frame.reset();
      assert(backend->Decode(hidden, 13, frame) && !frame); // Hidden decoded.
      assert(Sony::state.decodes == 4);
      assert(backend->Decode(std::array<u8, 1>{0x88}, 14, frame) && frame); // Show existing.
      assert(frame->GetFrame()->colorspace == 1 && frame->GetFrame()->color_range == AVCOL_RANGE_JPEG);
      assert(backend->Decode(Vp9Frame(true, 0, false), 15, frame) && frame);
      assert(frame->GetFrame()->colorspace == 2 && frame->GetFrame()->color_range == AVCOL_RANGE_MPEG);
      assert(backend->Decode(Vp9Frame(false, 0, true, false, true), 16, frame) && !frame);
      assert(backend->Decode(Vp9Frame(false), 17, frame) && frame);
      assert(frame->GetFrame()->colorspace == 5 && frame->GetFrame()->color_range == AVCOL_RANGE_MPEG);
      backend->Close(); Sony::Clean(); }
    // Malformed VP9 index and B-slices fail before reaching the native decode ioctl.
    for (bool vp : {false, true}) {
        Sony::Setup(); CaptureLog log;
        auto backend = Eden::CreatePs5VideoDecoder();
        assert(backend->Open(vp ? VideoCodec::VP9 : VideoCodec::H264, vp ? vp9 : high, vp ? std::vector<u8>{} : ParameterData()));
        std::shared_ptr<Frame> frame;
        if (vp) assert(!backend->Decode(std::array<u8, 1>{0xc1}, 1, frame));
        else assert(!backend->Decode(std::array<u8, 5>{0, 0, 1, 0x41, 0xa0}, 1, frame));
        assert(Sony::state.decodes == 0); Sony::Clean();
    }
    assert(Sony::loader.sysmodule_loads == 1);
    RegisterHardwareVideoDecoder(nullptr);
}

size_t CountLog(const std::string& text, const std::string& needle) {
    size_t count = 0, pos = 0;
    while ((pos = text.find(needle, pos)) != std::string::npos) { ++count; pos += needle.size(); }
    return count;
}
void CheckLoader(const std::string& mode) {
    Setup(); Sony::Setup();
    const bool module_failure = mode == "--loader-module-fail";
    assert(module_failure || mode == "--loader-success" || mode == "--loader-concurrent");
    Sony::loader.rc = module_failure ? Sony::Error : 0;
    CaptureLog log;
    Eden::RegisterPs5VideoDecoder();
    auto candidate = Eden::CreatePs5VideoDecoder();
    assert(candidate->Supports(VideoCodec::H264, high));
    assert(Sony::loader.sysmodule_loads == 0); // Registration/Supports are lazy.
    if (mode == "--loader-concurrent") {
        std::array<std::thread, 8> threads;
        for (auto& thread : threads) thread = std::thread([] {
            auto backend = Eden::CreatePs5VideoDecoder();
            backend->Open(VideoCodec::H264, high, ParameterData());
            backend->Close();
        });
        for (auto& thread : threads) thread.join();
        assert(Sony::state.creates >= 1 && Sony::state.creates == Sony::state.deletes);
        Sony::Setup(); // Loader cache survives while decoder resource counters reset.
    }
    for (unsigned attempt = 0; attempt < 2; ++attempt) {
        HardwareVideoDecoderSession session;
        std::shared_ptr<Frame> frame;
        const auto route = session.Decode(VideoCodec::H264, AccessUnit(), {}, high, attempt + 1, {}, frame);
        if (module_failure) {
            assert(route == HardwareVideoDecoderSession::Route::Software && !frame);
            assert(session.HasFallenBack() && Sony::state.calls.empty());
            // A fixed environment must not trigger a retry: failure belongs to the process cache.
            Sony::loader.rc = 0;
        } else {
            assert(route == HardwareVideoDecoderSession::Route::Hardware && frame);
            assert(frame->GetWidth() == 64 && frame->GetHeight() == 32);
            assert(frame->GetFrame()->pts == attempt + 1);
        }
    }
    Sony::Clean();
    assert(Sony::loader.sysmodule_loads == 1);
    const auto text = log.Read();
    assert(CountLog(text, "EDEN_HW_VIDEODEC sysmodule-load ") == 1);
    if (module_failure) {
        assert(text.find("EDEN_HW_VIDEODEC sysmodule-load id=207 rc=0x811d0200") != std::string::npos);
        assert(CountLog(text, "EDEN_HW_VIDEODEC fallback reason=sysmodule-load ") == 2);
    } else {
        assert(text.find("EDEN_HW_VIDEODEC sysmodule-load id=207 rc=0x00000000") != std::string::npos);
        if (mode == "--loader-concurrent") {
            // Queue ownership may reject contenders; the shared loader must still succeed once.
            assert(CountLog(text, "EDEN_HW_VIDEODEC fallback ") ==
                   CountLog(text, "EDEN_HW_VIDEODEC fallback reason=queue-busy "));
        } else assert(CountLog(text, "EDEN_HW_VIDEODEC fallback ") == 0);
        assert(Sony::state.creates == 2 && Sony::state.decodes == 2 && Sony::state.deletes == 2);
    }
}

int main(int argc, char** argv) {
    if (argc > 1) { CheckLoader(argv[1]); return 0; }
    CheckSession();
    CheckVideodecApi();
}
'''

with tempfile.TemporaryDirectory(prefix='hw-video-fallback-') as directory:
    temp = Path(directory)
    shim = temp / 'video_core/host1x/ffmpeg.h'
    shim.parent.mkdir(parents=True)
    shim.write_text(ffmpeg)
    (temp / 'check.cpp').write_text(cpp)
    subprocess.run(['clang++-18', '-std=c++20', '-O1', '-g',
                    '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-pthread',
                    '-DPS5_NATIVE=1', '-I' + str(temp), '-I' + str(source),
                    '-I' + str(root / 'headless'),
                    str(host1x / 'hardware_video_decoder.cpp'),
                    str(root / 'headless/ps5_video_decoder.cpp'),
                    str(temp / 'check.cpp'), '-o', str(temp / 'check')], check=True)
    for mode in (None, '--loader-module-fail', '--loader-success', '--loader-concurrent'):
        subprocess.run([str(temp / 'check')] + ([mode] if mode else []), check=True,
                       env={key: value for key, value in os.environ.items()
                            if key != 'EDEN_PS5_HW_VIDEODEC'})
print('HW_VIDEO_DECODE_FALLBACK_PASS (ASan/UBSan; standalone production session/backend, recording dependencies)')
