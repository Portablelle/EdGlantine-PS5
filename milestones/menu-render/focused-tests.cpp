#include <bit>
#include <array>
#include <vector>
#include <catch2/catch_test_macros.hpp>
#include <catch2/generators/catch_generators.hpp>
#include "shader_recompiler/environment.h"
#include "shader_recompiler/object_pool.h"
#include "shader_recompiler/frontend/ampere/lower_to_maxwell.h"
#include "shader_recompiler/frontend/ir/basic_block.h"
#include "shader_recompiler/frontend/ir/modifiers.h"
#include "shader_recompiler/frontend/maxwell/decode.h"
#include "shader_recompiler/frontend/maxwell/translate/impl/impl.h"
namespace IR=Shader::IR;
using Native=Shader::Ampere::Instruction;
class EmptyEnvironment : public Shader::Environment {
public:
    bool HasNativeRegisterCopies() const override { return true; }
    u64 ReadInstruction(u32) override { throw std::logic_error("unexpected instruction read"); }
    u32 ReadCbufValue(u32, u32) override { throw std::logic_error("unexpected constant folding"); }
    Shader::TextureType ReadTextureType(u32) override { return {}; }
    Shader::TexturePixelFormat ReadTexturePixelFormat(u32) override { return {}; }
    bool IsTexturePixelFormatInteger(u32) override { return false; }
    u32 ReadViewportTransformState() override { return 1; }
    u32 TextureBoundBuffer() const override { return 0; }
    u32 LocalMemorySize() const override { return local_size; }
    u32 local_size{};
    u32 SharedMemorySize() const override { return 0; }
    std::array<u32, 3> WorkgroupSize() const override { return {}; }
    bool HasHLEMacroState() const override { return false; }
    std::optional<Shader::ReplaceConstant> GetReplaceConstBuffer(u32, u32) override { return {}; }
    void Dump(u64, u64) override {}
};

constexpr std::array<Native,1> VertexTransform{{{{0x0000794d,0,0x03800000,0x000fea00}}}};
void TranslateScalarNative(std::span<const Native> input, IR::Block& block, bool shadow = false, u32 local_size = 0) {
    const auto lowered = Shader::Ampere::LowerToMaxwell(input, {}, shadow);
    INFO("offset=" << lowered.error_offset << " error=" << lowered.error);
    REQUIRE(lowered);
    EmptyEnvironment env;
    env.local_size = local_size;
    Shader::Maxwell::TranslatorVisitor visitor{env, block};
    for (u64 word : lowered.instructions) {
        const auto opcode = Shader::Maxwell::Decode(word);
        if (opcode == Shader::Maxwell::Opcode::EXIT) continue;
        switch (opcode) {
#define INST(name, cute, encode) case Shader::Maxwell::Opcode::name: visitor.name(word); break;
#include "shader_recompiler/frontend/maxwell/maxwell.inc"
#undef INST
        }
    }
}
TEST_CASE("Welcome Tour split RGB bindless 2D samples preserve coordinates handle and output aliases", "[native-shader][welcome-menu]") {
    const u32 mask = GENERATE(1U, 3U, 7U, 15U);
    const u32 count = std::popcount(mask);
    const u32 second = count > 2 ? 38 : 255;
    const std::array<Native,2> input{{
        {{0x00007361,0x38000027,0x041e0000U | (mask << 8) | second,0x002f4400}},
        VertexTransform.back(),
    }};
    Shader::ObjectPool<IR::Inst> pool;
    IR::Block block{pool};
    TranslateScalarNative(input,block);
    unsigned samples=0;
    std::vector<std::pair<u32,u32>> copies;
    for(const auto& inst:block.Instructions()) {
        if(inst.GetOpcode()==IR::Opcode::BindlessImageSampleImplicitLod) {
            REQUIRE(inst.Flags<IR::TextureInstInfo>().type.Value()==Shader::TextureType::Color2D);
            REQUIRE(inst.Arg(0).Inst()->Arg(0).Reg()==IR::Reg{39});
            const auto* coords=inst.Arg(1).Inst();
            REQUIRE(coords->Arg(0).Inst()->Arg(0).Inst()->Arg(0).Reg()==IR::Reg{0});
            REQUIRE(coords->Arg(1).Inst()->Arg(0).Inst()->Arg(0).Reg()==IR::Reg{1});
            ++samples;
        }
        if(inst.GetOpcode()==IR::Opcode::SetRegister && inst.Arg(1).Inst()->GetOpcode()==IR::Opcode::GetRegister)
            copies.emplace_back(static_cast<u32>(inst.Arg(0).Reg()),static_cast<u32>(inst.Arg(1).Inst()->Arg(0).Reg()));
    }
    REQUIRE(samples==1);
    std::vector<std::pair<u32,u32>> expected;
    for(u32 i=0;i<count;++i) expected.emplace_back(i<2?i:second+i-2,250+i);
    REQUIRE(copies==expected);
    auto invalid=input;
    invalid[0].words[2]|=1U<<15; // Half results are not admitted by this path.
    REQUIRE_FALSE(Shader::Ampere::LowerToMaxwell(invalid));
}

TEST_CASE("Welcome Tour array depth samples retain mixed descriptor bank and reference", "[native-shader][welcome-menu]") {
    const bool mixed=GENERATE(false,true);
    const u32 lod=GENERATE(0U,1U);
    std::vector<Native> input;
    if(mixed) input.push_back({{0x03027b6f,0x00800800,0x000003ff,0}});
    input.push_back({{0x0a0d7b60,0xb1012400,0x041e41ffU | (lod<<23),0x00114400}});
    input.push_back(VertexTransform.back());
    Shader::ObjectPool<IR::Inst> pool;
    IR::Block block{pool};
    TranslateScalarNative(input,block);
    unsigned samples=0,handles=0;
    std::vector<std::pair<u32,u32>> copies;
    for(const auto& inst:block.Instructions()) {
        if(inst.GetOpcode()==IR::Opcode::GetCbufU32) {
            REQUIRE(inst.Arg(0).U32()==4);
            REQUIRE(inst.Arg(1).U32()==0x490);
            ++handles;
        }
        if(inst.GetOpcode()==(lod == 1
            ? (mixed?IR::Opcode::BindlessImageSampleDrefExplicitLod:IR::Opcode::BoundImageSampleDrefExplicitLod)
            : (mixed?IR::Opcode::BindlessImageSampleDrefImplicitLod:IR::Opcode::BoundImageSampleDrefImplicitLod))) {
            REQUIRE(inst.Flags<IR::TextureInstInfo>().type.Value()==Shader::TextureType::ColorArray2D);
            REQUIRE(inst.Flags<IR::TextureInstInfo>().is_depth.Value()==1);
            if(mixed) REQUIRE(inst.Arg(0).Inst()->Arg(0).Reg()==IR::Reg{248});
            else REQUIRE(inst.Arg(0).U32()==0x490);
            REQUIRE(inst.Arg(2).Inst()->Arg(0).Inst()->Arg(0).Reg()==IR::Reg{mixed?249U:1U});
            ++samples;
        }
        if(inst.GetOpcode()==IR::Opcode::SetRegister && inst.Arg(1).Inst()->GetOpcode()==IR::Opcode::GetRegister)
            copies.emplace_back(static_cast<u32>(inst.Arg(0).Reg()),static_cast<u32>(inst.Arg(1).Inst()->Arg(0).Reg()));
    }
    REQUIRE(samples==1);
    REQUIRE(handles==(mixed?1U:0U));
    REQUIRE(copies.size()==(mixed?4U:3U));
    REQUIRE(copies[0]==std::pair<u32,u32>{250,10});
    REQUIRE(copies[1]==std::pair<u32,u32>{251,11});
    REQUIRE(copies[2]==std::pair<u32,u32>{252,0});
    if(mixed) REQUIRE(copies[3]==std::pair<u32,u32>{249,1});
}
