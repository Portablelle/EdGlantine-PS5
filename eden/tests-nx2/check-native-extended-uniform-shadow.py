"""OoT's last menu-text compute shader: IADD3 R206, R152, 0x20 next to the extended uniform bank.

Run of 00.067.000 on the OoT NUP (2026-11-06): the menu showed only the first letter of each line.
Six of its seven text compute shaders were fixed by the UIMAD layers (99zzzu, 99zzzv). The seventh
was still rejected:
- 0x296c6c7500, instruction 0x60: IADD3 R206, R152, 0x20, RZ (words 98ce7810 00000020 07ffe0ff
  044fe200), "native register shadowing mode".
The program uses UR16 or higher, so the uniform bank takes R168-R215 (UR16-UR31 are R200-R215) and
guest GPRs from R168 up are shadowed: kept in the SSA bank and copied into a free low quartet
around each instruction. IADD3 with an immediate had no entry in that table, so it was rejected.

Checks, with the production lower_to_maxwell.h and register_pressure.h:
- the captured instruction, after a UMOV that writes UR16, lowers: R204-R207 are copied into a
  free low quartet (R164-R167) before the add and back after it, the add writes R166 from R152,
  and UR16 still lands in R200, so it never aliases the guest's R206;
- every ALU form added to the shadowing table rewrites each named high GPR below the limit and
  leaves its other fields alone, and these forms lower with high GPRs next to the extended bank;
- an opcode outside the table is still rejected the same way;
- the translator salt changed, so pipelines cached by the older translator are not reused.
Fails before this change (the captured instruction is rejected).
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
assert 'NATIVE_TRANSLATOR_SALT = 0x4f554e4345a00009ULL' not in native, \
    'The translator changed but its cache salt did not: older cached pipelines would be reused'

code = r'''
#include <array>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <string_view>
#include "shader_recompiler/frontend/ampere/lower_to_maxwell.h"
using Shader::Ampere::Instruction;
using Shader::Ampere::LowerToMaxwell;
using Shader::Ampere::NativeRegisterCopy;
using Shader::Ampere::PrepareRegisterPressure;
static constexpr Instruction exit_insn{{0x0000794d, 0, 0x03800000, 0x000fea00}};
// UMOV UR16, 0x1234: a uniform destination in UR16-UR62 selects the extended uniform bank.
static constexpr Instruction umov_ur16{{0x00107882, 0x1234, 0, 0x000fe200}};
static u32 Bits(u64 word, u32 lo, u32 count) { return u32((word >> lo) & ((u64{1} << count) - 1)); }
static Shader::Ampere::LoweredProgram Lower(const Instruction& insn) {
    const std::array program{umov_ur16, insn, exit_insn};
    return LowerToMaxwell(program, {}, true, true);
}
static bool Contains(const Shader::Ampere::LoweredProgram& lowered, u64 word) {
    for (u64 w : lowered.instructions) if (w == word) return true;
    return false;
}
static u32 Field(const Instruction& insn, u32 bit) { return insn.Bits(bit, 8); }
static Instruction Make(u32 opcode, u32 d, u32 a, u32 b, u32 c, u32 w2_extra = 0) {
    return Instruction{{opcode | (7U << 12) | (d << 16) | (a << 24), b, c | w2_extra, 0x000fe200}};
}
int main() {
    const Instruction captured{{0x98ce7810, 0x00000020, 0x07ffe0ff, 0x044fe200}};
    {
        // Without the fix: rejected at the IADD3 as "native register shadowing mode".
        const auto lowered = Lower(captured);
        if (!lowered) std::printf("FAIL: %.*s at %#x\n", int(lowered.error.size()), lowered.error.data(), lowered.error_offset);
        assert(lowered);
        // R204-R207 borrow R164-R167: saved to bank 2, loaded from bank 1, then the reverse.
        for (u32 i = 0; i < 4; ++i) {
            assert(Contains(lowered, NativeRegisterCopy(2, 164 + i, 0, 164 + i)));
            assert(Contains(lowered, NativeRegisterCopy(0, 164 + i, 1, 204 + i)));
            assert(Contains(lowered, NativeRegisterCopy(1, 204 + i, 0, 164 + i)));
            assert(Contains(lowered, NativeRegisterCopy(0, 164 + i, 2, 164 + i)));
        }
        // No lowered word other than the bank copies names R206 as a destination; the add
        // writes R166 and reads R152.
        bool add = false;
        for (u64 w : lowered.instructions) {
            const bool copy = (w & 0xfff8000000000000ULL) == 0x5c98000000000000ULL && Bits(w, 44, 4) == 10;
            if (copy) continue;
            assert(Bits(w, 0, 8) != 206);
            if (Bits(w, 0, 8) == 166 && Bits(w, 8, 8) == 152) add = true;
        }
        assert(add);
        // UR16 is R200: the UMOV's value lands there, not in a guest register.
        bool ur16 = false;
        for (u64 w : lowered.instructions)
            if (Bits(w, 0, 8) == 200 && Bits(w, 20, 20) == 0x1234) ur16 = true;
        assert(ur16);
    }
    // Every added table entry: high GPRs (R172, R190, R206, R214) are rewritten below R168 and
    // nothing else moves.
    struct Form { u32 opcode; std::array<u32, 4> bits; };
    const Form forms[] = {
        {0xa02, {16}}, {0x919, {16}}, {0x202, {16, 32}}, {0x20c, {24, 32}},
        {0x80c, {24}}, {0xa0c, {24}}, {0xc0c, {24}},
        {0x207, {16, 24, 32}}, {0x217, {16, 24, 32}}, {0x220, {16, 24, 32}}, {0x221, {16, 24, 32}},
        {0x807, {16, 24}}, {0xa07, {16, 24}}, {0x817, {16, 24}}, {0xa17, {16, 24}}, {0xc17, {16, 24}},
        {0x820, {16, 24}}, {0xa20, {16, 24}}, {0xc20, {16, 24}}, {0x821, {16, 24}}, {0xa21, {16, 24}},
        {0x421, {16, 24}}, {0x621, {16, 24}},
        {0x210, {16, 24, 32, 64}}, {0x212, {16, 24, 32, 64}}, {0x223, {16, 24, 32, 64}},
        {0x224, {16, 24, 32, 64}},
        {0x810, {16, 24, 64}}, {0xa10, {16, 24, 64}}, {0xc10, {16, 24, 64}}, {0x423, {16, 24, 64}},
        {0x623, {16, 24, 64}}, {0x823, {16, 24, 64}}, {0xa23, {16, 24, 64}}, {0xc23, {16, 24, 64}},
        {0xa24, {16, 24, 64}}, {0xc24, {16, 24, 64}},
    };
    const u32 high[] = {206, 172, 190, 214};
    for (const auto& form : forms) {
        Instruction insn{{form.opcode | (7U << 12), 0x00000005, 0x00000000, 0x000fe200}};
        u32 n = 0;
        for (u32 bit : form.bits) {
            if (!bit) continue;
            insn.words[bit / 32] = (insn.words[bit / 32] & ~(255U << (bit % 32))) | (high[n++] << (bit % 32));
        }
        const auto pressure = PrepareRegisterPressure(insn, 168);
        if (!pressure.valid) std::printf("FAIL: %#x not shadowed\n", form.opcode);
        assert(pressure.valid);
        n = 0;
        for (u32 bit : form.bits) {
            if (!bit) continue;
            const u32 now = Field(pressure.instruction, bit);
            assert(now < 168 && now % 4 == high[n] % 4);
            ++n;
        }
        // Only the named fields change.
        Instruction masked = pressure.instruction, original = insn;
        for (u32 bit : form.bits) {
            if (!bit) continue;
            masked.words[bit / 32] &= ~(255U << (bit % 32));
            original.words[bit / 32] &= ~(255U << (bit % 32));
        }
        assert(std::memcmp(&masked, &original, sizeof(masked)) == 0);
        assert(pressure.prefix.size() == 8 * n && pressure.suffix.size() == 8 * n);
    }
    // Typical forms lower end to end next to the extended bank.
    const Instruction lowers[] = {
        Make(0x210, 206, 152, 190, 255, 0x07ffe000),          // IADD3 R206, R152, R190, RZ
        Make(0x810, 190, 206, 0x40, 255, 0x07ffe000),         // IADD3 R190, R206, 0x40, RZ
        Make(0x223, 206, 172, 190, 214),                      // FFMA R206, R172, R190, R214
        Make(0x221, 214, 206, 172, 0),                        // FADD R214, R206, R172
        Make(0x220, 206, 172, 190, 0, 0x00400000),            // FMUL R206, R172, R190
        Make(0x202, 206, 0, 190, 0x00000f00),                 // MOV R206, R190
        Instruction{{0x00007919 | (206U << 16), 0, 0x00002100, 0x000fe200}}, // S2R R206, SR_TID.X
    };
    for (const auto& insn : lowers) {
        const auto lowered = Lower(insn);
        if (!lowered) std::printf("FAIL: %#x: %.*s\n", insn.Bits(0, 12), int(lowered.error.size()), lowered.error.data());
        assert(lowered);
        for (u64 w : lowered.instructions) {
            const bool copy = (w & 0xfff8000000000000ULL) == 0x5c98000000000000ULL && Bits(w, 44, 4) == 10;
            if (!copy) assert(Bits(w, 0, 8) < 168 || Bits(w, 0, 8) == 200 || Bits(w, 0, 8) >= 246);
        }
    }
    // Outside the table: still rejected as before (FMNMX register, R206).
    {
        const auto lowered = Lower(Make(0x209, 206, 172, 190, 0));
        assert(!lowered && std::string_view{lowered.error} == "native register shadowing mode");
    }
    std::printf("PASS: IADD3 R206, R152, 0x20 lowers next to UR16 through R164-R167; ALU forms shadowed\n");
}
'''
with tempfile.TemporaryDirectory(prefix='nx2-extended-uniform-shadow-') as tmp:
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
