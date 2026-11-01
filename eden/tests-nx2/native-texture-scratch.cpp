// SPDX-License-Identifier: GPL-3.0-or-later
#include "shader_recompiler/frontend/ampere/lower_to_maxwell.h"
#include <cassert>
#include <cstdio>

// Execute the small subset emitted by this regression. Texture/conversion output
// is mocked; guest register preservation across its scratch writes is the target.
static std::array<std::array<u32,256>,3> Execute(std::span<const u64> code) {
    std::array<std::array<u32,256>,3> banks{};
    for(const u64 word:code) {
        const auto destination=word&255U, source=(word>>20)&255U;
        const auto op=word>>48;
        if(op==0x5c98) {
            if(((word>>44)&15U)==10) banks[(word>>8)&3U][destination]=banks[(word>>10)&3U][source];
            else banks[0][destination]=banks[0][source];
        } else if((word>>56)==0x01) banks[0][destination]=static_cast<u32>(word>>20);
        else if(op==0x5c10) banks[0][destination]=banks[0][(word>>8)&255U]+banks[0][source];
        else if((word>>56)==0xc8) for(unsigned i=0;i<4;++i) banks[0][destination+i]=0x3f800000U+i;
        else if(op==0x5ca8) banks[0][destination]=0x1234U; // Deliberately clobber the conversion temporary.
        else if(op==0x5c18) banks[0][destination]=0x12341234U;
        else if((word>>52)==0xe30) {} // EXIT
        else {std::fprintf(stderr,"Unhandled lowered instruction: %016llx\n",static_cast<unsigned long long>(word));assert(false);}
        banks[0][255]=0;
    }
    return banks;
}
int main() {
    using Shader::Ampere::Instruction;
    for(unsigned high:{246U,247U}) {
        const u32 value=0x76543210U+high;
        const std::array<Instruction,4> program{{
            {{(high<<16)|0x7802U,value,0x00000f00,0}},
            {{0x06027b63,0x33c04407,0x041e8f03,0x000fc200}},
            {{(high<<24)|(10U<<16)|0x7824U,1,0x078e02ff,0}},
            {{0x0000794d,0,0x03800000,0x000fea00}},
        }};
        assert(!Shader::Ampere::LowerToMaxwell(program)); // Without shadowing, reject safely.
        const auto lowered=Shader::Ampere::LowerToMaxwell(program,{},true);
        if(!lowered)std::fprintf(stderr,"Lowering failed: %.*s\n",int(lowered.error.size()),lowered.error.data());
        assert(lowered);
        const auto banks=Execute(lowered.instructions);
        assert(banks[0][10]==value); // Value live across the gather must survive.
        assert(banks[1][high]==value);
    }
    std::puts("TEXTURE_SCRATCH_OK: live R246/R247 preserved with shadowing; unsafe path rejected");
}
