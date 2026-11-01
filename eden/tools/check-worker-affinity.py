#!/usr/bin/env python3
"""Exercise production six-core topology and affinity with mocked native APIs."""
from pathlib import Path
import subprocess,tempfile
root=Path(__file__).resolve().parents[1]
s=(root/'headless/performance.cpp').read_text()
registration=s.split('void RegisterWorker(const char* name) {',1)[1].split('void SampleCoreCpu',1)[0]
assert registration.index('if (i >= CpuPolicy::PinnedWorkers) PlaceSecondary(name);') < registration.index('cpuset_t affinity{};')
assert 'if (result == 0) PinWorker(i, affinity);' in registration
a=s.index('std::array<unsigned, CpuPolicy::PinnedWorkers> worker_cpus{};')
body=s[a:s.index('\n#endif',a)]
secondary=s.split('void SetSecondaryPlacement(bool enabled) {\n#ifdef PS5_NATIVE\n',1)[1].split('\n#else',1)[0]
code=r'''
#include "cpu_policy.h"
#include <algorithm>
#include <atomic>
#include <cstring>
#include <cstdlib>
#include <cstdio>
#include <cerrno>
#include <stdexcept>
#include <cassert>
using cpuset_t=uint64_t;
namespace CpuPolicy=Eden::CpuPolicy;
#undef CPU_ISSET
#undef CPU_SET
#define CPU_ISSET(c,p) ((*(p)>>(c))&1)
#define CPU_SET(c,p) (*(p)|=uint64_t(1)<<(c))
#define CPU_LEVEL_WHICH 1
#define CPU_WHICH_TID 1
static uint64_t current, allowed_mask, fail_mask, ignore_mask;
static unsigned max_leaf, level_type, mock_apics[64], sets;
static bool fail_restore;
static constexpr std::array names{"CPUCore_0","CPUCore_1","CPUCore_2","CPUCore_3","CPUCore_4","CPUCore_5","GPU"};
static unsigned __get_cpuid_max(unsigned,void*) {return max_leaf;}
#define __cpuid_count(l,s,a,b,c,d) do {a=1;b=2;c=level_type<<8;d=mock_apics[__builtin_ctzll(current)];} while(0)
static int cpuset_getaffinity(int,int,int,size_t n,cpuset_t* out){assert(n==8);*out=current;return 0;}
static int cpuset_setaffinity(int,int,int,size_t n,const cpuset_t* in){
 assert(n==8 && *in && !(*in&~allowed_mask));++sets;
 if(*in==fail_mask || (fail_restore && *in==allowed_mask)) {errno=22;return -1;}
 if(*in!=ignore_mask)current=*in;
 return 0;
}
'''+body+'\nvoid SetSecondaryPlacement(bool enabled) {\n'+secondary+'\n}\n'+r'''
void reset(uint64_t mask=0x1fff){
 current=allowed_mask=mask;fail_mask=ignore_mask=0;fail_restore=false;
 max_leaf=0xb;level_type=1;sets=0;
 worker_topology_checked=false;worker_topology_ready=false;placement_secondary=false;
 for(unsigned i=0;i<64;++i)mock_apics[i]=i;
}
int main(){
 unsetenv("EDEN_NX2_SPLIT");
 constexpr unsigned expected[]={256,96,96,96,96,96};unsigned total=0;
 for(unsigned i=0;i<6;++i){assert(CpuPolicy::JitBytes(i)==expected[i]*1024u*1024u);total+=CpuPolicy::JitBytes(i);}
 assert(total==736u*1024u*1024u && CpuPolicy::JitBytes(6)==16u*1024u*1024u);
 assert(CpuPolicy::JitBytes(size_t(-1))==16u*1024u*1024u);
 reset();CheckWorkerTopology();assert(worker_topology_ready && current==allowed_mask);
 assert((worker_cpus==std::array<unsigned,7>{0,2,4,6,8,10,12}));assert(secondary_cpus==0xaaa);
 SetSecondaryPlacement(true);assert(current==0xaaa && placement_secondary);
 // Every primary can leave the auxiliary mask it inherited, including guest 5 and GPU.
 for(unsigned i=0;i<7;++i){current=0xaaa;cpuset_t inherited=current;PinWorker(i,inherited);assert(current==(1ULL<<(2*i)) && inherited==current);}
 current=0xaaa;SetSecondaryPlacement(false);assert(current==allowed_mask && !placement_secondary);
 current=3;unsigned before=sets;CheckWorkerTopology();assert(current==3 && sets==before);
 reset(0xffff);CheckWorkerTopology();assert(worker_topology_ready && secondary_cpus==0xc000); // spare physical core
 reset(0x3fff);CheckWorkerTopology();assert(worker_topology_ready && secondary_cpus==0xaaa); // exclude GPU sibling 13
 reset();for(unsigned i=0;i<7;++i)mock_apics[i]=i*2;for(unsigned i=7;i<13;++i)mock_apics[i]=(i-7)*2+1;
 CheckWorkerTopology();assert(worker_topology_ready && (worker_cpus==std::array<unsigned,7>{0,1,2,3,4,5,6}));assert(secondary_cpus==0x1f80);
 reset(0x5554);CheckWorkerTopology();assert(worker_topology_ready && secondary_cpus==0); // seven allowed primaries, no auxiliary CPU
 reset(0xfff);CheckWorkerTopology();assert(!worker_topology_ready && current==allowed_mask && secondary_cpus==0);
 reset();for(auto&apic:mock_apics)apic=5;CheckWorkerTopology();assert(!worker_topology_ready && current==allowed_mask);
 reset();level_type=0;CheckWorkerTopology();assert(!worker_topology_ready && current==allowed_mask);
 reset();max_leaf=0;CheckWorkerTopology();assert(!worker_topology_ready && sets==0);
 reset();fail_mask=4;CheckWorkerTopology();assert(!worker_topology_ready && current==allowed_mask);
 reset();ignore_mask=4;CheckWorkerTopology();assert(!worker_topology_ready && current==allowed_mask);
 reset();CheckWorkerTopology();fail_mask=1ULL<<10;cpuset_t original=current;PinWorker(5,original);assert(current==allowed_mask && original==current);
 current=0xaaa;original=current;PinWorker(5,original);assert(current==allowed_mask && original==current);
 fail_mask=0;ignore_mask=1ULL<<12;PinWorker(6,original);assert(current==allowed_mask && original==current);
 ignore_mask=0;PinWorker(7,original);assert(current==allowed_mask);
 reset();fail_restore=true;bool threw=false;try{CheckWorkerTopology();}catch(const std::runtime_error&){threw=true;}assert(threw);
 reset();CheckWorkerTopology();ignore_mask=0xaaa;SetSecondaryPlacement(true);assert(!placement_secondary && current==allowed_mask);
 reset();CheckWorkerTopology();SetSecondaryPlacement(true);current=1ULL<<12;PlaceSecondary("VSyncThread");assert(current==0xaaa);
 setenv("EDEN_NX2_SPLIT","1",1);
 reset(0xffff);CheckWorkerTopology();assert(split_back_cpus==0x4000 && secondary_cpus==0xaaa);
 SetSecondaryPlacement(true);PlaceSecondary("GPUBack");assert(current==0x4000);
 PlaceSecondary("VSyncThread");assert(current==0xaaa);
 reset(0x3fff);CheckWorkerTopology();assert(split_back_cpus==2 && !(secondary_cpus&(1ULL<<13)));
 reset(0xfff);CheckWorkerTopology();assert(!worker_topology_ready && !split_back_cpus && !secondary_cpus);
 unsetenv("EDEN_NX2_SPLIT");
}
'''
with tempfile.TemporaryDirectory() as tmp:
    exe=Path(tmp)/'affinity'
    subprocess.run(['c++','-std=c++20','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I'+str(root/'headless'),'-x','c++','-','-o',str(exe)],input=code,text=True,check=True)
    subprocess.run([str(exe)],check=True)
print('Six-core ARM cache budgets and seven-worker topology: permutations, inherited masks, GPU sibling exclusion, spare cores, unknown/insufficient topology, refusals and verified restoration PASS (mocked native APIs)')
