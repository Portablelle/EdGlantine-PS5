#include "shader_recompiler/frontend/ampere/lower_to_maxwell.h"
#include <cstdio>
int main() {
    using Shader::Ampere::Instruction;
    for (unsigned mode=0;mode<2;++mode) {
        const std::array<Instruction,3> code{{
            {{0x03027b6f,0x00800800,0x000003ff,0}},
            mode ? Instruction{{0x00007361,0x38000027,0x041e0726,0x002f4400}}
                 : Instruction{{0x0a0d7b60,0xb1012400,0x041e41ff,0x00114400}},
            {{0x0000794d,0,0x03800000,0x000fea00}}
        }};
        const auto lowered=Shader::Ampere::LowerToMaxwell(code);
        std::printf("case=%u accepted=%d error=%.*s\n",mode,bool(lowered),int(lowered.error.size()),lowered.error.data());
    }
}
