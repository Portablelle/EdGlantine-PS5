"""Compile the real upscale operation detector with a memory shim; run on dedie."""
from pathlib import Path
import platform
import subprocess
import tempfile

assert platform.system() == 'Linux', 'Compile on dedie'
r = Path(__file__).resolve().parents[1]
src = Path((r / '.local/headless-cache').read_text().strip()) / 'source/src'


def extract(text, signature):
    start = text.index(signature)
    end = text.index('{', start) + 1
    depth = 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


fermi = (src / 'video_core/engines/fermi_2d.h').read_text()
assert 'SrcCopySrgbToLinear = 7' in fermi, 'Missing upscale sRGB decode operation'
operation = extract(fermi, 'enum class Operation') + ';'
compute = (src / 'video_core/engines/kepler_compute.cpp').read_text()
detect = extract(compute, 'static Fermi2D::Operation UpscaleOperation(')
fallback = extract(compute, 'bool KeplerCompute::UpscaleInsteadOfNativeProgram()')
assert '.operation = UpscaleOperation(memory_manager, regs.code_loc.Address(), upscale_srgb_programs)' in fallback
assert '.must_accelerate = true' in fallback
header = (src / 'video_core/engines/kepler_compute.h').read_text()
assert 'std::unordered_map<GPUVAddr, bool> upscale_srgb_programs;' in header

cpp = r'''
#include <array>
#include <cassert>
#include <compare>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <unordered_map>
#include <vector>
using u32 = uint32_t;
using u64 = uint64_t;
using GPUVAddr = u64;
#define LOG_INFO(...) ((void)0)
struct Fermi2D {
''' + operation + r'''
};
struct MemoryManager {
    static constexpr GPUVAddr base = 0x100000;
    std::vector<u32> words = std::vector<u32>(0x21000 / 4);
    size_t mapped = 0x20000;
    unsigned reads = 0;
    bool IsFullyMappedRange(GPUVAddr address, size_t size) const {
        return address >= base && address - base <= mapped && size <= mapped - (address - base);
    }
    void ReadBlock(GPUVAddr address, void* out, size_t size) {
        assert(IsFullyMappedRange(address, size));
        ++reads;
        std::memcpy(out, reinterpret_cast<const char*>(words.data()) + address - base, size);
    }
    void instruction(size_t word, u32 opcode, u32 immediate) {
        words.at(word) = opcode;
        words.at(word + 1) = immediate;
    }
};
''' + detect + r'''
using VkRenderPass = u64;
namespace Tegra::Engines { using Fermi2D = ::Fermi2D; }
''' + extract((src / 'video_core/renderer_vulkan/blit_image.h').read_text(),
              'struct BlitImagePipelineKey') + r''';
int main() {
    using Op = Fermi2D::Operation;
    // Both markers are required, including when they occur in different read blocks.
    for (unsigned mask = 0; mask < 4; ++mask) {
        MemoryManager memory;
        std::unordered_map<GPUVAddr, bool> cache;
        if (mask & 1) memory.instruction(0x3fc, 0xabc00434, 0x292d292d);
        if (mask & 2) memory.instruction(0x400, 0xdef00832, 0x40cc40cc);
        const auto expected = mask == 3 ? Op::SrcCopySrgbToLinear : Op::SrcCopy;
        assert(UpscaleOperation(memory, memory.base, cache) == expected);
        const auto reads = memory.reads;
        assert(reads <= 32);
        assert(UpscaleOperation(memory, memory.base, cache) == expected);
        assert(memory.reads == reads); // Positive AND negative results are cached.
        // A different program address must not inherit the previous result.
        assert(UpscaleOperation(memory, memory.base + 0x2000, cache) == Op::SrcCopy);
    }
    // Wrong opcodes, wrong immediates and unaligned instruction words are not matches.
    for (unsigned mode = 0; mode < 3; ++mode) {
        MemoryManager memory;
        std::unordered_map<GPUVAddr, bool> cache;
        memory.instruction(mode == 2 ? 1 : 0, mode == 0 ? 0x435 : 0x434,
                           mode == 1 ? 0x292d292c : 0x292d292d);
        memory.instruction(4, 0x832, 0x40cc40cc);
        assert(UpscaleOperation(memory, memory.base, cache) == Op::SrcCopy);
    }
    // Stop at mapping boundaries; don't combine markers across a hole.
    MemoryManager short_memory;
    short_memory.mapped = 0x1000;
    short_memory.instruction(0, 0x434, 0x292d292d);
    short_memory.instruction(0x400, 0x832, 0x40cc40cc);
    std::unordered_map<GPUVAddr, bool> cache;
    assert(UpscaleOperation(short_memory, short_memory.base, cache) == Op::SrcCopy);
    assert(short_memory.reads == 1);
    MemoryManager unmapped;
    unmapped.mapped = 0;
    cache.clear();
    assert(UpscaleOperation(unmapped, unmapped.base, cache) == Op::SrcCopy);
    assert(unmapped.reads == 0);
    // Even mapped memory beyond the 128 KiB scan limit is ignored.
    MemoryManager limit;
    limit.mapped = 0x21000;
    limit.instruction(0, 0x434, 0x292d292d);
    limit.instruction(0x8000, 0x832, 0x40cc40cc);
    cache.clear();
    assert(UpscaleOperation(limit, limit.base, cache) == Op::SrcCopy);
    assert(limit.reads == 32);
    for (u64 program = 0; program < 100; ++program) {
        assert(UpscaleOperation(unmapped, program * 0x1000, cache) == Op::SrcCopy);
        assert(cache.size() <= 16);
    }
    const BlitImagePipelineKey plain{1, Op::SrcCopy}, decode{1, Op::SrcCopySrgbToLinear};
    assert(plain != decode); // Never reuse a plain-copy pipeline for the decode.
    std::cout << "UPSCALE_SRGB_DETECTION_PASS\n";
}
'''

shader_dir = src / 'video_core/host_shaders'
shader = shader_dir / 'blit_color_srgb_to_linear.frag'
assert '${CMAKE_CURRENT_SOURCE_DIR}/' + shader.name in (shader_dir / 'CMakeLists.txt').read_text()
blit = (src / 'video_core/renderer_vulkan/blit_image.cpp').read_text()
assert '#include "video_core/host_shaders/blit_color_srgb_to_linear_frag_spv.h"' in blit
assert 'blit_color_srgb_to_linear_frag(BuildShader(device, BLIT_COLOR_SRGB_TO_LINEAR_FRAG_SPV))' in blit
pipeline = extract(blit, 'VkPipeline BlitImageHelper::FindOrEmplaceColorPipeline(')
assert 'key.operation == Tegra::Engines::Fermi2D::Operation::SrcCopySrgbToLinear' in pipeline
assert 'srgb_to_linear ? *blit_color_srgb_to_linear_frag : *blit_color_to_color_frag' in pipeline
cache_source = (src / 'video_core/texture_cache/texture_cache.h').read_text()
assert 'copy.operation == Tegra::Engines::Fermi2D::Operation::SrcCopySrgbToLinear\n            ? RelaxedOptions{} : RelaxedOptions::Samples' in cache_source

with tempfile.TemporaryDirectory(prefix='upscale-srgb-') as td:
    t = Path(td)
    (t / 'test.cpp').write_text(cpp)
    subprocess.run(['clang++-18', '-std=c++20', '-O1', '-g',
                    '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                    str(t / 'test.cpp'), '-o', str(t / 'test')], check=True)
    subprocess.run([str(t / 'test')], check=True)
    subprocess.run(['glslangValidator', '-V', '--target-env', 'spirv1.3',
                    '-o', str(t / 'decode.spv'), str(shader)], check=True)
print('UPSCALE_SRGB_SHADER_INTEGRATION_PASS')
