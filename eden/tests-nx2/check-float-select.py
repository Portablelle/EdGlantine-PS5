"""Reproduce dropped FSEL modifiers with real lowering and bit-exact execution.

Run on dedie; an optional binary argument contains captured 16-byte FSELs.
"""
from pathlib import Path
import importlib.util, platform, subprocess, tempfile, sys
assert platform.system() == 'Linux', 'Run on dedie'
r=Path(__file__).resolve().parents[1]
scratch=Path((r/'.local/headless-cache').read_text().strip())
source=scratch/'source/src'
code=r'''
#include <array>
#include <bit>
#include <cassert>
#include <cstring>
#include <fstream>
#include <iostream>
#include <vector>
#include "shader_recompiler/frontend/ampere/lower_to_maxwell.h"
#include "native_shader_policy.h"
using Shader::Ampere::Instruction;
u32 cb(u32 bank,u32 offset,u32 seed){return (bank*0x1020304U+offset*7919U+seed)^0xbf400000U;}
u32 mod(u32 x,bool absolute,bool negative){return (absolute?x&0x7fffffffU:x)^(negative?0x80000000U:0U);}
bool pred(const std::array<bool,8>& p,u32 code){return p[code&7]^bool(code&8);}
u32 execute(std::span<const u64> words,std::array<u32,256> regs,const std::array<bool,8>& p,u32 result,u32 seed){
 for(u64 word:words){
  auto bits=[&](u32 lo,u32 count){return u32((word>>lo)&((u64{1}<<count)-1));};
  if(!pred(p,bits(16,4)))continue;
  u32 value{},dest=bits(0,8);const auto mask=word&0xfff8000000000000ULL;
  if(mask==0x5c98000000000000ULL)value=regs[bits(20,8)];
  else if(mask==0x4c98000000000000ULL)value=cb(bits(34,5),bits(20,14)*4,seed);
  else if((word&0xfff0000000000000ULL)==0x0100000000000000ULL)value=bits(20,32);
  else if((word&0xfc00000000000000ULL)==0x0400000000000000ULL){
   const auto a=regs[bits(8,8)],b=bits(20,32),op=bits(53,2);
   value=op==0?(a&b):op==1?(a|b):(a^b);
  }else if(mask==0x5ca0000000000000ULL)value=pred(p,bits(39,4))?regs[bits(8,8)]:regs[bits(20,8)];
  else if((word&0xfff0000000000000ULL)==0xe300000000000000ULL)break;
  else {std::cerr<<"Unmodelled instruction "<<std::hex<<word<<'\n';std::abort();}
  if(dest!=255)regs[dest]=value;
 }
 return regs[result];
}
int main(int argc,char**argv){
 constexpr Instruction exit{{0x0000794d,0,0x03800000,0x000fea00}};
 std::vector<Instruction> cases;
 if(argc>1){
  std::ifstream f(argv[1],std::ios::binary|std::ios::ate);
  if(!f || f.tellg()<=0 || f.tellg()%std::streamoff(sizeof(Instruction))) return 2;
  const auto bytes=f.tellg();cases.resize(static_cast<size_t>(bytes)/sizeof(Instruction));
  f.seekg(0);if(!f.read(reinterpret_cast<char*>(cases.data()),bytes)) return 2;
 }
 const auto captured=cases.size();
 // Captured sign-selection idiom followed by all source modifier combinations.
 cases.push_back({{0x06067208,0x80000007,0x00800000,0x000fe200}});
 for(u32 opcode:{0x208U,0x808U,0xa08U,0x207U})for(u32 modifiers=0;modifiers<16;++modifiers){
  Instruction i{{opcode|0x7000U|(6U<<16)|(8U<<24),opcode==0x208||opcode==0x207?9U:opcode==0x808?0x3f800000U:0x00c00400U,1U<<23,0}};
  i.words[2]|=(modifiers&3)<<8; // A negate/absolute
  if(opcode!=0x808)i.words[1]|=((modifiers>>2)&3)<<30; // B absolute/negate
  cases.push_back(i);
 }
 size_t old_failures{},fixed_failures{},checks{};
 const std::array<u32,8> values{0,0x80000000,0x3f800000,0xbf800000,0x7f800000,0xff800000,0x7fc12345,0xffc12345};
 for(const auto& i:cases){
  const std::array input{i,exit};
  const auto old=Shader::Ampere::LowerToMaxwell(input,{},true,false);
  const auto fixed=Shader::Ampere::LowerToMaxwell(input,{},true,true);
  assert(old&&fixed);
  // Integer SEL must keep its original bitwise behavior.
  if(i.Bits(0,12)==0x207)assert(old.instructions==fixed.instructions);
  for(u32 seed:values)for(bool condition:{false,true}){
   std::array<u32,256> regs{};for(u32 n=0;n<255;++n)regs[n]=(seed+n*0x1020304U);
   regs[8]=seed;regs[9]=seed^0x80000000U;
   std::array<bool,8> p{};p.fill(condition);p[7]=true;
   const u32 form=i.Bits(9,3),opcode=i.Bits(0,12);const bool floating=opcode!=0x207;
   u32 a=regs[i.Bits(24,8)],b=form==4?i.words[1]:form==5?cb(i.Bits(54,5),i.Bits(38,16),seed):regs[i.Bits(32,8)];
   if(floating){a=mod(a,i.Bits(73,1),i.Bits(72,1));if(form!=4)b=mod(b,i.Bits(62,1),i.Bits(63,1));}
   const u32 dest=i.Bits(16,8);
   const u32 expected=pred(p,i.Bits(12,4))?(pred(p,i.Bits(87,4))?a:b):regs[dest];
   old_failures+=execute(old.instructions,regs,p,dest,seed)!=expected;
   fixed_failures+=execute(fixed.instructions,regs,p,dest,seed)!=expected;++checks;
  }
 }
 assert(old_failures>0&&fixed_failures==0);
 using namespace Eden::NativeShaderPolicy;
 static_assert(CorrectFloatSelect(0x0400A3A01EE4C000ULL));
 static_assert(!CorrectFloatSelect(0x040057C02159A000ULL));
 static_assert(CacheTag(0x0400A3A01EE4C000ULL)==0x100U);
 static_assert(CacheTag(0x040057C02159A000ULL)==0U);
 std::cout<<"PASS captured="<<captured<<" cases="<<cases.size()<<" checks="<<checks<<" baseline_mismatches="<<old_failures<<" fixed_mismatches="<<fixed_failures<<'\n';
}
'''
with tempfile.TemporaryDirectory(prefix='nx2-fsel-') as tmp:
 t=Path(tmp);rel=Path('shader_recompiler/frontend/ampere/lower_to_maxwell.h');(t/rel).parent.mkdir(parents=True)
 (t/rel).write_text((source/rel).read_text());(t/'check.cpp').write_text(code)
 subprocess.run(['c++','-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer','-I'+str(t),'-I'+str(source),'-I'+str(r/'headless'),str(t/'check.cpp'),'-o',str(t/'check')],check=True)
 for filename,data in [('empty.bin',b''),('truncated.bin',b'bad')]:
  fixture=t/filename;fixture.write_bytes(data)
  assert subprocess.run([str(t/'check'),str(fixture)]).returncode==2
 assert subprocess.run([str(t/'check'),str(t/'missing.bin')]).returncode==2
 subprocess.run([str(t/'check'),*sys.argv[1:]],check=True)
