"""Compile the real synchronous frame converter and Common::ThreadWorker on dedie.

Only platform thread-name/affinity calls are shimmed; the queue, threads, waits,
row conversion, environment parsing and frame partitioning are production code.
Correctness runs with ASan/UBSan at O1/O2. The separate O2 benchmark has no
sanitizers, uses a random 4K frame, and prints best-of-15 times without gating.
Main fails the explicit parallel-converter/environment presence assertion.
"""
from pathlib import Path
import os
import platform
import subprocess
import tempfile

assert platform.system() == 'Linux', 'Compile on dedie'
root = Path(__file__).resolve().parents[1]
source = Path((root / '.local/headless-cache').read_text().strip()) / 'source/src'
decoder = (source / 'core/hle/service/am/service/native_video_decoder.cpp').read_text()
layout = (source / 'core/hle/service/am/service/native_video_layout.h').read_text()
assert ('class NativeVideoConverter {' in decoder
        and 'EDEN_NX2_VIDEO_CONVERT_THREADS' in decoder
        and 'video_converter.Convert(' in decoder), 'main has no persistent parallel frame converter'


def definition(text, name):
    start = text.index(name)
    begin = text.index('{', start)
    end, depth = begin + 1, 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


scalar = definition(layout, 'inline std::array<u8, 4> ConvertNativeVideoYuv709(')
row = definition(layout, 'inline void ConvertNativeVideoYuv709Row(')
assert '_mm_setr_ps' in row and 'load_chroma' not in row, 'restore the main row converter'
parser = definition(decoder, 'u32 NativeVideoConvertThreads(')
converter = definition(decoder, 'class NativeVideoConverter {') + ';'
# Confirm the production RGBA call is still within the Convert timing interval.
start = decoder.index('video_converter.Convert(')
end = decoder.index('PerfMark(Convert, phase);', start)
assert 'PerfMark(' not in decoder[start:end]
assert 'ConvertNativeVideoYuv709Row' not in decoder[start:end]

cpp = r'''
#include <algorithm>
#include <array>
#include <atomic>
#include <cassert>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <emmintrin.h>
#include <limits>
#include <memory>
#include <random>
#include <string>
#include <thread>
#include <vector>
#include "common/scope_exit.h"
#include "common/thread_worker.h"
namespace Test {
std::atomic<unsigned> started{}, exited{};
struct WorkerLifetime {
    WorkerLifetime() { ++started; }
    ~WorkerLifetime() { ++exited; }
};
void WaitStarted(unsigned count) {
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    while (started.load() < count && std::chrono::steady_clock::now() < deadline)
        std::this_thread::yield();
    assert(started.load() == count);
}
}
namespace Common {
void SetCurrentThreadName(const char* name) {
    assert(std::strcmp(name, "VideoConvert") == 0);
    thread_local Test::WorkerLifetime lifetime;
    (void)lifetime;
}
void SetCurrentThreadPriority(ThreadPriority) {}
void SetCurrentThreadToEfficiencyCores() {}
void SetCurrentThreadToBackgroundWork() {}
void SetCurrentThreadToAllCores() {}
}
'''
cpp += scalar + '\n' + row + '\n' + parser + '\n' + converter + '\n'
cpp += r'''
static void Setting(const char* value) {
    if (value) assert(setenv("EDEN_NX2_VIDEO_CONVERT_THREADS", value, 1) == 0);
    else assert(unsetenv("EDEN_NX2_VIDEO_CONVERT_THREADS") == 0);
}
struct Frame {
    u32 width, height, row_bytes, pool_height;
    std::array<u32, 3> strides;
    std::array<std::vector<u8>, 3> planes;
    Frame(u32 w, u32 h, unsigned seed, bool padded = false)
        : width(w), height(h), row_bytes((w * 4 + 63) / 64 * 64), pool_height(h + 3),
          strides{w + (padded ? 13U : 0U), (w + 1) / 2 + (padded ? 7U : 0U),
                  (w + 1) / 2 + (padded ? 3U : 0U)} {
        std::mt19937 random(seed);
        for (unsigned i = 0; i < 3; ++i) {
            planes[i].resize(size_t{strides[i]} * (i ? (h + 1) / 2 : h));
            for (auto& byte : planes[i]) byte = u8(random());
        }
    }
    std::array<const u8*, 3> Pointers() const {
        return {planes[0].data(), planes[1].data(), planes[2].data()};
    }
    size_t Bytes() const { return size_t{row_bytes} * pool_height; }
};
// The original PumpOutput loop, including its global y/2 chroma addressing.
static void Single(u8* rgba, const Frame& frame, bool full) {
    for (u32 y = 0; y < frame.height; ++y)
        ConvertNativeVideoYuv709Row(rgba + size_t{y} * frame.row_bytes,
            frame.planes[0].data() + size_t{y} * frame.strides[0],
            frame.planes[1].data() + size_t{y / 2} * frame.strides[1],
            frame.planes[2].data() + size_t{y / 2} * frame.strides[2], frame.width, full);
}
static void Compare(NativeVideoConverter& converter, const Frame& frame, bool full) {
    constexpr unsigned guard = 17; // Unaligned destination plus prefix/suffix guards.
    std::vector<u8> expected(frame.Bytes() + guard * 2, 0), actual = expected;
    for (auto* bytes : {&actual, &expected}) {
        std::fill_n(bytes->begin(), guard, 0xCD);
        std::fill_n(bytes->end() - guard, guard, 0xCD);
    }
    Single(expected.data() + guard, frame, full);
    converter.Convert(actual.data() + guard, frame.row_bytes, frame.Pointers(), frame.strides,
                      frame.width, frame.height, full);
    // Includes untouched padding columns/rows and both guards. Also checks that
    // every queued slice is finished when Convert returns to the swizzle caller.
    assert(actual == expected);
}
static void Correctness() {
    const std::array<std::array<u32, 2>, 8> sizes{{
        {1, 1}, {7, 65}, {257, 63}, {257, 64}, {1024, 64},
        {1025, 65}, {513, 129}, {1919, 131}}};
    struct Option { const char* setting; unsigned threads; };
    const Option options[] = {
        {nullptr, 4}, {"1", 1}, {"2", 2}, {"3", 3}, {"4", 4}, {"5", 5},
        {"6", 6}, {"7", 7}, {"8", 8}, {"0", 1}, {"-5", 1}, {"99", 8},
        {"999999999999999999999999", 8}, {"-999999999999999999999999", 1},
        {"", 4}, {"bad", 4}, {"2bad", 4}};
    for (auto option : options) {
        Setting(option.setting);
        assert(NativeVideoConvertThreads() == option.threads);
        const auto before = Test::started.load();
        assert(Test::exited.load() == before);
        {
            NativeVideoConverter converter;
            // Configuration is captured per codec, never re-read by worker tasks.
            Setting("1");
            for (auto size : sizes) {
                for (bool full : {false, true}) {
                    Frame frame(size[0], size[1], size[0] + 17 * size[1] + full, full);
                    Compare(converter, frame, full);
                }
                if (size[0] == 257 && size[1] == 64)
                    assert(Test::started.load() == before); // Tiny/short frames create no pool.
            }
            const auto workers = option.threads - 1;
            Test::WaitStarted(before + workers);
            // Reuse the same codec through repeated frames and large/small/range
            // changes, just as Stop/Reset can be followed by another configuration.
            for (unsigned i = 0; i < 8; ++i) {
                Frame frame(i % 2 ? 3 : 1025, i % 2 ? 3 : 65, i, true);
                Compare(converter, frame, i % 2);
            }
            assert(Test::started.load() == before + workers); // No per-frame thread creation.
            assert(Test::exited.load() == before); // Workers persist while the codec lives.
        }
        assert(Test::started.load() == before + option.threads - 1);
        assert(Test::exited.load() == Test::started.load()); // Destruction joins every worker.
    }
    // Repeated destruction both before lazy pool creation and after active frames.
    for (unsigned i = 0; i < 12; ++i) {
        Setting(nullptr);
        NativeVideoConverter converter;
        if (i % 2) Compare(converter, Frame(1025, 65, i), false);
    }
    assert(Test::started.load() == Test::exited.load());
    std::puts("Exact frames, 1..8 threads, env parsing, padding, pool reuse and shutdown OK");
}
static double Bench(const Frame& frame, bool full, const char* setting, std::vector<u8>& output) {
    Setting(setting);
    NativeVideoConverter converter;
    auto convert = [&] {
        converter.Convert(output.data(), frame.row_bytes, frame.Pointers(), frame.strides,
                          frame.width, frame.height, full);
    };
    convert(); convert(); // Exclude persistent pool startup and warm the buffers.
    double best = std::numeric_limits<double>::max();
    for (unsigned i = 0; i < 15; ++i) {
        const auto start = std::chrono::steady_clock::now();
        convert();
        const auto ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
        best = (std::min)(best, ms);
    }
    return best;
}
int main(int argc, char** argv) {
    if (argc > 1 && std::string(argv[1]) == "--bench") {
        Frame frame(3840, 2160, 0x595556);
        std::vector<u8> single(frame.Bytes()), parallel(frame.Bytes());
        for (bool full : {false, true}) {
            const auto one = Bench(frame, full, "1", single);
            const auto four = Bench(frame, full, nullptr, parallel);
            assert(single == parallel);
            std::printf("NON-GATING O2 4K best-of-15 range=%s: 1 thread %.3f ms, default 4 threads %.3f ms, speedup %.3fx\n",
                        full ? "full" : "limited", one, four, one / four);
        }
    } else {
        Correctness();
    }
}
'''
with tempfile.TemporaryDirectory(prefix='native-video-fast-yuv-rgba-') as temp:
    path = Path(temp)
    (path / 'check.cpp').write_text(cpp)
    common = ['clang++-18', '-std=c++20', '-g', '-pthread', '-march=x86-64',
              '-msse2', '-mno-avx', '-ffp-contract=off', '-I', str(source),
              str(path / 'check.cpp')]
    for opt in ('-O1', '-O2'):
        binary = path / ('check' + opt)
        subprocess.run(common + [opt, '-fsanitize=address,undefined',
                                '-fno-sanitize-recover=all', '-fno-omit-frame-pointer',
                                '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=120,
                       env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=1'})
    binary = path / 'bench'
    subprocess.run(common + ['-O2', '-o', str(binary)], check=True)
    subprocess.run([str(binary), '--bench'], check=True, timeout=120)
