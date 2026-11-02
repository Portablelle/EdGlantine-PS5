"""Exercise actual sparse-free production code with stale kernel ranges. Run on dedie."""
from pathlib import Path
import platform, subprocess
assert platform.system() == 'Linux', 'Run on dedie'
r=Path(__file__).resolve().parents[1]
s=(r/'src/guest_memory_service.inc').read_text()
a=s.index('void GuestMemoryFreed(');b=s.index('{',a);depth=1;end=b+1
while depth:
    depth+=(s[end]=='{')-(s[end]=='}');end+=1
function=s[a:end]
code=r'''
#include <algorithm>
#include <array>
#include <atomic>
#include <cassert>
#include <cstdint>
#include <limits>
#include <vector>
constexpr std::size_t SparseSlot=2*1024*1024;
constexpr std::uint8_t SlotZero=0;
struct SparseRange {
 std::atomic<std::uintptr_t> begin{0x10000000};
 std::uintptr_t end=0x10000000+4*SparseSlot;
 bool promote=true;
 std::array<std::uint8_t,4> state{1,1,1,1};
};
std::atomic<SparseRange*> guest_range;
struct { std::atomic<std::uint64_t> returns_free{0}; } counters;
std::vector<std::size_t> touched;
void LockSlot(SparseRange& r,std::size_t slot){assert(slot<r.state.size());touched.push_back(slot);}
std::uint8_t SlotState(SparseRange& r,std::size_t slot){return r.state.at(slot);}
void ReturnSlot(SparseRange& r,std::size_t slot){r.state.at(slot)=0;}
void UnlockSlot(SparseRange& r,std::size_t slot,std::uint8_t state){r.state.at(slot)=state;}
'''+function+r'''
int main(){
 SparseRange range;guest_range=&range;
 const auto check=[&](std::uint64_t offset,std::size_t size,std::vector<std::size_t> expected){
  touched.clear();range.state.fill(1);GuestMemoryFreed(offset,size);assert(touched==expected);
 };
 check(0,SparseSlot-1,{});
 check(1,3*SparseSlot,{1,2});
 check(0,4*SparseSlot,{0,1,2,3});
 check(3*SparseSlot,std::numeric_limits<std::size_t>::max(),{3});
 check(4*SparseSlot,8*SparseSlot,{});
 check(6*SparseSlot,2*SparseSlot,{});
 check(std::numeric_limits<std::uint64_t>::max(),std::numeric_limits<std::size_t>::max(),{});
 check(std::numeric_limits<std::uint64_t>::max()-SparseSlot,4*SparseSlot,{});
 range.promote=false;check(0,4*SparseSlot,{});
 guest_range=nullptr;check(0,4*SparseSlot,{});
}
'''
out=r/'build/guest-free-bounds';out.mkdir(parents=True,exist_ok=True)
p=out/'test.cpp';p.write_text(code)
subprocess.run(['c++','-std=c++20','-O1','-g','-fsanitize=address,undefined',str(p),'-o',str(out/'test')],check=True)
subprocess.run([str(out/'test')],check=True)
main=(r/'headless/main.cpp').read_text()
assert main.index('if (game && eden_game_is_switch2(guest))') < main.index('Core::System system;')
assert 'SetValue(Settings::MemoryLayout::Memory_12Gb)' in main[main.index('if (game && eden_game_is_switch2(guest))'):main.index('Core::System system;')]
print('PASS: actual sparse-free routine rejects stale/outside ranges and overflow, preserves partial slots; NX2 layout chosen before DeviceMemory construction (ASan/UBSan).')
