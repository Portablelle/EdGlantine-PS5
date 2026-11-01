// Runs the actual Scheduler batch methods against an ordered GPU command model.
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <functional>
#include <map>
#include <random>
#include <span>
#include <vector>
#include "video_core/native_snapshot_batch.h"
#include "video_core/native_draw_indirect.h"
using u64 = std::uint64_t;
using VkBuffer = u64;
struct VkBufferCopy { u64 srcOffset, dstOffset, size; };
struct BufferCopy {u64 src_offset, dst_offset, size;};
struct VkMemoryBarrier { int type; const void* next; int src, dst; };
constexpr int VK_STRUCTURE_TYPE_MEMORY_BARRIER=1, VK_ACCESS_MEMORY_WRITE_BIT=1,
 VK_ACCESS_TRANSFER_READ_BIT=2, VK_ACCESS_TRANSFER_WRITE_BIT=4, VK_ACCESS_MEMORY_READ_BIT=8,
 VK_PIPELINE_STAGE_ALL_COMMANDS_BIT=1, VK_PIPELINE_STAGE_TRANSFER_BIT=2;
namespace vk {
template<class T> auto Span(T* data, size_t size) { return std::span<T>{data,size}; }
struct World {
 std::map<VkBuffer,std::vector<std::uint8_t>> memory;
 u64 copies{}, regions{}, barriers{};
};
struct CommandBuffer {
 World* world;
 void PipelineBarrier(int,int,int,const VkMemoryBarrier&) { ++world->barriers; }
 void CopyBuffer(VkBuffer source,VkBuffer destination,std::span<VkBufferCopy> copies) {
  ++world->copies; world->regions+=copies.size();
  std::vector<std::pair<u64,u64>> intervals;
  for(const auto& copy:copies) intervals.emplace_back(copy.dstOffset,copy.dstOffset+copy.size);
  std::sort(intervals.begin(),intervals.end());
  for(size_t i=1;i<intervals.size();++i) assert(intervals[i-1].second<=intervals[i].first);
  for(const auto& copy:copies) {
   const auto& input=world->memory.at(source);auto& output=world->memory.at(destination);
   assert(copy.srcOffset+copy.size<=input.size() && copy.dstOffset+copy.size<=output.size());
   std::copy_n(input.begin()+copy.srcOffset,copy.size,output.begin()+copy.dstOffset);
  }
 }
};
}
namespace Vulkan {
class Scheduler {
public:
 using Fn=std::function<void(vk::CommandBuffer)>;
 Tegra::NativeSnapshotBatch<VkBuffer> native_snapshots;
 vk::World world;
 std::vector<Fn> main, device;
 bool in_pass{};unsigned submits{}, ends{};
 template<class F> void Record(F fn) { main.emplace_back(std::move(fn)); }
 void RequestOutsideRenderPassOperationContext() {
  if(in_pass) {in_pass=false;++ends;}
 }
 void Submit() { FlushNativeSnapshots();for(auto& fn:main)device.push_back(std::move(fn));main.clear();++submits; }
 void ExecuteGpu() {for(auto& fn:device)fn({&world});device.clear();}
 void QueueNativeSnapshot(VkBuffer,VkBuffer,u64,u64,u64);
 void CancelNativeSnapshots(VkBuffer);
 bool HasNativeSnapshotConflict(VkBuffer,u64,u64) const;
 void BeforeNativeBufferWrite(VkBuffer,u64,u64);
 void BeforeNativeBufferRelease(VkBuffer);
 void FlushNativeSnapshots();
};
#include "scheduler-methods.inc"
}
using Scheduler=Vulkan::Scheduler;
using Bytes=std::vector<std::uint8_t>;
void Init(Scheduler& scheduler,u64 source=1,u64 destination=2) {
 scheduler.world.memory[source]=Bytes(2048,3);scheduler.world.memory[destination]=Bytes(4096,0);
}
void Write(Scheduler& scheduler,VkBuffer source,u64 offset,u64 count,std::uint8_t value) {
 scheduler.BeforeNativeBufferWrite(source,offset,count);
 scheduler.Record([=](vk::CommandBuffer command){
  std::fill_n(command.world->memory.at(source).begin()+offset,count,value);
 });
}
// Actual raw-copy overlap guard from BufferCacheRuntime, generated alongside methods.
bool UploadGuard(Scheduler& scheduler,VkBuffer dst_buffer,std::span<const BufferCopy> copies,bool can_reorder_upload) {
#include "upload-guard.inc"
 return can_reorder_upload;
}
void Check(const Scheduler& scheduler,VkBuffer destination,u64 offset,std::uint8_t expected) {
 const auto& bytes=scheduler.world.memory.at(destination);
 for(size_t i=0;i<20;++i) assert(bytes[offset+i]==expected);
}
int main() {
 { // Cancellation before submission emits no commands and forces no submission.
  Scheduler s;Init(s);s.in_pass=true;
  s.QueueNativeSnapshot(1,2,0,0,20);s.CancelNativeSnapshots(2);
  assert(s.native_snapshots.Empty());s.Submit();s.ExecuteGpu();assert(s.world.copies==0 && s.submits==1);
 }
 { // A write elsewhere in the same buffer must not break the pass or flush copies.
  Scheduler s;Init(s);s.in_pass=true;
  s.QueueNativeSnapshot(1,2,0,0,20);Write(s,1,40,20,8);
  assert(s.native_snapshots.Size()==1 && s.ends==0 && s.submits==0);
  s.RequestOutsideRenderPassOperationContext();assert(s.native_snapshots.Size()==1);
  s.Submit();s.ExecuteGpu();Check(s,2,0,3);assert(s.world.copies==1);
 }
 { // Many pass changes do not emit copies; later full overwrite still cancels all.
  Scheduler s;Init(s);
  for(u64 i=0;i<100;++i) {
   s.QueueNativeSnapshot(1,2,0,i*20,20);
   s.in_pass=true;s.RequestOutsideRenderPassOperationContext();
  }
  assert(s.native_snapshots.Size()==100 && s.main.empty());
  s.CancelNativeSnapshots(2);s.Submit();s.ExecuteGpu();
  assert(s.world.copies==0 && s.world.regions==0);
 }
 { // Surviving requests across passes batch into one command at submission.
  Scheduler s;Init(s);
  for(u64 i=0;i<100;++i) {
   s.QueueNativeSnapshot(1,2,0,i*20,20);
   s.in_pass=true;s.RequestOutsideRenderPassOperationContext();
  }
  s.Submit();s.ExecuteGpu();assert(s.world.copies==1 && s.world.regions==100);
 }
 { // Producer/copy/reuse ordering in one main buffer, no special queue submit.
  Scheduler s;Init(s);Write(s,1,0,20,9);s.QueueNativeSnapshot(1,2,0,0,20);
  Write(s,1,0,20,12);assert(s.submits==0);s.QueueNativeSnapshot(1,2,0,20,20);
  s.Submit();s.ExecuteGpu();Check(s,2,0,9);Check(s,2,20,12);
 }
 { // An otherwise reorderable CPU upload must remain after the pending read.
  Scheduler s;Init(s);s.QueueNativeSnapshot(1,2,0,0,20);
  std::array copies{BufferCopy{0,0,20}};
  assert(!UploadGuard(s,1,copies,true));assert(s.native_snapshots.Empty());
  Write(s,1,0,20,19);s.Submit();s.ExecuteGpu();Check(s,2,0,3);
 }
 { // Multiple surviving regions share one copy command; slots reused after cancel do not overlap.
  Scheduler s;Init(s);s.world.memory[3]=Bytes(2048,7);
  s.QueueNativeSnapshot(1,2,0,0,20);s.QueueNativeSnapshot(1,2,20,20,20);
  s.QueueNativeSnapshot(3,2,0,40,20);s.Submit();s.ExecuteGpu();
  assert(s.world.copies==2 && s.world.regions==3 && s.world.barriers==2);Check(s,2,40,7);
  s.QueueNativeSnapshot(1,2,0,0,20);s.CancelNativeSnapshots(2);
  s.QueueNativeSnapshot(3,2,0,0,20);s.Submit();s.ExecuteGpu();Check(s,2,0,7);
 }
 { // No stale resource can remain queued past release/growth; partial destination overlaps drain.
  Scheduler s;Init(s);s.QueueNativeSnapshot(1,2,0,0,20);s.BeforeNativeBufferRelease(1);
  assert(s.native_snapshots.Empty());s.Submit();s.ExecuteGpu();Check(s,2,0,3);
  s.QueueNativeSnapshot(1,2,0,0,20);s.QueueNativeSnapshot(1,2,0,4,20);
  s.Submit();s.ExecuteGpu();Check(s,2,4,3);
 }
 { // Bounded capacity drains commands, without introducing a queue submission.
  Scheduler s;Init(s);constexpr auto cap=Tegra::NativeSnapshotBatch<u64>::MaxRequests;
  s.world.memory[2].resize((cap+1)*20);
  for(u64 i=0;i<cap+1;++i)s.QueueNativeSnapshot(1,2,0,i*20,20);
  assert(s.submits==0 && s.native_snapshots.Size()==1);s.Submit();s.ExecuteGpu();
  assert(s.world.regions==cap+1);
 }
 std::mt19937 random(0x4101e7);
 for(unsigned run=0;run<128;++run) {
  Scheduler s;Init(s);s.world.memory[3]=Bytes(2048,6);
  std::map<u64,Bytes> logical=s.world.memory;
  std::map<u64,std::array<std::uint8_t,20>> expected;
  u64 slot{};
  for(unsigned step=0;step<2048;++step) {
   const auto action=random()%7;const u64 source=random()%2?1:3;
   const u64 offset=(random()%32)*20;
   if(action<2) {
    if(slot==128) {s.Submit();s.ExecuteGpu();for(auto& [at,value]:expected)
      assert(std::equal(value.begin(),value.end(),s.world.memory[2].begin()+at));expected.clear();slot=0;}
    std::array<std::uint8_t,20> value;std::copy_n(logical[source].begin()+offset,20,value.begin());
    expected[slot*20]=value;s.QueueNativeSnapshot(source,2,offset,slot*20,20);++slot;
   } else if(action<4) {
    const auto value=std::uint8_t(random());Write(s,source,offset,20,value);
    std::fill_n(logical[source].begin()+offset,20,value);
   } else if(action==4) {
    // A complete CPU overwrite makes all outstanding destination slots unobservable.
    s.CancelNativeSnapshots(2);expected.clear();slot=0;
   } else if(action==5) {s.in_pass=true;s.RequestOutsideRenderPassOperationContext();}
   else {s.Submit();}
  }
  s.Submit();s.ExecuteGpu();
  for(auto& [at,value]:expected)assert(std::equal(value.begin(),value.end(),s.world.memory[2].begin()+at));
 }
 std::puts("PASS: real scheduler methods and upload guard; cancellation, exact write ranges, overwrite/replay, natural boundaries, resource release, grouping, slot reuse, capacity and 262144 mixed events (ASan/UBSan)");
}
