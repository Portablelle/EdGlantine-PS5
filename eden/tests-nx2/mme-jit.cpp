#include <cassert>
#include <cstdio>
#include <cstring>
#include <random>
#include <unordered_map>
#include <sys/mman.h>
#include <unistd.h>
#include "video_core/macro_turing_jit.h"
namespace {
struct Map { int fd; size_t size; };
std::unordered_map<void*, Map> maps;
unsigned allocations=0, aliases=0;
bool fail_alloc=false, fail_alias=false;
}
namespace Common {
void* AllocateMemoryPages(size_t n) noexcept {
    ++allocations;
    if(fail_alloc) return nullptr;
    int fd=memfd_create("mme-test",MFD_CLOEXEC); assert(fd>=0 && ftruncate(fd,n)==0);
    void* p=mmap(nullptr,n,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0); assert(p!=MAP_FAILED);
    maps.emplace(p,Map{fd,n}); return p;
}
void* MapExecutableAlias(void* p,size_t n) noexcept {
    ++aliases;
    if(fail_alias) return nullptr;
    assert(maps.at(p).size==n);
    void* rx=mmap(nullptr,n,PROT_READ|PROT_EXEC,MAP_SHARED,maps.at(p).fd,0);
    assert(rx!=MAP_FAILED && rx!=p); return rx;
}
void FreeMemoryPages(void* p) noexcept {
    auto m=maps.at(p); assert(munmap(p,m.size)==0 && close(m.fd)==0); maps.erase(p);
}
}
using W=uint32_t;
using Code=std::vector<W>;
struct Inst {
    std::array<W,3> b{};
    void field(unsigned at,unsigned n,W value) {
        for(unsigned i=0;i<n;++i) { unsigned k=at+i; b[k/32]=(b[k/32]&~(1u<<(k%32)))|(((value>>i)&1u)<<(k%32)); }
    }
    Inst() { field(15,5,24);field(51,5,24);field(20,5,24);field(25,5,24);field(56,5,24);field(61,5,24); }
    void append(Code& c)const {c.insert(c.end(),{b[2],b[1],b[0]});}
};
void compare(const Code& c,W start,std::vector<W> params={},bool grow_fifo=false,bool refuse_emit=false) {
    Tegra::TuringMacroInterpreter interp;
    Tegra::TuringMacroInterpreter::DataRam ram{};
    std::vector<std::pair<W,W>> a,b;
    auto p=params,q=params;
    auto read=[](W address){return address^0xa5a5u;};
    auto emit_a=[&](W m,W v){a.emplace_back(m,v);if(grow_fifo)p.push_back(v+7);return !refuse_emit;};
    auto emit_b=[&](W m,W v){b.emplace_back(m,v);if(grow_fifo)q.push_back(v+7);return !refuse_emit;};
    auto x=interp.Execute(c,start,p,read,emit_a);
    Tegra::TuringMacroJit jit;
    assert(jit.Prepare(c,1));
    auto y=jit.Execute(start,q,ram,read,emit_b);
    assert(x.success==y.success && x.consumed==y.consumed && a==b && ram==interp.dram && p==q);
    if(!x.success) assert(x.error==y.error);
}
int main() {
    Code basic; Inst emit; emit.field(30,16,0x123);emit.field(82,3,5);emit.field(85,4,1);emit.field(0,1,1);
    emit.append(basic); Inst{}.append(basic);
    compare(basic,0);compare(basic,50);compare(basic,0,{},false,true);
    std::mt19937 rng(431);
    const W ops[]={0,1,2,3,4,5,6,8,9,10,11,12,13,14,15,17,18,19,20,21};
    for(unsigned i=0;i<250;++i) {
        Code c;Inst x=emit;x.field(10,5,ops[i%std::size(ops)]);x.field(20,5,28);x.field(25,5,29);x.append(c);Inst{}.append(c);
        compare(c,0,{W(rng()),W(rng())});compare(c,0,{});
    }
    // Callback may reallocate the FIFO; a following instruction must use its new pointer.
    Code fifo;Inst first=emit;first.field(0,1,0);first.append(fifo);
    Inst second=emit;second.field(20,5,28);second.append(fifo);Inst{}.append(fifo);compare(fifo,0,{},true);
    // Data RAM write/read and a register-read callback (op 22).
    Code mem;Inst w;w.field(10,5,31);w.field(20,5,25);w.field(30,16,3);w.field(25,5,26);w.field(66,16,77);w.append(mem);
    Inst rd=emit;rd.field(10,5,30);rd.field(20,5,25);rd.field(30,16,3);rd.append(mem);Inst{}.append(mem);compare(mem,0);
    Code reads;rd=emit;rd.field(10,5,22);rd.field(20,5,25);rd.append(reads);Inst{}.append(reads);compare(reads,0);
    Code branch;Inst jump;jump.field(10,5,24);jump.field(30,16,2);jump.append(branch);
    Inst skipped=emit;skipped.append(branch);emit.append(branch);Inst{}.append(branch);compare(branch,0);
    for(W count:{0u,1u,3u}) {
        Code loop;Inst begin;begin.field(10,5,23);begin.field(20,5,28);begin.field(30,16,2);begin.append(loop);
        Inst body=emit;body.field(0,1,0);body.append(loop);emit.append(loop);Inst{}.append(loop);compare(loop,0,{count});
    }
    // Force AutoGrow; execute an entry near the end through the relocated absolute table.
    Code big;Inst growth=emit;growth.field(0,1,0);for(unsigned i=0;i<16000;++i) growth.append(big);emit.append(big);Inst{}.append(big);
    unsigned before=allocations;compare(big,16000);assert(allocations>before+1);
    {
        Tegra::TuringMacroJit jit;assert(jit.Prepare(basic,1));
        before=allocations;assert(jit.Prepare(basic,1));assert(allocations==before);
        fail_alloc=true;assert(!jit.Prepare(basic,2));before=allocations;assert(!jit.Prepare(basic,2));assert(allocations==before);
        fail_alloc=false;assert(jit.Prepare(basic,3));
        fail_alias=true;assert(!jit.Prepare(basic,4));fail_alias=false;assert(jit.Prepare(basic,5));
    }
    assert(maps.empty());
    auto* allocator=Tegra::MmePs5Allocator();assert(!allocator->alloc(32u<<20));
    std::vector<uint8_t*> cap;for(unsigned i=0;i<4;++i){auto*p=allocator->alloc(16u<<20);assert(p);cap.push_back(p);}
    assert(!allocator->alloc(1u<<20));for(auto*p:cap)allocator->free(p);assert(maps.empty());
    std::puts("MME JIT: differential graphics/compute primitives, FIFO growth, callbacks, relocation, generations, allocation/alias failures and budgets PASS (Linux dual mappings)");
}
