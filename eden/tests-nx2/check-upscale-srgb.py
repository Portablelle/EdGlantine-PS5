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
assert 'std::unordered_map<GPUVAddr, std::pair<u64, bool>> upscale_srgb_programs;' in header

cpp = r'''
#include <array>
#include <cassert>
#include <compare>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <unordered_map>
#include <utility>
#include <vector>
#include "shader_recompiler/frontend/ampere/program_capture.h"
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
    void exit(size_t index) {
        instruction(index * 4, 0x794d, 0);
        words.at(index * 4 + 2) = 0x03800000;
    }
    void branch(size_t index, size_t target, u32 opcode = 0x947) {
        instruction(index * 4, 0x7000 | opcode, static_cast<u32>((target - index - 1) * 16));
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
        std::unordered_map<GPUVAddr, std::pair<u64, bool>> cache;
        if (mask & 1) memory.instruction(0x3fc, 0xabc00434, 0x292d292d);
        if (mask & 2) memory.instruction(0x400, 0xdef00832, 0x40cc40cc);
        const auto expected = mask == 3 ? Op::SrcCopySrgbToLinear : Op::SrcCopy;
        assert(UpscaleOperation(memory, memory.base, cache) == expected);
        const auto reads = memory.reads;
        assert(reads <= 32);
        assert(UpscaleOperation(memory, memory.base, cache) == expected);
        assert(memory.reads == reads + 1); // Validate the first block without rescanning.
        // A different program address must not inherit the previous result.
        assert(UpscaleOperation(memory, memory.base + 0x2000, cache) == Op::SrcCopy);
    }
    // Reusing an address for rewritten code invalidates both negative and positive results.
    MemoryManager rewritten;
    rewritten.exit(2);
    std::unordered_map<GPUVAddr, std::pair<u64, bool>> rewritten_cache;
    for (const auto expected : {Op::SrcCopy, Op::SrcCopySrgbToLinear, Op::SrcCopy}) {
        const bool decode = expected == Op::SrcCopySrgbToLinear;
        rewritten.instruction(0, decode ? 0x434 : 0, decode ? 0x292d292d : 0);
        rewritten.instruction(4, decode ? 0x832 : 0, decode ? 0x40cc40cc : 0);
        rewritten.reads = 0;
        assert(UpscaleOperation(rewritten, rewritten.base, rewritten_cache) == expected);
        assert(rewritten.reads == 1); // Reuse the first-block read through the EXIT.
        rewritten.reads = 0;
        assert(UpscaleOperation(rewritten, rewritten.base, rewritten_cache) == expected);
        assert(rewritten.reads == 1); // Unchanged code never triggers a rescan.
    }
    // An unmapped first block must not reuse a cached positive result.
    rewritten.instruction(0, 0x434, 0x292d292d);
    rewritten.instruction(4, 0x832, 0x40cc40cc);
    assert(UpscaleOperation(rewritten, rewritten.base, rewritten_cache) == Op::SrcCopySrgbToLinear);
    rewritten.mapped = 0;
    rewritten.reads = 0;
    assert(UpscaleOperation(rewritten, rewritten.base, rewritten_cache) == Op::SrcCopy);
    assert(rewritten.reads == 0);
    // Neither or just one marker before EXIT: neighbouring shaders must not supply the rest.
    for (unsigned mask = 0; mask < 4; ++mask) {
        MemoryManager memory;
        std::unordered_map<GPUVAddr, std::pair<u64, bool>> cache;
        memory.instruction(mask & 1 ? 0 : 12, 0x434, 0x292d292d);
        memory.instruction(mask & 2 ? 4 : 16, 0x832, 0x40cc40cc);
        memory.exit(2);
        assert(UpscaleOperation(memory, memory.base, cache) ==
               (mask == 3 ? Op::SrcCopySrgbToLinear : Op::SrcCopy));
        assert(memory.reads == 1);
    }
    // BRA and BSSY forward targets keep capture alive past an early EXIT, across blocks.
    for (const u32 opcode : {0x947U, 0x945U}) {
        MemoryManager memory;
        std::unordered_map<GPUVAddr, std::pair<u64, bool>> cache;
        memory.branch(0, 0x102, opcode);
        memory.exit(1);
        memory.instruction(0x400, 0x434, 0x292d292d);
        memory.instruction(0x404, 0x832, 0x40cc40cc);
        memory.exit(0x102);
        assert(UpscaleOperation(memory, memory.base, cache) == Op::SrcCopySrgbToLinear);
        assert(memory.reads == 2);
    }
    // An unconditional CALL keeps scanning through the main EXIT until its callee's RET.
    MemoryManager called;
    std::unordered_map<GPUVAddr, std::pair<u64, bool>> end_cache;
    called.branch(0, 4, 0x944);
    called.exit(1);
    called.instruction(16, 0x434, 0x292d292d);
    called.instruction(20, 0x832, 0x40cc40cc);
    called.instruction(24, 0x7950, 0);
    assert(UpscaleOperation(called, called.base, end_cache) == Op::SrcCopySrgbToLinear);
    assert(called.reads == 1);
    // Invalid branch targets force and cache a plain copy even after finding both markers.
    MemoryManager invalid;
    end_cache.clear();
    invalid.instruction(0, 0x434, 0x292d292d);
    invalid.instruction(4, 0x832, 0x40cc40cc);
    invalid.instruction(8, 0x7947, 1); // Target is not aligned to a 16-byte instruction.
    assert(UpscaleOperation(invalid, invalid.base, end_cache) == Op::SrcCopy);
    assert(invalid.reads == 1);
    assert(!end_cache.at(invalid.base).second);
    invalid.reads = 0;
    assert(UpscaleOperation(invalid, invalid.base, end_cache) == Op::SrcCopy);
    assert(invalid.reads == 1);
    // Wrong opcodes, wrong immediates and unaligned instruction words are not matches.
    for (unsigned mode = 0; mode < 3; ++mode) {
        MemoryManager memory;
        std::unordered_map<GPUVAddr, std::pair<u64, bool>> cache;
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
    std::unordered_map<GPUVAddr, std::pair<u64, bool>> cache;
    assert(UpscaleOperation(short_memory, short_memory.base, cache) == Op::SrcCopy);
    assert(short_memory.reads == 1);
    MemoryManager unmapped;
    unmapped.mapped = 0;
    cache.clear();
    assert(UpscaleOperation(unmapped, unmapped.base, cache) == Op::SrcCopy);
    assert(unmapped.reads == 0 && cache.empty());
    // Even mapped memory beyond the 128 KiB scan limit is ignored.
    MemoryManager limit;
    limit.mapped = 0x21000;
    limit.instruction(0, 0x434, 0x292d292d);
    limit.instruction(0x8000, 0x832, 0x40cc40cc);
    cache.clear();
    assert(UpscaleOperation(limit, limit.base, cache) == Op::SrcCopy);
    assert(limit.reads == 32);
    MemoryManager bounded;
    cache.clear();
    for (u64 program = 0; program < 100; ++program) {
        assert(UpscaleOperation(bounded, bounded.base + program * 0x100, cache) == Op::SrcCopy);
        assert(cache.size() == program % 16 + 1);
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
                    '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-I' + str(src),
                    str(t / 'test.cpp'), '-o', str(t / 'test')], check=True)
    subprocess.run([str(t / 'test')], check=True)
    subprocess.run(['glslangValidator', '-V', '--target-env', 'spirv1.3',
                    '-o', str(t / 'decode.spv'), str(shader)], check=True)
print('UPSCALE_SRGB_SHADER_INTEGRATION_PASS')
