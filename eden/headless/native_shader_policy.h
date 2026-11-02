// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>

namespace Eden::NativeShaderPolicy {
// Keep the unqualified lowering policy for other titles while this fix is
// validated on Pokopia. This is selected per program, never cached per process.
constexpr bool CorrectFloatSelect(std::uint64_t program_id) {
    return program_id == 0x0400A3A01EE4C000ULL;
}
constexpr unsigned CacheTag(std::uint64_t program_id) {
    if (program_id == 0x040074A01BF12000ULL) return 0x201U;
    return CorrectFloatSelect(program_id) ? 0x100U : 0U;
}
} // namespace Eden::NativeShaderPolicy
