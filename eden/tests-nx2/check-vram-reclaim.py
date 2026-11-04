"""A staging buffer refused twice gets a last try after the texture cache let go of what it can.

Issue #20, run of #25 (00.065.025, Mario Kart World): a 128 MiB staging buffer was refused, the
123 idle kept buffers (238 MiB) went, it was refused again and the game ended, with 470 MiB free
in blocks of 80 MiB at most. Images the texture cache deleted wait 8 frames for the GPU before
their memory goes. Checks, compiled: the retry rule in headless/staging_buffers.h (refused: idle
buffers go, refused again: reclaim, refused a third time: the error goes on); the production
TextureCache::ReclaimMemory (waits for the GPU before it destroys the deleted images, arms an
aggressive collection, does not run again from inside itself). Then runs the real
tools/prepare-vulkan-port.py and checks the generated pool and rasterizer use them. Fails on main.
"""
from pathlib import Path
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile

assert platform.system() == 'Linux', 'Run on the Linux build server'
root = Path(__file__).resolve().parents[1]
if len(sys.argv) > 1:
    source = Path(sys.argv[1]).resolve()
else:
    source = Path((root / '.local/headless-cache').read_text().strip()) / 'source'
src = source / 'src'
header = (root / 'headless/staging_buffers.h').read_text()
if 'MakeOrReclaim' not in header:
    print('FAIL: a staging buffer refused after the idle kept buffers went is not asked for again: '
          'nothing reclaims the texture cache\'s memory (staging_buffers.h has no MakeOrReclaim)')
    sys.exit(1)
cache = (src / 'video_core/texture_cache/texture_cache.h').read_text()


def function(text, signature):
    assert text.count(signature) == 1, 'Missing production code: ' + signature
    start = text.index(signature)
    at = text.index('{', start)
    depth, end = 1, at + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end] + '\n'


reclaim = function(cache, 'size_t TextureCache<P>::ReclaimMemory() {')
tick = function(cache, 'void TextureCache<P>::TickFrame() {')
armed = tick.find('std::exchange(reclaim_requested, false)')
assert armed != -1 and armed < tick.index('RunGarbageCollector();'), \
    'TickFrame does not make the collector aggressive after a reclaim'
assert 'critical_memory + 1_GiB' in tick[armed:tick.index('RunGarbageCollector();')]

test = r'''
#include <cassert>
#include <cstdio>
#include <stdexcept>
#include <string>
#include "staging_buffers.h"
#include "common/scope_exit.h"
#include "video_core/delayed_destruction_ring.h"
using Eden::StagingBuffers::MakeOrReclaim;

struct Refusal { int result; };
constexpr int kOutOfDeviceMemory = -2;
struct Allocator {
    int refusals = 0, made = 0;
    int error = kOutOfDeviceMemory;
    std::string Make() {
        if (refusals > 0) { --refusals; throw Refusal{error}; }
        ++made;
        return "buffer";
    }
};
static std::string Run(Allocator& allocator, std::string& steps) {
    return MakeOrReclaim<Refusal>([&] { return allocator.Make(); },
                                  [](const Refusal& refused) { return refused.result == kOutOfDeviceMemory; },
                                  [&] { steps += "release "; }, [&] { steps += "reclaim "; });
}

// The production ReclaimMemory, with the production delayed destruction ring.
static bool gpu_idle = false;
static int destroyed = 0;
struct Image {
    bool live = true;
    Image() = default;
    Image(Image&& other) noexcept { other.live = false; }
    ~Image() { if (live) { assert(gpu_idle && "an image was destroyed before the GPU was idle"); ++destroyed; } }
};
template <class P> struct TextureCache;
struct Runtime {
    TextureCache<int>* cache = nullptr;
    int finishes = 0;
    void Finish();
};
template <class P>
struct TextureCache {
    Runtime runtime;
    VideoCommon::DelayedDestructionRing<Image, 8> sentenced_images;
    bool reclaim_requested = false;
    bool reclaiming = false;
    size_t ReclaimMemory();
};
RECLAIM
size_t nested = ~size_t{0};
void Runtime::Finish() {
    ++finishes;
    nested = cache->ReclaimMemory();  // a staging buffer refused while the GPU is waited for
    gpu_idle = true;
}

int main() {
    std::string steps;
    Allocator first_try;
    assert(Run(first_try, steps) == "buffer" && steps.empty());
    Allocator once{1};
    assert(Run(once, steps) == "buffer" && steps == "release ");
    steps.clear();
    Allocator twice{2};  // the console's case: refused, idle buffers went, refused again
    assert(Run(twice, steps) == "buffer" && steps == "release reclaim " && twice.made == 1);
    steps.clear();
    Allocator always{3};
    bool thrown = false;
    try { Run(always, steps); } catch (const Refusal&) { thrown = true; }
    assert(thrown && steps == "release reclaim " && always.made == 0);
    steps.clear();
    Allocator lost{1, 0, -4};  // another error: no retry
    thrown = false;
    try { Run(lost, steps); } catch (const Refusal&) { thrown = true; }
    assert(thrown && steps.empty());

    TextureCache<int> cache;
    cache.runtime.cache = &cache;
    for (int frame = 0; frame < 8; ++frame) {
        for (int i = 0; i < 3; ++i) cache.sentenced_images.Push(Image{});
        if (frame < 7) cache.sentenced_images.Tick();
    }
    // Ticking 7 times cleared nothing yet older than 8 frames: all 24 wait.
    assert(destroyed == 0);
    const size_t gone = cache.ReclaimMemory();
    assert(gone == 24 && destroyed == 24 && cache.runtime.finishes == 1 && nested == 0);
    assert(cache.reclaim_requested && !cache.reclaiming);
    assert(cache.ReclaimMemory() == 0 && cache.runtime.finishes == 2);
    std::printf("PASS: refused twice, the staging buffer is asked for again after the texture cache's reclaim "
                "(not after a third refusal or another error); ReclaimMemory destroyed %zu deleted images after "
                "the GPU was idle, armed an aggressive collection and did not run again from inside itself\n", gone);
}
'''

with tempfile.TemporaryDirectory(prefix='eden-vram-reclaim-') as temp:
    temp = Path(temp)
    compiler = os.environ.get('CXX') or next((c for c in ('clang++-18', 'clang++', 'g++') if shutil.which(c)), None)
    assert compiler, 'No host C++ compiler'
    (temp / 'check.cpp').write_text(test.replace('RECLAIM', 'template <class P>\n' + reclaim))
    subprocess.run([compiler, '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined', '-I' + str(root / 'headless'),
                    '-I' + str(src), str(temp / 'check.cpp'), '-o', str(temp / 'check')], check=True)
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
    body = create.group(0)
    for needed in ('::Eden::StagingBuffers::MakeOrReclaim<vk::Exception>(', 'memory_allocator.CreateBuffer(buffer_ci, usage)',
                   'VK_ERROR_OUT_OF_DEVICE_MEMORY', 'EDEN_STAGING_OOM', 'reclaim ? reclaim() : 0', 'EDEN_VRAM_RECLAIM'):
        assert needed in body, 'Generated CreateStagingBuffer lacks: ' + needed
    assert body.count('memory_allocator.CreateBuffer(') == 1, 'CreateBuffer is called outside MakeOrReclaim'
    rasterizer = (temp / 'out/vulkan_rasterizer.cpp').read_text()
    made = rasterizer[rasterizer.index('RasterizerVulkan::RasterizerVulkan('):rasterizer.index('RasterizerVulkan::~RasterizerVulkan()')]
    for needed in ('staging_pool.reclaim = [this]', 'std::try_to_lock', 'texture_cache.ReclaimMemory()'):
        assert needed in made, 'Generated RasterizerVulkan constructor lacks: ' + needed
    gone = function(rasterizer, 'RasterizerVulkan::~RasterizerVulkan() {')
    assert gone.index('staging_pool.reclaim = nullptr;') < gone.index('scheduler.Finish();'), \
        'The rasterizer does not clear the reclaim before it goes'
print('PASS: the generated staging pool reclaims through the rasterizer\'s texture cache before its last try')
