"""Pokopia's two rejected compute shaders lower: wide local spills and one-term predicate LUTs.

Run of 00.065.028 in Pokopia (2026-11-04): compute shaders were rejected and their dispatches
skipped (sprites flickered when many were on screen):
- 0x2b1d765900, instruction 0x3c020: STL.128 [RZ+0x80], R12 (words ff007387 0000800c 00100c00
  0001e800), "native local scalar spill mode": only 32-bit local spills were lowered;
- 0x2b1d437300, instruction 0x72f0: UPLOP3.LUT with LUT 0x04 (0000789c 00000000 0270e054
  000fc400), "native uniform predicate LUT mode": only 0x80 and 0x40 were lowered.

Checks, with the production lower_to_maxwell.h:
- both captured instructions now lower;
- LDL/STL of 32, 64 and 128 bits become Maxwell LDL/STL with that size (bits 48-50), the same
  registers and offset. Misaligned registers or offsets, a wide RZ store, and (without register
  spills) registers reaching the lowering's reserved range are still rejected;
- for each of the 8 one-term LUTs and each of the 8 values of its three sources, the PSETP
  emitted gives the LUT's value (predicates modelled as the lowering maps them: UPn in P(6-n)),
  and two-term LUTs are still rejected;
- the translator salt changed, so pipelines cached by the older translator are not reused.
Fails on main before this change (both captured instructions are rejected).
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
if len(sys.argv) > 1:
    source = Path(sys.argv[1]).resolve() / 'src'
else:
    source = Path((root / '.local/headless-cache').read_text().strip()) / 'source/src'
native = (source / 'shader_recompiler/frontend/ampere/native.h').read_text()
assert 'NATIVE_TRANSLATOR_SALT = 0x4f554e4345a00007ULL' not in native, \
    'The translator changed but its cache salt did not: older cached pipelines would be reused'

code = r'''
#include <array>
#include <cassert>
#include <cstdio>
#include <vector>
#include "shader_recompiler/frontend/ampere/lower_to_maxwell.h"
using Shader::Ampere::Instruction;
using Shader::Ampere::LowerToMaxwell;
static constexpr Instruction exit_insn{{0x0000794d, 0, 0x03800000, 0x000fea00}};
static u32 Bits(u64 word, u32 lo, u32 count) { return u32((word >> lo) & ((u64{1} << count) - 1)); }
static Shader::Ampere::LoweredProgram Lower(const Instruction& insn, bool spills = true) {
    const std::array program{insn, exit_insn};
    return LowerToMaxwell(program, {}, spills, true);
}
// The Maxwell LDL/STL a local access lowered to (exactly one).
static u64 LocalAccess(const Shader::Ampere::LoweredProgram& lowered, bool store) {
    const u64 opcode = store ? 0xef50000000000000ULL : 0xef40000000000000ULL;
    u64 found = 0; int count = 0;
    for (u64 word : lowered.instructions)
        if ((word & 0xfff8000000000000ULL) == opcode) { found = word; ++count; }
    assert(count == 1);
    return found;
}
static Instruction Local(bool store, u32 data, u32 address, u32 offset, u32 width, u32 mode) {
    Instruction i{{(store ? 0x387U : 0x983U) | 0x7000U | (address << 24), 0, mode | (width << 9), 0x0001e800}};
    if (store) i.words[1] = data | (offset << 8);  // a store's destination field is 0
    else i.words[0] |= data << 16, i.words[1] = offset << 8;
    return i;
}
int main() {
    // The captured spill: STL.128 [RZ+0x80], R12.
    const Instruction spill{{0xff007387, 0x0000800c, 0x00100c00, 0x0001e800}};
    const auto lowered_spill = Lower(spill);
    if (!lowered_spill) { std::printf("FAIL: captured STL.128 rejected: %.*s\n", int(lowered_spill.error.size()), lowered_spill.error.data()); return 1; }
    const u64 stl = LocalAccess(lowered_spill, true);
    assert(Bits(stl, 48, 3) == 6 && Bits(stl, 0, 8) == 12 && Bits(stl, 8, 8) == 255 && Bits(stl, 20, 24) == 0x80);
    // 32, 64 and 128 bits, stores and both load modes; the 32-bit form is unchanged (size 4).
    size_t local_checks = 0;
    for (bool store : {true, false}) for (u32 width : {4U, 5U, 6U}) for (u32 mode : {0x00100000U, 0x00300000U}) {
        if (store && mode == 0x00300000U) continue;
        const u32 count = width == 6 ? 4 : width == 5 ? 2 : 1;
        const auto lowered = Lower(Local(store, 8, 2, 0x40, width, mode));
        if (!lowered) { std::printf("FAIL: %s width %u mode %#x rejected: %.*s\n", store ? "STL" : "LDL", width, mode,
                                    int(lowered.error.size()), lowered.error.data()); return 1; }
        const u64 word = LocalAccess(lowered, store);
        assert(Bits(word, 48, 3) == width && Bits(word, 0, 8) == 8 && Bits(word, 8, 8) == 2 && Bits(word, 20, 24) == 0x40);
        if (count > 1) {
            assert(!Lower(Local(store, 9, 2, 0x40, width, mode)));           // misaligned register
            assert(!Lower(Local(store, 8, 2, 0x40 + 4, width, mode)));       // misaligned offset
            // Without register spills the lowering keeps R246 up: R244.128 would reach it.
            if (count == 4) assert(!Lower(Local(store, 244, 2, 0x40, width, mode), false));
            assert(Lower(Local(store, 240, 2, 0x40, width, mode), false));
        }
        ++local_checks;
    }
    assert(!Lower(Local(true, 255, 2, 0x40, 6, 0x00100000U)));               // wide RZ store
    assert(!Lower(Local(true, 8, 2, 0x40, 3, 0x00100000U)));                 // 16-bit
    assert(!Lower(Local(true, 8, 2, 0x40, 4, 0x00500000U)));                 // other mode bits

    // The captured predicate LUT: 0x04 = !a & b & !c.
    const Instruction lop{{0x0000789c, 0x00000000, 0x0270e054, 0x000fc400}};
    const auto lowered_lop = Lower(lop);
    if (!lowered_lop) { std::printf("FAIL: captured UPLOP3 LUT 0x04 rejected: %.*s\n", int(lowered_lop.error.size()), lowered_lop.error.data()); return 1; }
    // Every one-term LUT, sources a = UP1, b = UP2, c = UP3: the PSETP gives the LUT's value.
    size_t lut_checks = 0;
    for (u32 term = 0; term < 8; ++term) {
        const u32 lut = 1U << term;
        Instruction i = lop;
        i.words[2] = (i.words[2] & ~(0x7U | (0x1fU << 8) | (0xfU << 4) | (0xfU << 13) | (0xfU << 23))) |
                     (lut & 7) | ((lut >> 3) << 8) | (3U << 4) | (2U << 13) | (1U << 23);
        const auto lowered = Lower(i);
        assert(lowered);
        u64 psetp = 0; int count = 0;
        for (u64 word : lowered.instructions)
            if ((word & 0xfff8000000000000ULL) == 0x5090000000000000ULL) { psetp = word; ++count; }
        assert(count == 1 && Bits(psetp, 24, 2) == 0 && Bits(psetp, 45, 2) == 0);   // AND, AND
        for (u32 values = 0; values < 8; ++values) {
            const bool a = values & 4, b = values & 2, c = values & 1;
            std::array<bool, 8> p{};
            p[6 - 1] = a; p[6 - 2] = b; p[6 - 3] = c; p[7] = true;
            const auto read = [&](u32 field) { return p[field & 7] ^ bool(field & 8); };
            const bool result = read(Bits(psetp, 12, 4)) && read(Bits(psetp, 29, 4)) && read(Bits(psetp, 39, 4));
            assert(result == bool((lut >> ((a << 2) | (b << 1) | c)) & 1));
            ++lut_checks;
        }
    }
    for (u32 lut : {0x00U, 0x03U, 0xc0U, 0xffU}) {
        Instruction i = lop;
        i.words[2] = (i.words[2] & ~(0x7U | (0x1fU << 8))) | (lut & 7) | ((lut >> 3) << 8);
        assert(!Lower(i));
    }
    std::printf("PASS: captured STL.128 and UPLOP3 LUT 0x04 lower; %zu local access forms, %zu LUT values\n",
                local_checks, lut_checks);
}
'''
with tempfile.TemporaryDirectory(prefix='nx2-spill-lut-') as tmp:
    t = Path(tmp)
    (t / 'check.cpp').write_text(code)
    compiler = os.environ.get('CXX') or next((c for c in ('clang++-18', 'clang++', 'c++') if shutil.which(c)), None)
    flags = ['-std=c++20', '-O1', '-g']
    if sys.platform.startswith('linux'):
        flags += ['-fsanitize=address,undefined', '-fno-omit-frame-pointer']
    subprocess.run([compiler, *flags, '-I' + str(source), '-I' + str(root / 'headless'), str(t / 'check.cpp'),
                    '-o', str(t / 'check')], check=True)
    result = subprocess.run([str(t / 'check')])
    sys.exit(result.returncode)
