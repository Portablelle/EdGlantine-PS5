// Offline check of native shaders dumped by the console (logs/rejected-shaders/<key>.source.bin).
// Built against the patched Eden source tree, it runs the same LowerToMaxwell as the console and
// lists every instruction that names a register in the range the extended uniform bank takes and
// that the register shadowing does not handle, then the first error of the full lowering.
//
//   c++ -std=c++20 -O1 -I<patched tree>/src scan.cpp -o scan && ./scan <key>.source.bin...
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iterator>
#include <map>
#include <vector>
#include "shader_recompiler/frontend/ampere/lower_to_maxwell.h"

using namespace Shader::Ampere;

static int Scan(const char* path) {
    std::ifstream file(path, std::ios::binary);
    if (!file) {
        std::printf("%s: cannot open\n", path);
        return 2;
    }
    std::vector<char> bytes((std::istreambuf_iterator<char>(file)), {});
    std::vector<Instruction> code(bytes.size() / sizeof(Instruction));
    std::memcpy(code.data(), bytes.data(), code.size() * sizeof(Instruction));
    std::printf("== %s: %zu instructions\n", path, code.size());

    // Same test as the lowering's shadowing check; R168 is the limit with the extended bank.
    constexpr u32 reserved = 168;
    std::map<u32, std::pair<u32, u32>> unshadowed; // opcode -> (count, first offset)
    for (u32 i = 0; i < code.size(); ++i) {
        const auto& insn = code[i];
        const u32 op = insn.Bits(0, 12);
        bool high = false;
        for (u32 bit : {16U, 24U, 32U, 64U}) {
            if (bit == 32 && insn.Bits(9, 3) != 1 && op != 0xb60 && op != 0xb66 && op != 0x986 &&
                op != 0xb6c && op != 0x98e && op != 0x9a8)
                continue;
            const u32 reg = insn.Bits(bit, 8);
            if (reg >= reserved && reg < 255) high = true;
        }
        if (high && !PrepareRegisterPressure(insn, reserved).valid) {
            auto& entry = unshadowed[op];
            if (entry.first++ == 0) entry.second = i * static_cast<u32>(sizeof(Instruction));
        }
    }
    for (const auto& [op, entry] : unshadowed) {
        const auto& w = code[entry.second / sizeof(Instruction)].words;
        std::printf("  not shadowed: opcode %#05x x%u, first at %#x [%08x %08x %08x %08x]\n", op,
                    entry.first, entry.second, w[0], w[1], w[2], w[3]);
    }

    const auto lowered = LowerToMaxwell(code, {}, true);
    if (lowered) {
        std::printf("  LOWERS: %zu Maxwell instructions\n", lowered.instructions.size());
        return 0;
    }
    const u32 index = lowered.error_offset / sizeof(Instruction);
    if (index < code.size()) {
        const auto& w = code[index].words;
        std::printf("  REJECTED at %#x: %.*s [%08x %08x %08x %08x] opcode %#05x\n",
                    lowered.error_offset, static_cast<int>(lowered.error.size()), lowered.error.data(),
                    w[0], w[1], w[2], w[3], code[index].Bits(0, 12));
    } else {
        std::printf("  REJECTED at %#x: %.*s\n", lowered.error_offset,
                    static_cast<int>(lowered.error.size()), lowered.error.data());
    }
    return 1;
}

int main(int argc, char** argv) {
    int result = 0;
    for (int i = 1; i < argc; ++i) result |= Scan(argv[i]);
    return result;
}
