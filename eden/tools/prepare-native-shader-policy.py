"""Apply PS5 title policy and cache tags to generated platform sources."""
from pathlib import Path
import sys

def environment(source: str) -> str:
    if 'NX2_POKOPIA_FSEL' in source:
        return source
    old = '    auto lowered = Shader::Ampere::LowerToMaxwell(native, verified_traps, true);'
    assert source.count(old) == 1, 'Pinned native translation call changed'
    return '#include "native_shader_policy.h"\n' + source.replace(old, '''    const bool correct_float_select = Eden::NativeShaderPolicy::CorrectFloatSelect(Settings::GetCurrentProgramID());
    if (correct_float_select) {
        const auto affected = std::count_if(native.begin(), native.end(), [](const Instruction& i) {
            const auto op = i.Bits(0, 12);
            return (op == 0x208 || op == 0x808 || op == 0xa08) &&
                   (i.Bits(72, 2) || i.Bits(62, 2));
        });
        static std::atomic<unsigned> reported{};
        if (affected && reported.fetch_add(1, std::memory_order_relaxed) < 8)
            LOG_INFO(Shader, "NX2_POKOPIA_FSEL key={:016x} modifiers={}", native_program_key, affected);
    }
    auto lowered = Shader::Ampere::LowerToMaxwell(native, verified_traps, true, correct_float_select);''')


def pipeline(source: str) -> str:
    if 'NativeShaderPolicy::CacheTag' in source:
        return source
    old = '    return Shader::VulkanShaderCacheVersion();'
    assert source.count(old) == 1, 'Pinned Vulkan shader-cache version changed'
    return '#include "native_shader_policy.h"\n' + source.replace(old,
        '    return Shader::VulkanShaderCacheVersion() + Eden::NativeShaderPolicy::CacheTag(Settings::GetCurrentProgramID());')


def shader_environment(source: str) -> str:
    adapted = environment(source)
    if 'NX2_BANANZA_COMPUTE' not in adapted:
        call = '    auto lowered = Shader::Ampere::LowerToMaxwell(native, verified_traps, true, correct_float_select);'
        assert adapted.count(call) == 1
        adapted = adapted.replace(call, call + r'''
    if (Settings::GetCurrentProgramID() == 0x040074A01BF12000ULL) {
        const auto half_predicates = std::count_if(native.begin(), native.end(), [](const Instruction& i) { return i.Bits(0, 12) == 0x234; });
        const auto breaks = std::count_if(native.begin(), native.end(), [](const Instruction& i) { return i.Bits(0, 12) == 0x942; });
        static std::atomic<unsigned> reported_bananza{};
        if ((half_predicates || breaks) && reported_bananza.fetch_add(1, std::memory_order_relaxed) < 12)
            LOG_INFO(Shader, "NX2_BANANZA_COMPUTE key={:016x} half_predicates={} breaks={} lowered={}", native_program_key, half_predicates, breaks, bool(lowered));
    }''')
    return adapted
