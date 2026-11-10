"""UB-058: execute production Ampere lowering and native translator over 32 lanes.

Usage: python3 tests-nx2/check-native-hmma-lowering.py [--source-only] [SOURCE_DIR]
SOURCE_DIR contains src/; defaults to the prepared headless cache. Linux/dedie only
for C++ (clang++-18); no Vulkan needed. --source-only checks wiring/encoding only,
NOT numerical behavior. Negative control: the SAME full command against prepared
main WITHOUT 99zzzz5 must fail because lowering emits hundreds of instructions.
The translator is extracted verbatim, with a small evaluating IR backend; f32 FMA
and f16 conversions use host arithmetic. Reference uses independent matrix indexing.
Our effective main already translates SHFL to a single shuffle, unlike upstream's
historical 96/48 IR shuffles: verify 32/16 here, do not assert that historical count.
"""
from pathlib import Path
import os
import platform
import re
import subprocess
import sys

args = [a for a in sys.argv[1:] if a != '--source-only']
source_only = '--source-only' in sys.argv[1:]
root = Path(__file__).resolve().parents[1]
source = (Path(args[0]).resolve() if args else
          Path((root / '.local/headless-cache').read_text().strip()) / 'source')
src = source / 'src'
shader = src / 'shader_recompiler'
translator = shader / 'frontend/maxwell/translate/impl/hmma_native.cpp'
inc = (shader / 'frontend/maxwell/maxwell.inc').read_text()
patterns = re.findall(r'INST\(\s*(\w+),\s*"[^"]*",\s*"([01 -]+)"', inc)
assert all(len(mask.replace(' ', '')) == 16 for _, mask in patterns)
matches = [name for name, mask in patterns
           if all(a == '-' or a == b for a, b in zip(mask.replace(' ', ''), f'{0x5d38:016b}'))]

if source_only:
    assert matches == ['HMMA_NATIVE'], matches
    assert translator.exists()
    assert 'frontend/maxwell/translate/impl/hmma_native.cpp' in (shader / 'CMakeLists.txt').read_text()
    for path, dispatch in [('translate/impl/impl.h', 'void name(u64 insn);'),
                           ('translate/translate.cpp', 'visitor.name(insn);')]:
        text = (shader / 'frontend/maxwell' / path).read_text()
        assert dispatch in text and '#include "shader_recompiler/frontend/maxwell/maxwell.inc"' in text
    lower = (shader / 'frontend/ampere/lower_to_maxwell.h').read_text()
    case = lower[lower.index('        case 0x23c:'):lower.index('        case 0x226:')]
    assert case.index('EDEN_NATIVE_DISABLE_TENSOR') < case.index('native half matrix multiply mode')
    assert case.index('native half matrix multiply mode') < case.index('if (hmma_native)') < case.index('const auto add =')
    print('HMMA source wiring and collision checks PASS (C++ behavior not run)')
    sys.exit(0)

assert platform.system() == 'Linux', 'Run C++ fixture on Linux/dedie only'
out = root / 'build/nx2-tests/native-hmma-lowering'
out.mkdir(parents=True, exist_ok=True)
# Keep all production lowering, including validation and the environment toggle.
code = r'''
#include <cassert>
#include <bit>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <random>
#include "shader_recompiler/frontend/ampere/lower_to_maxwell.h"
using namespace Shader::Ampere;
void check(bool ok, const char* why) { if (!ok) { std::fprintf(stderr, "FAIL: %s\n", why); std::exit(1); } }
Instruction instruction(u32 depth, u32 dest=0, u32 a=8, u32 b=16, u32 c=24) {
    return {{0x23c | (7u << 12) | (dest << 16) | (a << 24), b,
             c | (depth == 16 ? 0x800u : 0u), 0}};
}
LoweredProgram lower_one(Instruction insn) {
    const std::array code{insn, Instruction{{0x794d,0,0x03800000,0}}};
    auto result=LowerToMaxwell(code);
    if(result) result.instructions.resize(result.source_instruction_offsets.at(1));
    return result;
}
float half_round(float x) { return float(_Float16(x)); }
u32 pack(float a, float b) {
    return u32(std::bit_cast<u16>(_Float16(a))) | (u32(std::bit_cast<u16>(_Float16(b))) << 16);
}
float unpack(u32 x, u32 h) { return float(std::bit_cast<_Float16>(u16(x >> (h*16)))); }
// This backend evaluates an IR value over the entire warp. No lane formula from
// HMMA is duplicated here: those formulas execute in the production translator.
namespace Shader::IR {
enum class Reg : u64 {};
struct U32 { std::array<u32,32> v{}; };
struct F32 { std::array<float,32> v{}; };
struct Pair { F32 v[2]; };
struct IREmitter {
    int shuffles=0, fmas=0, rounds=0;
    U32 Imm32(int x) { return Imm32(u32(x)); }
    U32 Imm32(u32 x) { U32 r; r.v.fill(x); return r; }
    F32 Imm32(float x) { F32 r; r.v.fill(x); return r; }
    U32 LaneId() { U32 r; for (u32 i=0;i<32;++i) r.v[i]=i; return r; }
    U32 BitwiseAnd(U32 a,U32 b) { for(int i=0;i<32;++i) a.v[i]&=b.v[i]; return a; }
    U32 BitwiseOr(U32 a,U32 b) { for(int i=0;i<32;++i) a.v[i]|=b.v[i]; return a; }
    U32 ShiftLeftLogical(U32 a,U32 b) { for(int i=0;i<32;++i) a.v[i]<<=b.v[i]; return a; }
    U32 IAdd(U32 a,U32 b) { for(int i=0;i<32;++i) a.v[i]+=b.v[i]; return a; }
    U32 ShuffleIndex(U32 a,U32 index,U32 clamp,U32 segment) {
        ++shuffles; U32 r;
        for(int i=0;i<32;++i) {
            check(clamp.v[i]==31 && segment.v[i]==0 && index.v[i]<32, "shuffle mask/index");
            r.v[i]=a.v[index.v[i]];
        }
        return r;
    }
    Pair UnpackHalf2x16(U32 a) {
        Pair r; for(int h=0;h<2;++h) for(int i=0;i<32;++i) r.v[h].v[i]=unpack(a.v[i],h); return r;
    }
    F32 CompositeExtract(Pair a,u32 h) { return a.v[h]; }
    Pair CompositeConstruct(F32 a,F32 b) { return {{a,b}}; }
    F32 FPConvert(u32 bits,F32 a) {
        if(bits==16) { ++rounds; for(auto& x:a.v) x=half_round(x); }
        else check(bits==32,"FPConvert width");
        return a;
    }
    F32 FPFma(F32 a,F32 b,F32 c) {
        ++fmas; for(int i=0;i<32;++i) c.v[i]=std::fma(a.v[i],b.v[i],c.v[i]); return c;
    }
    U32 PackHalf2x16(Pair a) {
        U32 r; for(int i=0;i<32;++i) r.v[i]=pack(a.v[0].v[i],a.v[1].v[i]); return r;
    }
};
}
// Only bit extraction is substituted; the production union layout and fields
// remain verbatim, so encoded operand/depth mistakes affect the test.
template<int Offset,int Width,class T> struct BitField {
    u64 raw;
    T Value() const { return static_cast<T>((raw >> Offset) & ((u64{1} << Width)-1)); }
    operator T() const { return Value(); }
};
namespace Shader::Maxwell {
struct TranslatorVisitor {
    IR::IREmitter ir;
    std::array<IR::U32,256> regs{};
    IR::U32 X(IR::Reg r) { return regs[static_cast<u32>(r)]; }
    void X(IR::Reg r,IR::U32 v) { regs[static_cast<u32>(r)]=v; }
    void HMMA_NATIVE(u64 insn);
};
}
'''
# On main keep the fixture compilable: fail first on lowering behavior, never on
# an absent symbol/include. The no-op translator would also fail the shuffle count.
code += ('\n'.join(line for line in translator.read_text().splitlines()
                   if not line.startswith('#include')) if translator.exists() else
         'void Shader::Maxwell::TranslatorVisitor::HMMA_NATIVE(u64) {}\n')
code += r'''
int main() {
    const bool expansion=std::getenv("EDEN_NX2_HMMA_NATIVE") != nullptr;
    const bool disabled=std::getenv("EDEN_NATIVE_DISABLE_TENSOR") != nullptr;
    std::mt19937 rng(58); std::uniform_real_distribution<float> dist(-2,2);
    for(u32 depth:{8u,16u}) {
        auto insn=instruction(depth);
        auto lowered=lower_one(insn);
        if(disabled) { check(!lowered,"tensor disable must reject"); continue; }
        check(bool(lowered),"valid HMMA rejected");
        // Shared validation must apply to both paths.
        for(auto bad:{instruction(depth,1),instruction(depth,0,9),instruction(depth,0,8,16,25),
                      instruction(depth,240),instruction(depth,0,240),instruction(depth,0,8,240)}) {
            check(!lower_one(bad),"invalid register accepted");
        }
        auto bad=instruction(depth); bad.words[0]^=1u<<12;
        check(!lower_one(bad),"predicated HMMA accepted");
        bad=instruction(depth); bad.words[2]|=0x1000;
        check(!lower_one(bad),"invalid mode accepted");
        if(expansion) {
            check(lowered.instructions.size()>100,"toggle must keep long Maxwell expansion");
            int shuffles=0, fmas=0;
            for(auto op:lowered.instructions) {
                shuffles+=(op>>48)==0xef17;  // SHFL with PT destination
                fmas+=((op>>52)==0x598);
                check((op & 0xfff8000000000000ULL)!=0x5d38000000000000ULL,"toggle emitted native opcode");
            }
            check(shuffles==int(depth*2),"software SHFL count");
            check(fmas==int(depth*4),"software FMA count");
            continue;
        }
        check(lowered.instructions.size()==1,"default HMMA still emits long Maxwell expansion");
        const u64 op=lowered.instructions[0];
        check((op & 0xfff8000000000000ULL)==0x5d38000000000000ULL,"wrong pseudo opcode");
        for(int iter=0;iter<100;++iter) for(bool zero:{false,true}) for(bool alias:{false,true}) {
            // D aliases each source in turn, including C. Writes must follow all reads.
            u32 dest=alias ? (iter%3==0 ? 8 : iter%3==1 ? 16 : 24) : 0;
            insn=instruction(depth,dest,8,16,zero?255:24);
            lowered=lower_one(insn);
            check(bool(lowered) && lowered.instructions.size()==1,"alias/zero lowering");
            float A[16][16],B[16][8],C[16][8];
            for(auto& row:A) for(auto& x:row) x=half_round(dist(rng));
            for(auto& row:B) for(auto& x:row) x=half_round(dist(rng));
            for(auto& row:C) for(auto& x:row) x=zero?0:half_round(dist(rng));
            Shader::Maxwell::TranslatorVisitor v;
            for(u32 t=0;t<32;++t) {
                u32 g=t/4,q=t%4;
                for(u32 chunk=0;chunk<depth/8;++chunk) {
                    for(u32 row=0;row<2;++row)
                        v.regs[8+chunk*2+row].v[t]=pack(A[g+row*8][chunk*8+q*2],A[g+row*8][chunk*8+q*2+1]);
                    v.regs[16+chunk].v[t]=pack(B[chunk*8+q*2][g],B[chunk*8+q*2+1][g]);
                }
                for(u32 row=0;row<2;++row) v.regs[24+row].v[t]=pack(C[g+row*8][q*2],C[g+row*8][q*2+1]);
            }
            v.HMMA_NATIVE(lowered.instructions[0]);
            check(v.ir.shuffles==int(depth*2),"native must emit 32/16 shuffles");
            check(v.ir.fmas==int(depth*4),"native FMA count");
            check(v.ir.rounds==int(depth/8*4),"round once per eight products");
            for(u32 t=0;t<32;++t) for(u32 r=0;r<2;++r) for(u32 c=0;c<2;++c) {
                u32 row=t/4+8*r,col=(t%4)*2+c; float ref=C[row][col];
                for(u32 k=0;k<depth;++k) {
                    ref=std::fma(A[row][k],B[k][col],ref);
                    if(k%8==7) ref=half_round(ref);
                }
                check(unpack(v.regs[dest+r].v[t],c)==ref,"matrix product/order/f16 rounding differs");
            }
        }

    }
    std::puts(disabled ? "Tensor disable PASS" : expansion ? "Software HMMA fallback PASS" : "Native HMMA behavior PASS");
}
'''
(out / 'hmma.cpp').write_text(code)
exe = out / 'hmma'
subprocess.run(['clang++-18', '-std=c++20', '-O1', '-g', '-ffp-contract=off',
                '-fsanitize=address,undefined', '-I' + str(src), str(out / 'hmma.cpp'),
                '-o', str(exe)], check=True)
env = os.environ.copy()
env.pop('EDEN_NX2_HMMA_NATIVE', None)
env.pop('EDEN_NATIVE_DISABLE_TENSOR', None)
for extra in ({}, {'EDEN_NX2_HMMA_NATIVE': '0'}, {'EDEN_NATIVE_DISABLE_TENSOR': '1'}):
    subprocess.run([str(exe)], env=env | extra, check=True)
