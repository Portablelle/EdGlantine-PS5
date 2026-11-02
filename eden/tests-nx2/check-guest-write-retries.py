"""Run on dedie: real fault handler, repeated protected-page writes and no-progress guard."""
from pathlib import Path
import platform, subprocess, sys
assert platform.system() == 'Linux', 'Run on dedie'
root=Path(__file__).resolve().parents[1]
current=(root/'src/guest_memory_service.inc').read_text()
baseline=Path(sys.argv[1]).read_text() if len(sys.argv)>1 else subprocess.check_output(
 ['git','show','HEAD:eden/src/guest_memory_service.inc'],cwd=root,text=True)
def extract(s):
 a=s.index('bool HandleGuestWriteFault('); b=s.index('\nnamespace {\nstruct sigaction service_previous',a)
 return s[a:b]
fixture=r'''
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <csignal>
#include <sys/mman.h>
#include <unistd.h>
constexpr size_t SparseSlot=2*1024*1024;
enum {SlotZero=0,SlotOwn=1,SlotShared=2,SlotFine=3};
struct SparseRange { std::atomic<uintptr_t> begin{0}; unsigned state=SlotZero; bool locked=false; } range;
std::atomic<uintptr_t> probe_expected{0}; std::atomic<bool> probe_mismatch{false};
struct { std::atomic<unsigned> faults{0},promotions{0},failures{0}; } counters;
bool simulate_wait=false, fail_promote=false;
SparseRange* WriteRangeOf(uintptr_t a){return a>=range.begin && a<range.begin+SparseSlot ? &range:nullptr;}
bool LockSlot(SparseRange& r,size_t slot,bool){assert(slot==0&&!r.locked);r.locked=true;bool waited=simulate_wait;simulate_wait=false;return waited;}
unsigned SlotState(SparseRange& r,size_t){return r.state;}
void UnlockSlot(SparseRange& r,size_t,unsigned state){assert(r.locked);r.state=state;r.locked=false;}
bool PromoteZero(SparseRange& r,size_t){if(fail_promote)return false;return mprotect((void*)r.begin.load(),SparseSlot,PROT_READ|PROT_WRITE)==0;}
bool PromoteShared(SparseRange& r,size_t s){return PromoteZero(r,s);}
bool PromoteFine(SparseRange& r,size_t s){return PromoteZero(r,s);}
void Note(const char*){}
'''
main=r'''
volatile sig_atomic_t signals=0;
void Handler(int,siginfo_t* info,void*){
 ++signals;
 if(!HandleGuestWriteFault(info->si_addr)) _exit(77);
}
int main(int argc,char**){
 void* p=mmap(nullptr,SparseSlot,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
 assert(p!=MAP_FAILED);range.begin=(uintptr_t)p;
 struct sigaction action{};action.sa_sigaction=Handler;action.sa_flags=SA_SIGINFO;
 sigemptyset(&action.sa_mask);assert(sigaction(SIGSEGV,&action,nullptr)==0);
 auto* word=(volatile uint64_t*)p;
 for(unsigned n=0;n<100;++n){
  range.state=SlotZero;
  assert(mprotect(p,SparseSlot,PROT_READ)==0);
  *word=n+1;
  assert(*word==n+1&&range.state==SlotOwn&&!range.locked);
 }
 assert(signals==100);
 // A real fault with no state transition must still be rejected and unlocked.
 for(unsigned n=0;n<16;++n)assert(HandleGuestWriteFault(p));
 assert(!HandleGuestWriteFault(p)&&!range.locked);
 // Repeated waits are progress elsewhere, not sixteen failed own-slot retries.
 for(unsigned n=0;n<100;++n){simulate_wait=true;assert(HandleGuestWriteFault(p));}
 for(unsigned state:{SlotShared,SlotFine}){
  range.state=state;assert(HandleGuestWriteFault(p));assert(range.state==SlotOwn);
 }
 range.state=SlotZero;fail_promote=true;
 assert(!HandleGuestWriteFault(p)&&range.state==SlotZero&&!range.locked);
 assert(!HandleGuestWriteFault(nullptr));
 assert(munmap(p,SparseSlot)==0);
 puts("PASS: 100 real same-address faults, no-progress rejection, waits, shared/fine and failure unlocks");
}
'''
fixture='#include <initializer_list>\n'+fixture
out=root/'build/guest-write-retries';out.mkdir(parents=True,exist_ok=True)
for label,source in [('baseline',baseline),('corrected',current)]:
 p=out/(label+'.cpp');p.write_text(fixture+extract(source)+main)
 binary=out/label
 subprocess.run(['c++','-std=c++20','-O1','-g','-fsanitize=undefined',str(p),'-o',str(binary)],check=True)
 result=subprocess.run([str(binary)])
 expected=77 if label=='baseline' else 0
 assert result.returncode==expected,(label,result.returncode,expected)
 if label=='baseline':print('REPRODUCED: original rejects the 17th valid same-address promotion',flush=True)
