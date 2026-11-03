// SPDX-License-Identifier: GPL-3.0-only
// Adapted from sainsaji/EVO-PLAYER-PS5 a54dcf516e9cfda4c26d78733bf5ccb8c10e7e0b (GPL-3.0)
#include "ps5_video_decoder.h"

#ifdef PS5_NATIVE
#include <algorithm>
#include <cstdio>
#include <cstring>
#include <mutex>
#include "ps5_video_helpers.h"
#include "ps5_videodec2_abi.h"
#include "video_core/host1x/ffmpeg.h"

extern "C" {
int sceKernelLoadStartModule(const char*, std::size_t, const void*, std::uint32_t, const void*, int*);
int sceKernelDlsym(int, const char*, void**);
std::int64_t sceKernelGetDirectMemorySize();
int sceKernelAllocateDirectMemory(std::int64_t, std::int64_t, std::size_t, std::size_t, int, std::int64_t*);
int sceKernelMapDirectMemory(void**, std::size_t, int, int, std::int64_t, std::size_t);
int sceKernelReleaseDirectMemory(std::int64_t, std::size_t);
int sceKernelMunmap(void*, std::size_t);
int sceKernelMapNamedFlexibleMemory(void**, std::size_t, int, int, const char*);
int sceKernelReleaseFlexibleMemory(void*, std::size_t);
int sceKernelAvailableFlexibleMemorySize(std::size_t*);
}

namespace Eden {
namespace {
using namespace VideoDecode;
using Tegra::Host1x::NvdecCommon::VideoCodec;
// EVO uses independent resident slots. Eden instead owns one queue/decoder per stream;
// refuse a concurrent owner of pipe=0/queue=0 rather than resetting another stream.
std::mutex decoder_mutex;
bool decoder_owned{};

void Note(const char* stage, int rc) {
    std::fprintf(stderr, "EDEN_HW_VIDEODEC %s rc=0x%08x\n", stage, static_cast<unsigned>(rc));
}

// The absolute system path and kernel loading mechanism are also used by the local
// moonlight-VideoDecoder.cpp reference. No POSIX dlopen/dlsym or PS4 dependency preload.
struct Videodec2Api {
    decltype(&sceVideodec2QueryComputeMemoryInfo) QueryComputeMemoryInfo{};
    decltype(&sceVideodec2AllocateComputeQueue) AllocateComputeQueue{};
    decltype(&sceVideodec2ReleaseComputeQueue) ReleaseComputeQueue{};
    decltype(&sceVideodec2QueryDecoderMemoryInfo) QueryDecoderMemoryInfo{};
    decltype(&sceVideodec2CreateDecoder) CreateDecoder{};
    decltype(&sceVideodec2DeleteDecoder) DeleteDecoder{};
    decltype(&sceVideodec2MapDirectMemory) MapDirectMemory{};
    decltype(&sceVideodec2Reset) Reset{};
    decltype(&sceVideodec2Decode) Decode{};
    decltype(&sceVideodec2Flush) Flush{};
    int module{-1};
    bool ready{};
    const char* failure{"module-load"};
    int rc{};
};

template <typename Function>
bool ResolveVideodec2(int module, const char* name, Function& function, int& rc) {
    void* address{};
    rc = sceKernelDlsym(module, name, &address);
    if (rc != 0 || !address) {
        std::fprintf(stderr, "EDEN_HW_VIDEODEC symbol-missing name=%s rc=0x%08x\n",
                     name, static_cast<unsigned>(rc));
        return false;
    }
    function = reinterpret_cast<Function>(address);
    return true;
}

const Videodec2Api& GetVideodec2Api() {
    // Function-local static initialization is thread-safe and caches failure too. Retain the
    // module until process exit: Close releases decoder resources, never these shared pointers.
    static const Videodec2Api api = [] {
        Videodec2Api result;
        constexpr const char* path = "/system/common/lib/libSceVideodec2.sprx";
        const int module = result.module = sceKernelLoadStartModule(path, 0, nullptr, 0, nullptr, nullptr);
        std::fprintf(stderr, "EDEN_HW_VIDEODEC module-load rc=0x%08x path=%s\n",
                     static_cast<unsigned>(module), path);
        if (module < 0) { result.rc = module; return result; }
        result.failure = "symbol-missing";
        if (!ResolveVideodec2(module, "sceVideodec2QueryComputeMemoryInfo", result.QueryComputeMemoryInfo, result.rc)) return result;
        if (!ResolveVideodec2(module, "sceVideodec2AllocateComputeQueue", result.AllocateComputeQueue, result.rc)) return result;
        if (!ResolveVideodec2(module, "sceVideodec2ReleaseComputeQueue", result.ReleaseComputeQueue, result.rc)) return result;
        if (!ResolveVideodec2(module, "sceVideodec2QueryDecoderMemoryInfo", result.QueryDecoderMemoryInfo, result.rc)) return result;
        if (!ResolveVideodec2(module, "sceVideodec2CreateDecoder", result.CreateDecoder, result.rc)) return result;
        if (!ResolveVideodec2(module, "sceVideodec2DeleteDecoder", result.DeleteDecoder, result.rc)) return result;
        if (!ResolveVideodec2(module, "sceVideodec2MapDirectMemory", result.MapDirectMemory, result.rc)) return result;
        if (!ResolveVideodec2(module, "sceVideodec2Reset", result.Reset, result.rc)) return result;
        if (!ResolveVideodec2(module, "sceVideodec2Decode", result.Decode, result.rc)) return result;
        if (!ResolveVideodec2(module, "sceVideodec2Flush", result.Flush, result.rc)) return result;
        result.ready = true;
        return result;
    }();
    return api;
}

struct DirectMemory {
    void* address{};
    std::int64_t physical{-1};
    std::size_t bytes{};

    int Allocate(std::uint64_t requested, std::int64_t limit, std::size_t alignment = Alignment) {
        const auto aligned = Align(requested, alignment);
        if (!aligned || *aligned > static_cast<std::uint64_t>(limit)) return -1;
        bytes = *aligned;
        std::int64_t start = -1;
        int rc = sceKernelAllocateDirectMemory(0, limit, bytes, alignment, 12, &start);
        if (rc != 0) return rc;
        if (start < 0) return -1;
        physical = start;
        // The frozen implementation uses 0x33 for ALL direct maps: CPU readback needs r/w.
        // This intentionally follows evo_vdec_native.c, rather than the older docs' 0x32.
        if (rc == 0) rc = sceKernelMapDirectMemory(&address, bytes, 0x33, 0, physical, alignment);
        return rc == 0 && !address ? -1 : rc;
    }
    void Free() {
        if (address) sceKernelMunmap(address, bytes);
        if (physical >= 0) sceKernelReleaseDirectMemory(physical, bytes);
        address = nullptr; physical = -1; bytes = 0;
    }
};

class Ps5VideoDecoder final : public FFmpeg::HardwareVideoDecoder {
public:
    ~Ps5VideoDecoder() override { Close(); }

    bool Supports(VideoCodec codec, const FFmpeg::FrameDimensions& dimensions) const override {
        if (dimensions.width <= 0 || dimensions.height <= 0 ||
            dimensions.width > 3840 || dimensions.height > 2176) return false;
        // Profile 2 is documented working, but returns P010; our consumer contract is 8-bit.
        return (codec == VideoCodec::H264 && (dimensions.profile == 66 ||
                    dimensions.profile == 77 || dimensions.profile == 100)) ||
               (codec == VideoCodec::VP9 && dimensions.profile == 0);
    }

    bool Open(VideoCodec codec, const FFmpeg::FrameDimensions& dimensions,
              std::span<const u8> extradata) override {
        if (!Supports(codec, dimensions)) return Fail("unsupported");
        api = &GetVideodec2Api();
        if (!api->ready) return Fail(api->failure, api->rc);
        {
            const std::lock_guard lock(decoder_mutex);
            if (decoder_owned) return Fail("queue-busy");
            decoder_owned = owns_queue = true;
        }
        current_codec = codec;
        display = dimensions;
        picture.width = static_cast<u32>(dimensions.width);
        picture.height = static_cast<u32>(dimensions.height);
        if (codec == VideoCodec::H264) {
            auto converted = H264Extradata(extradata);
            if (!converted) return Fail("h264-extradata");
            prefix = std::move(*converted);
            if (!ReadH264(prefix)) return false;
        }
        const auto limit = sceKernelGetDirectMemorySize();
        if (limit <= 0) return Fail("direct-memory-limit");
        SceVideodec2ComputeMemoryInfo cm{};
        cm.size = sizeof(cm);
        int rc = api->QueryComputeMemoryInfo(&cm);
        if (rc || cm.size != sizeof(cm)) return Fail("compute-memory-query", rc);
        if ((rc = compute.Allocate(cm.cpu_gpu_size, limit))) return Fail("compute-memory", rc);
        cm.cpu_gpu = compute.address; cm.cpu_gpu_size = compute.bytes;
        SceVideodec2ComputeConfigInfo cc{};
        cc.size = sizeof(cc);
        rc = api->AllocateComputeQueue(&cc, &cm, &queue);
        Note("compute-queue", rc);
        if (rc || !queue) return Fail("compute-queue", rc);

        SceVideodec2DecoderConfigInfo config{};
        config.size = sizeof(config);
        config.resource_type = 1;
        config.codec_type = codec_type = codec == VideoCodec::H264 ? 1U : 2382845U;
        config.profile = codec == VideoCodec::H264 ? 100 : 0; // EVO's AVC High slot accepts BP/MP.
        // Cover the documented padded 1088/2176 surfaces, including absent in-band SPS at Open.
        config.max_width = max_width = std::max<u32>((dimensions.width + 15) & ~15, picture.coded_width);
        config.max_height = max_height = std::max<u32>((dimensions.height + 31) & ~31, picture.coded_height);
        const bool large = max_width > 1920 || max_height > 1088;
        config.max_level = codec == VideoCodec::H264 ? (large ? 52 : 51) : (large ? 51 : 41);
        config.max_dpb_frames = 4;
        config.pipeline_depth = 1; // Verified single-decoder sequence, synchronous Eden contract.
        config.compute_queue = reinterpret_cast<std::uintptr_t>(queue);
        config.cpu_affinity = 0x3f;
        config.cpu_priority = 700;
        config.optimize_progressive = 1;
        SceVideodec2DecoderMemoryInfo memory{};
        memory.size = sizeof(memory);
        // Log BEFORE the native call too: the reference warns invalid configurations can fault.
        std::fprintf(stderr, "EDEN_HW_VIDEODEC config codec=%u profile=%u level=%u coded=%ux%u depth=1 dpb=4\n",
            codec_type, config.profile, config.max_level, max_width, max_height);
        Note("decoder-memory-query-enter", 0);
        rc = api->QueryDecoderMemoryInfo(&config, &memory);
        if (rc || memory.size != sizeof(memory)) return Fail("decoder-memory-query", rc);
        if (memory.cpu_size) {
            auto aligned = Align(memory.cpu_size);
            if (!aligned) return Fail("cpu-memory-size");
            cpu_bytes = *aligned;
            std::size_t available{};
            sceKernelAvailableFlexibleMemorySize(&available); // Advisory, as in the reference.
            rc = sceKernelMapNamedFlexibleMemory(&cpu, cpu_bytes, 0x03, 0, "EdenVideodec2");
            if (rc || !cpu) return Fail("cpu-memory", rc);
            memory.cpu = cpu;
        }
        if ((rc = gpu.Allocate(memory.gpu_size, limit))) return Fail("gpu-memory", rc);
        memory.gpu = gpu.address; memory.gpu_size = gpu.bytes;
        if (memory.cpu_gpu_size) {
            if ((rc = cpu_gpu.Allocate(memory.cpu_gpu_size, limit))) return Fail("cpu-gpu-memory", rc);
            memory.cpu_gpu = cpu_gpu.address; memory.cpu_gpu_size = cpu_gpu.bytes;
        }
        if (memory.frame_alignment && (memory.frame_alignment & (memory.frame_alignment - 1)))
            return Fail("frame-alignment");
        const auto alignment = std::max<std::size_t>(Alignment, memory.frame_alignment);
        const auto aligned_frame = Align(memory.max_frame_size, alignment);
        if (!aligned_frame || *aligned_frame > std::numeric_limits<std::size_t>::max() / Slots)
            return Fail("frame-memory-size");
        frame_bytes = *aligned_frame;
        if ((rc = input.Allocate(InputBytes * Slots, limit))) return Fail("input-memory", rc);
        if ((rc = frames.Allocate(frame_bytes * Slots, limit, alignment))) return Fail("frame-memory", rc);
        Note("create-enter", 0);
        rc = api->CreateDecoder(&config, &memory, &decoder);
        Note("create", rc);
        if (rc || !decoder) return Fail("create", rc);
        rc = api->Reset(decoder);
        Note("reset", rc);
        if (rc) return Fail("reset", rc);
        reset_done = true;
        return true;
    }

    bool Decode(std::span<const u8> packet, s64 pts, std::shared_ptr<FFmpeg::Frame>& frame) override {
        frame.reset();
        if (!decoder || failed) return false;
        if (current_codec == VideoCodec::H264) {
            if (packet.empty() || packet.size() > InputBytes - prefix.size()) return Fail("access-unit-size");
            std::vector<u8> au = std::move(prefix);
            prefix.clear();
            au.insert(au.end(), packet.begin(), packet.end());
            if (!ReadH264(au)) return false;
            if (!have_sps) return Fail("h264-sps-missing");
            return DecodeOne(au, pts, true, frame);
        }
        const auto split = SplitVp9(packet);
        if (!split) return Fail("vp9-superframe");
        unsigned shown = 0;
        for (std::size_t i = 0; i < split->count; ++i) {
            const auto header = ParseVp9(split->frames[i]);
            if (!header || header->profile != 0) return Fail("vp9-header");
            shown += header->shown;
        }
        if (shown > 1) return Fail("vp9-multiple-shown"); // One visible frame per interface call.
        for (std::size_t i = 0; i < split->count; ++i) {
            const auto header = *ParseVp9(split->frames[i]);
            if (header.color_config) {
                picture.matrix = header.matrix;
                picture.full_range = header.full_range;
            }
            if (!DecodeOne(split->frames[i], pts, header.shown, frame)) return false;
        }
        return true;
    }

    void ReportFallback(const char* reason) override { Fail(reason); }

    void Close() override {
        if (decoder) {
            if (reset_done) {
                SceVideodec2FrameBuffer fb{};
                fb.size = sizeof(fb); fb.buffer = frames.address; fb.buffer_size = frame_bytes;
                SceVideodec2OutputInfo out{};
                out.size = sizeof(out);
                const int rc = api->Flush(decoder, &fb, &out);
                if (rc) LogFailure("close-flush", rc);
            }
            api->DeleteDecoder(decoder);
            decoder = nullptr;
        }
        frames.Free(); input.Free(); cpu_gpu.Free(); gpu.Free();
        if (cpu) { sceKernelReleaseFlexibleMemory(cpu, cpu_bytes); sceKernelMunmap(cpu, cpu_bytes); cpu = nullptr; }
        if (queue) { api->ReleaseComputeQueue(queue); queue = nullptr; }
        compute.Free();
        if (owns_queue) {
            const std::lock_guard lock(decoder_mutex);
            decoder_owned = owns_queue = false;
        }
        reset_done = false;
    }

private:
    void LogFailure(const char* reason, int rc) {
        if (!failed) std::fprintf(stderr, "EDEN_HW_VIDEODEC fallback reason=%s rc=0x%08x\n",
                                  reason, static_cast<unsigned>(rc));
        failed = true;
    }
    bool Fail(const char* reason, int rc = -1) {
        LogFailure(reason, rc);
        Close();
        return false;
    }
    bool ReadH264(Bytes bytes) {
        if (bytes.empty()) return true;
        const auto nals = AnnexBNals(bytes);
        if (nals.empty()) return Fail("h264-annex-b");
        for (auto nal : nals) {
            const auto type = nal[0] & 31;
            if (type == 7) {
                const auto parsed = H264Sps(nal);
                if (!parsed || parsed->width != static_cast<u32>(display.width) ||
                    parsed->height != static_cast<u32>(display.height) ||
                    (decoder && (parsed->coded_width > max_width || parsed->coded_height > max_height)) ||
                    parsed->level > (display.width > 1920 || display.height > 1088 ? 52U : 51U))
                    return Fail("h264-sps-format");
                picture = *parsed;
                have_sps = true;
            } else if (type == 1 || type == 5) {
                const auto b_slice = IsBSlice(nal);
                // OutputInfo carries no PTS. Reject B slices rather than guess EVO's PTS window.
                if (!b_slice || *b_slice) return Fail("h264-reordering");
            } else if (type >= 2 && type <= 4) return Fail("h264-data-partition");
            else if (type == 0 || type > 12) return Fail("h264-nal-type");
        }
        return true;
    }
    bool DecodeOne(Bytes au, s64 pts, bool shown, std::shared_ptr<FFmpeg::Frame>& frame) {
        if (au.empty() || au.size() > InputBytes) return Fail("access-unit-size");
        const auto slot = next_slot++ % Slots;
        auto* au_buffer = static_cast<u8*>(input.address) + slot * InputBytes;
        auto* frame_buffer = static_cast<u8*>(frames.address) + slot * frame_bytes;
        std::memcpy(au_buffer, au.data(), au.size());
        SceVideodec2InputData in{};
        in.size = sizeof(in); in.au = au_buffer; in.au_size = au.size();
        in.pts = static_cast<u64>(pts); in.dts = std::numeric_limits<u64>::max();
        SceVideodec2FrameBuffer fb{};
        fb.size = sizeof(fb); fb.buffer = frame_buffer; fb.buffer_size = frame_bytes;
        SceVideodec2OutputInfo out{};
        out.size = sizeof(out);
        int rc = api->Decode(decoder, &in, &fb, &out);
        if (!decoded_once) {
            std::fprintf(stderr, "EDEN_HW_VIDEODEC first-decode rc=0x%08x accepted=%u valid=%u error=%u shown=%u size=%ux%u pitch=%u\n",
                static_cast<unsigned>(rc), fb.accepted, out.valid, out.error, static_cast<unsigned>(shown),
                out.width, out.height, out.pitch_bytes);
            decoded_once = true;
        }
        if (rc) return Fail("decode", rc);
        if (in.size != sizeof(in) || fb.size != sizeof(fb) || out.size != sizeof(out) || out.error)
            return Fail("decode-output");
        if (shown && !out.valid) {
            out = {}; out.size = sizeof(out);
            rc = api->Flush(decoder, &fb, &out);
            if (rc) return Fail("decode-flush", rc);
        }
        // Hidden VP9 references must be submitted, but never paired to an output timestamp.
        if (!shown) return true;
        if (!out.valid || out.error || out.picture_count != 1 || out.codec != codec_type ||
            out.size != sizeof(out) || fb.size != sizeof(fb) || !fb.accepted) return Fail("no-picture");
        const auto pitch = out.pitch_bytes ? out.pitch_bytes : out.pitch;
        if (!pitch || pitch != out.pitch || pitch < out.width || out.width > max_width ||
            out.height > max_height || out.width < picture.coded_width || out.height < picture.coded_height ||
            out.width < picture.width + picture.left || out.height < picture.height + picture.top || (pitch & 1)) return Fail("pitch-size");
        const auto needed = std::uint64_t{pitch} * (out.height + (std::uint64_t{out.height} + 1) / 2);
        const auto start = reinterpret_cast<std::uintptr_t>(frame_buffer);
        const auto output = reinterpret_cast<std::uintptr_t>(out.buffer);
        if (!output || output < start || output - start > frame_bytes ||
            needed > frame_bytes - (output - start) || needed > out.buffer_size) return Fail("frame-bounds");
        auto owned = std::make_shared<FFmpeg::Frame>();
        auto* av = owned->GetFrame();
        if (!av) return Fail("frame-allocation");
        av->format = AV_PIX_FMT_NV12;
        av->width = display.width; av->height = display.height; av->pts = pts;
        av->colorspace = static_cast<AVColorSpace>(picture.matrix);
        av->color_range = picture.full_range ? AVCOL_RANGE_JPEG : AVCOL_RANGE_MPEG;
        if (av_frame_get_buffer(av, 32) < 0) return Fail("frame-allocation");
        const auto* source = static_cast<const u8*>(out.buffer);
        for (int row = 0; row < display.height; ++row)
            std::memcpy(av->data[0] + std::ptrdiff_t{row} * av->linesize[0],
                source + std::size_t{row + picture.top} * pitch + picture.left, display.width);
        source += std::size_t{pitch} * out.height;
        const auto chroma_bytes = (display.width / 2 + display.width % 2) * 2;
        if (picture.left + chroma_bytes > pitch) return Fail("chroma-pitch");
        for (int row = 0; row < (display.height + 1) / 2; ++row)
            std::memcpy(av->data[1] + std::ptrdiff_t{row} * av->linesize[1],
                source + std::size_t{row + picture.top / 2} * pitch + picture.left, chroma_bytes);
        frame = std::move(owned); // No decoder-owned pointers escape, even across Close().
        return true;
    }

    const Videodec2Api* api{};
    VideoCodec current_codec{};
    FFmpeg::FrameDimensions display;
    Picture picture;
    std::vector<u8> prefix;
    DirectMemory compute, gpu, cpu_gpu, input, frames;
    void* queue{};
    void* decoder{};
    void* cpu{};
    std::size_t cpu_bytes{}, frame_bytes{}, next_slot{};
    u32 codec_type{}, max_width{}, max_height{};
    bool owns_queue{}, reset_done{}, have_sps{}, decoded_once{}, failed{};
};

std::unique_ptr<FFmpeg::HardwareVideoDecoder> CreatePs5VideoDecoder() {
    return std::make_unique<Ps5VideoDecoder>();
}
} // namespace

void RegisterPs5VideoDecoder() {
    FFmpeg::RegisterHardwareVideoDecoder(CreatePs5VideoDecoder);
}
} // namespace Eden
#endif
