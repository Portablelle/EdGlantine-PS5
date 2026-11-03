"""Real native decoder teardown/release methods with FFmpeg-free shims; run on dedie."""
from pathlib import Path
import platform
import subprocess
import tempfile

assert platform.system() == 'Linux', 'Compile on dedie'
root = Path(__file__).resolve().parents[1]
source = Path((root / '.local/headless-cache').read_text().strip()) / 'source/src'
text = (source / 'core/hle/service/am/service/native_video_decoder.cpp').read_text()


def method(signature):
    start = text.index(signature)
    end = text.index('{', start) + 1
    depth = 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


# The same harness compiles main, so its failure is a runtime fence assertion.
helper = method('void CompletePendingFences()') if 'void CompletePendingFences()' in text else ''
methods = '\n'.join(method(signature) for signature in (
    'void Reset()', 'void Stop(', 'void Finalize(', 'void Flush(', 'void ReleaseImage('))
cpp = r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <memory>
#include <optional>
#include <vector>
using u8 = uint8_t; using u32 = uint32_t; using s32 = int32_t; using u64 = uint64_t;
struct Result { u32 raw; bool IsSuccess() const { return raw == 0; } };
constexpr Result ResultSuccess{0};
namespace Kernel {
constexpr Result ResultInvalidCombination{1}, ResultInvalidState{2},
                 ResultNotFound{3}, ResultNotImplemented{4};
}
namespace libgav1 { constexpr int kStatusOk = 0; }
#define LOG_DEBUG(...) ((void)0)
struct HLERequestContext {
    std::array<u32, 16> packet{};
    std::vector<u64> reply;
    const u32* CommandBuffer() { return packet.data(); }
};
namespace IPC {
struct ResponseBuilder {
    HLERequestContext& ctx;
    ResponseBuilder(HLERequestContext& c, int) : ctx(c) { ctx.reply.clear(); }
    template<class T> void Push(T value) { ctx.reply.push_back(value); }
};
}
struct Syncpoints {
    u32 guest = 40, host = 40;
    unsigned increments{}, frees{};
    u32 freed_guest{}, freed_host{};
    u32 GetGuestSyncpointValue(u32 id) { assert(id == 7); return guest; }
    void IncrementGuest(u32 id) { assert(id == 7); ++guest; ++increments; }
    void IncrementHost(u32 id) { assert(id == 7); ++host; }
    void FreeSyncpoint(u32 id) {
        assert(id == 7); ++frees; freed_guest = guest; freed_host = host;
    }
    Syncpoints& GetSyncpointManager() { return *this; }
};
struct System {
    Syncpoints sync;
    Syncpoints& Host1x() { return sync; }
};
struct Module {
    Syncpoints* sync;
    Module& GetContainer() { return *this; }
    Syncpoints& GetSyncpointManager() { return *sync; }
};
struct State { std::unique_ptr<Module> module; };
struct Backend { int SignalEOS() { return libgav1::kStatusOk; } };
struct Transfer { void Close(int) {} };
struct Event { void Clear(int) {} };
struct Codec {
    System system;
    State storage{std::make_unique<Module>(Module{&system.sync})};
    State* state = &storage;
    int kernel{};
    std::unique_ptr<Backend> decoder, h264_context = std::make_unique<Backend>(), h264_decoder;
    std::unique_ptr<Transfer> transfer_memory;
    std::unique_ptr<Event> submission_event;
    std::optional<int> configuration{1};
    std::optional<u32> operation_syncpoint{7};
    u64 next_completion_value = 42, pending_input_bytes{}, next_submission_id{1};
    bool started = true, ffmpeg_vp9{};
    struct RegisteredImage { u32 id; u64 completion_value; bool available; };
    std::vector<RegisteredImage> registered_images{{10, 41, false}, {11, 42, false}};
    std::vector<int> pending_inputs, output_properties, decoded_frames, h264_timestamps;
    // Optional hardware state touched by the real Reset; these shims keep this check
    // focused on guest fences and teardown, independently of the Videodec2 API.
    struct HardwareSession { void Reset() {} } h264_backend;
    std::vector<u8> h264_extradata;
    unsigned pumps{}, drains{};
    bool Initialized() const { return decoder || h264_context; }
    void DrainH264() { ++drains; }
    Result PumpOutput() { ++pumps; return ResultSuccess; } // Empty post-EOS queues.
''' + helper + '\n' + methods + r'''
};
HLERequestContext Request(u32 header, u32 words = 0) {
    HLERequestContext ctx; ctx.packet[0] = header; ctx.packet[1] = words; return ctx;
}
void Release(Codec& codec, u32 id) {
    auto ctx = Request(0x14a, 8); ctx.packet[2] = id;
    codec.ReleaseImage(ctx);
    assert(ctx.reply[0] == 0 && ctx.reply[3] == codec.next_completion_value);
}
int main() {
    // 031e58e: EOS releases and Flush stay pending; Stop completes every handed fence.
    Codec stopped;
    Release(stopped, 10); Release(stopped, 11);
    // Idle-image releases also hand out a new fence without producing a frame.
    Release(stopped, 10);
    assert(stopped.next_completion_value == 45 && stopped.system.sync.guest == 40);
    auto flush = Request(0x18); stopped.Flush(flush);
    assert(flush.reply[0] == 0 && stopped.system.sync.guest == 40);
    auto stop = Request(0xdf); stopped.Stop(stop);
    assert(stop.reply[0] == 0 && !stopped.started);
    assert(stopped.system.sync.guest == 45 && stopped.system.sync.host == 45);
    assert(stopped.system.sync.increments == 5 && stopped.system.sync.frees == 0);
    stopped.Stop(stop);
    assert(stopped.system.sync.increments == 5); // Idempotent completion.

    // Finalize must complete before freeing the syncpoint, including without Stop.
    Codec finalized; Release(finalized, 10);
    auto finalize = Request(0x83); finalized.Finalize(finalize);
    assert(finalize.reply[0] == 0 && !finalized.operation_syncpoint);
    assert(finalized.system.sync.frees == 1);
    assert(finalized.system.sync.freed_guest == 43 && finalized.system.sync.freed_host == 43);
    finalized.Finalize(finalize);
    assert(finalized.system.sync.frees == 1 && finalized.system.sync.increments == 3);

    // Fence thresholds are 32-bit even though the service stores its sequence in u64.
    Codec wrapped;
    wrapped.system.sync.guest = wrapped.system.sync.host = 0xfffffffeU;
    wrapped.next_completion_value = 0x100000001ULL;
    wrapped.Stop(stop);
    assert(wrapped.system.sync.guest == 1 && wrapped.system.sync.host == 1);
    assert(wrapped.system.sync.increments == 3);
    Codec reached; reached.system.sync.guest = reached.system.sync.host = 43;
    reached.Stop(stop); assert(reached.system.sync.increments == 0);

    Codec invalid;
    auto malformed = Request(0); invalid.Stop(malformed); invalid.Finalize(malformed);
    assert(invalid.system.sync.increments == 0 && invalid.system.sync.frees == 0);
    Codec unregistered; unregistered.operation_syncpoint.reset();
    unregistered.Stop(stop); unregistered.Finalize(finalize);
    assert(unregistered.system.sync.increments == 0 && unregistered.system.sync.frees == 0);
    std::cout << "NATIVE_VIDEO_PENDING_FENCE_TEARDOWN_PASS\n";
}
'''
with tempfile.TemporaryDirectory(prefix='native-video-decode-fixes-') as td:
    path = Path(td)
    (path / 'test.cpp').write_text(cpp)
    subprocess.run(['clang++-18', '-std=c++20', '-O1', '-g',
                    '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                    str(path / 'test.cpp'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
