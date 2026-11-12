"""Compile the real page-table update methods against recording cache/page backends."""
from pathlib import Path
import subprocess
root = Path(__file__).resolve().parents[1]
scratch = Path((root / '.local/headless-cache').read_text().strip())
source = (scratch / 'source/src/video_core/memory_manager.cpp').read_text()
start = source.index('GPUVAddr MemoryManager::PageTableOp(')
end = source.index('\nvoid MemoryManager::BindRasterizer', start)
fixture = r'''
#include <atomic>
#include <cassert>
#include <cstdint>
#include <map>
#include <mutex>
#include <utility>
#include <vector>
using u8=uint8_t; using u32=uint32_t; using u64=uint64_t;
using GPUVAddr=u64; using DAddr=u64; using PTEKind=int;
struct MemoryManager {
 enum class EntryType { Free, Mapped, Reserved };
 static constexpr u64 page_size=4096, big_page_size=65536, cpu_page_bits=12;
 struct Rasterizer { std::vector<std::pair<u64,u64>> ranges;
  void ModifyGPUMemory(u64, u64 address, u64 size) { ranges.emplace_back(address,size); }
 } cache;
 Rasterizer* rasterizer=&cache;
 u64 unique_identifier=1;
 std::atomic<u64> map_serial{};  // bumped by both page table operations (memory_manager.h)
 void NoteMapChange(GPUVAddr,size_t) { map_serial.fetch_add(1); }  // UB-178 change log
 std::map<std::pair<u64,bool>,EntryType> entries;
 EntryType GetEntry(u64 address,bool big) { return entries[{address,big}]; }
 void SetEntry(u64 address,EntryType type,bool big) { entries[{address,big}]=type; }
 u64 PageEntryIndex(u64 address,bool big) { return address/(big?big_page_size:page_size); }
 void SetBigPageContinuous(u64,bool) {}
 struct Table : std::map<u64,u32> { void ReserveRange(u64,u64) {} void Set(u64 i,u32 v) { (*this)[i]=v; } } page_table,big_page_table_dev;
 struct Memory { template<class T> T* GetPointer(u64) { return nullptr; } } memory;
 struct Kinds { void Map(u64,u64,int) {} } kind_map;
 std::mutex guard;
 GPUVAddr PageTableOp(GPUVAddr,DAddr,size_t,PTEKind,EntryType);
 GPUVAddr BigPageTableOp(GPUVAddr,DAddr,size_t,PTEKind,EntryType);
};
'''
fixture += source[start:end]
fixture += r'''
int main() {
 for (bool big : {false,true}) {
  MemoryManager m;
  const u64 page=big?m.big_page_size:m.page_size;
  const auto update=[&](u64 address,u64 size) {
   if(big) m.BigPageTableOp(address,0,size,0,MemoryManager::EntryType::Reserved);
   else m.PageTableOp(address,0,size,0,MemoryManager::EntryType::Reserved);
  };
  update(page,0); assert(m.cache.ranges.empty());
  m.SetEntry(3*page,MemoryManager::EntryType::Reserved,big);
  update(page,6*page);
  const std::vector<std::pair<u64,u64>> expected{{page,2*page},{4*page,3*page}};
  assert(m.cache.ranges==expected);
  m.cache.ranges.clear(); update(page,6*page); assert(m.cache.ranges.empty());
  update(20*page,10000*page);
  assert(m.cache.ranges.size()==1);
  assert(m.cache.ranges[0]==std::make_pair(20*page,10000*page));
 }
}
'''
out=root/'build/nx2-tests';out.mkdir(parents=True,exist_ok=True)
(out/'memory-ranges.cpp').write_text(fixture)
subprocess.run(['clang++-18','-std=c++20','-O1','-g','-fsanitize=address,undefined',str(out/'memory-ranges.cpp'),'-o',str(out/'memory-ranges')],check=True)
subprocess.run([str(out/'memory-ranges')],check=True)
print('Page-table cache notifications: empty, unchanged, disjoint and 10000-page runs PASS')
