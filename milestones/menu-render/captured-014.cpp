#include "shader_recompiler/frontend/ampere/lower_to_maxwell.h"
#include <cstdio>
int main() {
    using Shader::Ampere::Instruction;
    const std::array<Instruction, 4> samples{{
        {{0x0c0d7361,0xa800001e,0x041e41ff,0x001f4400}},
        {{0x18187b60,0x31018820,0x059e0f20,0x000f4200}},
        {{0x04047b66,0x33c0440e,0x059e8705,0x002f4200}},
        {{0x02017b66,0x33c04401,0x059e8705,0x00114400}},
    }};
    for (unsigned i=0;i<samples.size();++i) {
        const std::array<Instruction,3> code{{
            {{0x03027b6f,0x00800800,0x000003ff,0}},
            samples[i],
            {{0x0000794d,0,0x03800000,0x000fea00}}
        }};
        const auto out=Shader::Ampere::LowerToMaxwell(code);
        std::printf("captured=%u accepted=%d error=%.*s\n",i,bool(out),int(out.error.size()),out.error.data());
        if(!out) return 1;
    }
}
