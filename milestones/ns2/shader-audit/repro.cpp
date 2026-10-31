#include <cstdio>
#include "shader_recompiler/frontend/ampere/lower_to_maxwell.h"
using Native=Shader::Ampere::Instruction;
int main() {
    const std::array<Native, 15> input{{
        {{0x27945, 208, 0x03800000, 0}},
        {{0x7945, 160, 0x03800000, 0}},
        {{0x17945, 96, 0x03800000, 0}},
        {{0x18942, 0, 0x03800000, 0}},
        {{0x8942, 0, 0x03800000, 0}},
        {{0x8947, 96, 0x03800000, 0}},
        {{0x27802, 2, 0xf00, 0}},
        {{0x7918, 0, 0, 0}},
        {{0x17941, 0, 0x03800000, 0}},
        {{0x27802, 3, 0xf00, 0}},
        {{0x7918, 0, 0, 0}},
        {{0x7941, 0, 0x03800000, 0}},
        {{0x37802, 4, 0xf00, 0}},
        {{0x27941, 0, 0x03800000, 0}},
        {{0x0000794d,0,0x03800000,0x000fea00}},
    }};

 const auto result=Shader::Ampere::LowerToMaxwell(input);
 std::printf("nested barrier: success=%d offset=%u error=%.*s\n",bool(result),result.error_offset,int(result.error.size()),result.error.data());
 std::array<Native,2> attribute{{{{0xff007322,0x000070ff,0x000004ff,0}},{{0x0000794d,0,0x03800000,0x000fea00}}}};
 const auto reserved=Shader::Ampere::LowerToMaxwell(attribute);
 std::printf("attribute formerly rejected by test: success=%d error=%.*s\n",bool(reserved),int(reserved.error.size()),reserved.error.data());
}
