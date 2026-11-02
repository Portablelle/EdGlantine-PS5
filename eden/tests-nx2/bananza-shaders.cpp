// SPDX-License-Identifier: GPL-3.0-or-later
#include <array>
#include <bit>
#include <cassert>
#include <cmath>
#include <fstream>
#include <iostream>
#include <map>
#include "shader_recompiler/frontend/ampere/program_capture.h"
using namespace Shader::Ampere;
constexpr Instruction exit_instruction{{0x794d,0,0x03800000,0}};
bool predicate(const std::array<bool,8>& p,u32 code){return p[code&7]^bool(code&8);}
float half(u32 h){const float sign=h&0x8000?-1.f:1.f;const auto e=(h>>10)&31,m=h&1023;
 if(e==31)return m?NAN:sign*INFINITY;return sign*std::ldexp(e?float(1024+m):float(m),e?int(e)-25:-24);}
float lane(u32 value,u32 swizzle,u32 n,bool absolute,bool negative){
 float f=swizzle==1?std::bit_cast<float>(value):half(value>>((swizzle==3||(swizzle==0&&n==1))?16:0));
 if(absolute)f=std::fabs(f);return negative?-f:f;
}
bool compare(float a,float b,u32 condition){bool nan=std::isnan(a)||std::isnan(b);
 switch(condition){case 0:return false;case 1:return a<b;case 2:return a==b;case 3:return a<=b;case 4:return a>b;case 5:return !nan&&a!=b;case 6:return a>=b;case 7:return !nan;case 8:return nan;case 9:return nan||a<b;case 10:return nan||a==b;case 11:return nan||a<=b;case 12:return nan||a>b;case 13:return a!=b;case 14:return nan||a>=b;case 15:return true;}std::abort();}
bool combine(bool a,bool b,u32 op){return op==0?(a&&b):op==1?(a||b):(a!=b);}
void comparisons(){
 size_t checks=0;constexpr std::array<u32,8> values{0,0x80008000,0x3c003c00,0xbc003c00,0x7c007c00,0x7e003c00,0x00010000,0x3c007e00};
 for(u32 cond:{2U,5U,8U,14U})for(u32 bop=0;bop<3;++bop)for(u32 and_halves=0;and_halves<2;++and_halves)
 for(u32 sa=0;sa<4;++sa)for(u32 sb=0;sb<4;++sb)for(u32 modifiers=0;modifiers<16;++modifiers){
 Instruction input{{0x04002234,8U|(sb<<28)|((modifiers>>2)<<30),
 (bop<<5)|(and_halves<<7)|((modifiers&3)<<8)|(sa<<10)|(cond<<12)|(1U<<20),0}};
 const std::array code{input,exit_instruction};auto lowered=LowerToMaxwell(code);assert(lowered&&lowered.instructions.size()==2);
 const u64 word=lowered.instructions.front();auto bits=[&](u32 first,u32 count){return u32((word>>first)&((1ULL<<count)-1));};
 for(auto a:values)for(auto b:values)for(bool carry:{false,true})for(bool execute:{false,true}){
  std::array<bool,8> p{carry,true,execute,false,false,false,false,true},expected=p,actual=p;
  if(execute){bool low=combine(compare(lane(a,sa,0,modifiers&2,modifiers&1),lane(b,sb,0,modifiers&4,modifiers&8),cond),carry,bop);
   bool high=combine(compare(lane(a,sa,1,modifiers&2,modifiers&1),lane(b,sb,1,modifiers&4,modifiers&8),cond),carry,bop);
   expected[0]=and_halves?(low&&high):low;expected[1]=and_halves?!expected[0]:high;}
  if(predicate(p,bits(16,4))){
   const bool c=predicate(p,bits(39,4));
   bool low=combine(compare(lane(a,bits(47,2),0,bits(44,1),bits(43,1)),lane(b,bits(28,2),0,bits(30,1),bits(31,1)),bits(35,4)),c,bits(45,2));
   bool high=combine(compare(lane(a,bits(47,2),1,bits(44,1),bits(43,1)),lane(b,bits(28,2),1,bits(30,1),bits(31,1)),bits(35,4)),c,bits(45,2));
   const bool x=bits(49,1)?low&&high:low,y=bits(49,1)?!x:high;
   if(bits(3,3)!=7)actual[bits(3,3)]=x;if(bits(0,3)!=7)actual[bits(0,3)]=y;
  }
  assert(expected==actual);++checks;
 }
 }
 std::cout<<"PASS half predicate comparisons: "<<checks<<" cases, NaN/Inf/signed zero/subnormal, swizzles, modifiers, predicate alias and predication\n";
}
Instruction branch(u32 pc,u32 destination,u32 pred=7,u32 second=7){return {{0x947U|(pred<<12),(destination-pc-1)*16,second<<23,0}};}
Instruction setup(u32 pc,u32 destination,u32 token){return {{0x7945U|(token<<16),(destination-pc-1)*16,0x03800000,0}};}
Instruction sync(u32 token){return {{0x7941U|(token<<16),0,0x03800000,0}};}
Instruction mov(u32 reg,u32 value){return {{0x7802U|(reg<<16),value,0x00000f00,0}};}
std::array<u32,4> run(const LoweredProgram& program,bool first,bool second){
 std::map<s64,u32> addresses;auto address=[](u32 n){return 0x50+n*8+((n+1)/3)*8;};
 for(u32 n=0;n<program.instructions.size();++n)addresses[address(n)]=n;
 std::vector<std::pair<u32,u32>> stack;std::array<u32,4> regs{};std::array<bool,8> p{first,second,false,false,false,false,false,true};
 for(u32 pc=0,steps=0;pc<program.instructions.size();){assert(++steps<100);u64 word=program.instructions[pc];u32 op=word>>48;auto bits=[&](u32 lo,u32 count){return u32((word>>lo)&((1ULL<<count)-1));};
  if(!predicate(p,bits(16,4))){++pc;continue;}
  if(op==0xe290||op==0xe2a0||op==0xe240){s64 delta=static_cast<s64>(word<<20)>>40;u32 target=addresses.at(address(pc)+8+delta);
   if(op==0xe240){pc=target;continue;}stack.push_back({op,target});
  }else if(op==0xf0f8||op==0xe340){u32 token=op==0xf0f8?0xe290:0xe2a0;while(!stack.empty()&&stack.back().first!=token)stack.pop_back();assert(!stack.empty());auto target=stack.back().second;stack.pop_back();pc=target;continue;
  }else if((word&0xfff0000000000000ULL)==0x0100000000000000ULL){assert(bits(0,8)<4);regs[bits(0,8)]=bits(20,32);}
  else if(op==0xe300){assert(stack.empty());return regs;}
  else{std::cerr<<"Unexpected word "<<std::hex<<word<<'\n';std::abort();}++pc;
 }std::abort();
}
void barriers(){
 // B0/B1 remain live while BREAK cancels only B3, cleaned up at parent B2.
 for(u32 second:{1U,7U}){
 std::vector<Instruction> code{setup(0,16,0),setup(1,15,1),setup(2,14,2),setup(3,9,3),
 {{0x00030942,0,second<<23,0}},branch(5,11,0,second),mov(0,10),mov(1,20),sync(3),mov(0,30),branch(10,13),mov(0,40),mov(1,50),sync(2),sync(1),sync(0),exit_instruction};
 assert(VerifiedParentCancellation(code,4,3,2));auto lowered=LowerToMaxwell(code);assert(lowered);
 for(bool a:{false,true})for(bool b:{false,true}){auto regs=run(lowered,a,b);bool canceled=a&&(second==7||b);assert(regs[0]==(canceled?40:30));assert(regs[1]==(canceled?50:20));}
 auto bad=code;bad[4].words[0]^=1U<<16;assert(!VerifiedParentCancellation(bad,4,3,2));
 bad=code;bad[5].words[2]^=1U<<23;assert(!VerifiedParentCancellation(bad,4,3,2));
 bad=code;bad[11]=branch(11,6);assert(!VerifiedParentCancellation(bad,4,3,2));
 bad=code;bad[11]=sync(3);assert(!VerifiedParentCancellation(bad,4,3,2));
 // Malformed signed targets previously passed the relative comparisons and
 // indexed code[-1]; reject before touching any candidate instruction.
 bad=code;bad[3].words[1]=u32(-96);bad[5].words[1]=u32(-112);
 bad[5].words[2]=(second<<23)|0x3ffffU;
 assert(!VerifiedParentCancellation(bad,4,3,2));
 assert(!VerifiedParentCancellation(code,~0U,3,2));
 assert(!VerifiedParentCancellation(code,4,u32(code.size()),2));

 bad=code;bad[11]=branch(11,13,0);assert(!VerifiedParentCancellation(bad,4,3,2));
 }
 std::cout<<"PASS partial nested cancellation, both predicate conditions, preserved outer scopes, unsafe cleanup rejected\n";
}
int main(int argc,char**argv){
 for(int n=1;n<argc;++n){std::ifstream in(argv[n],std::ios::binary);assert(in);std::vector<Instruction> code;Instruction i;ProgramCaptureState state;bool complete=false;
  while(in.read(reinterpret_cast<char*>(&i),sizeof(i))){code.push_back(i);auto s=state.Observe(i,code.size()-1);assert(s!=ProgramCaptureState::Result::InvalidTarget);if(s==ProgramCaptureState::Result::Complete){complete=true;break;}}
  assert(complete);auto result=LowerToMaxwell(code,{},true);if(!result)std::cerr<<argv[n]<<" rejected at "<<std::hex<<result.error_offset<<": "<<result.error<<'\n';assert(result);std::cout<<"PASS captured shader "<<argv[n]<<" native_bytes="<<code.size()*16<<'\n';
 }
 comparisons();barriers();
}
