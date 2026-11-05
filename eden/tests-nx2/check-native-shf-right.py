"""Ocarina of Time's text shader lowers: SHF.R.U32 without .HI, with RZ as the high word.

Run of 00.065.037 on the Ocarina of Time NUP (2026-11-05): the title screen showed its logo, but
almost none of its text. One graphics shader was rejected and its draws failed (5120 and more):
- 0x11767c0000, instruction 0x3e0: SHF.R.U32 R49, R32, R49, RZ (words 20310219 00000031 000016ff
  000fc800), "native register shift mode". The lowering took SHF.L and SHF.R.HI, not SHF.R
  without .HI.

Checks, with the production lower_to_maxwell.h:
- the captured instruction lowers to one Maxwell SHF.R (0x5cf8) with the same destination and
  shift, the low word R32 in its low slot (bits 8-15) and RZ in its high slot (bits 39-46); it
  keeps the clamp (no .W, bit 50);
- with .W set, bit 50 is set;
- the existing forms still lower as before: SHF.L with RZ high, SHF.R.HI with RZ low;
- SHF.R without .HI and a high word other than RZ (a true funnel shift) is still rejected;
- the translator salt changed, so pipelines cached by the older translator are not reused.
Fails on main before this change (the captured instruction is rejected).
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
assert 'NATIVE_TRANSLATOR_SALT = 0x4f554e4345a00008ULL' not in native, \
    'The translator changed but its cache salt did not: older cached pipelines would be reused'

code = r'''
#include <array>
#include <cassert>
#include <cstdio>
#include "shader_recompiler/frontend/ampere/lower_to_maxwell.h"
using Shader::Ampere::Instruction;
using Shader::Ampere::LowerToMaxwell;
static constexpr Instruction exit_insn{{0x0000794d, 0, 0x03800000, 0x000fea00}};
static u32 Bits(u64 word, u32 lo, u32 count) { return u32((word >> lo) & ((u64{1} << count) - 1)); }
static Shader::Ampere::LoweredProgram Lower(const Instruction& insn) {
    const std::array program{insn, exit_insn};
    return LowerToMaxwell(program, {}, true, true);
}
// The one Maxwell SHF (SHF.R 0x5cf8 or SHF.L 0x5bf8) a shift lowered to.
static u64 Shf(const Shader::Ampere::LoweredProgram& lowered, u64 opcode) {
    u64 found = 0; int count = 0;
    for (u64 word : lowered.instructions)
        if ((word & 0xfff8000000000000ULL) == opcode) { found = word; ++count; }
    assert(count == 1);
    return found;
}
// SHF reg: dest (16-23), low (24-31), shift (32-39), high (64-71), U32 (73-74), .W (75),
// .R (76), .HI (80).
static Instruction Shift(u32 dest, u32 low, u32 shift, u32 high, bool right, bool hi, bool wrap) {
    Instruction i{{0x0219U | (dest << 16) | (low << 24), shift,
                   high | (3U << 9) | (u32{wrap} << 11) | (u32{right} << 12) | (u32{hi} << 16),
                   0x000fc800}};
    return i;
}
int main() {
    // The captured instruction.
    const Instruction captured{{0x20310219, 0x00000031, 0x000016ff, 0x000fc800}};
    assert(captured.words[2] == Shift(49, 32, 49, 255, true, false, false).words[2]);
    {
        const auto lowered = Lower(captured);
        assert(lowered);
        const u64 shf = Shf(lowered, 0x5cf8000000000000ULL);
        assert(Bits(shf, 0, 8) == 49);     // destination
        assert(Bits(shf, 8, 8) == 32);     // low word
        assert(Bits(shf, 20, 8) == 49);    // shift
        assert(Bits(shf, 39, 8) == 255);   // high word RZ
        assert(Bits(shf, 50, 1) == 0);     // clamp, as without .W
    }
    {   // .W wraps.
        const auto lowered = Lower(Shift(5, 7, 9, 255, true, false, true));
        assert(lowered);
        const u64 shf = Shf(lowered, 0x5cf8000000000000ULL);
        assert(Bits(shf, 8, 8) == 7 && Bits(shf, 39, 8) == 255 && Bits(shf, 50, 1) == 1);
    }
    {   // Unchanged: SHF.R.HI of {high:RZ} keeps high in the low slot.
        const auto lowered = Lower(Shift(5, 255, 9, 11, true, true, false));
        assert(lowered);
        const u64 shf = Shf(lowered, 0x5cf8000000000000ULL);
        assert(Bits(shf, 0, 8) == 5 && Bits(shf, 8, 8) == 11 && Bits(shf, 39, 8) == 255);
    }
    {   // Unchanged: SHF.L of {RZ:low} keeps low in the high slot.
        const auto lowered = Lower(Shift(5, 7, 9, 255, false, false, false));
        assert(lowered);
        const u64 shf = Shf(lowered, 0x5bf8000000000000ULL);
        assert(Bits(shf, 8, 8) == 255 && Bits(shf, 39, 8) == 7);
    }
    // Still rejected: a real funnel shift right (high word not RZ), SHF.R.HI with a low word.
    assert(!Lower(Shift(5, 7, 9, 11, true, false, false)));
    assert(!Lower(Shift(5, 7, 9, 11, true, true, false)));
    std::printf("PASS: captured SHF.R.U32 R49, R32, R49, RZ lowers to Maxwell SHF.R {RZ:R32}\n");
}
'''
with tempfile.TemporaryDirectory(prefix='nx2-shf-right-') as tmp:
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
