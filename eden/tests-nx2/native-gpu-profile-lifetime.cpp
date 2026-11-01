// SPDX-License-Identifier: GPL-3.0-or-later
#include <algorithm>
#include <array>
#include <atomic>
#include <cassert>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <exception>
#include <stdexcept>
#include <utility>
#include "native_gpu_profile.h"
using u64=uint64_t;
constexpr int VK_NOT_READY=1,VK_SUCCESS=0,VK_QUERY_RESULT_64_BIT=1,VK_STRUCTURE_TYPE_QUERY_POOL_CREATE_INFO=1,VK_QUERY_TYPE_TIMESTAMP=1,VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT=1,VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT=2;
struct PoolInfo {int type;void* next;int flags,queryType;unsigned count;int statistics;};
using PFN_vkCmdWriteTimestamp=void(*)(int,int,int,unsigned);
static void Stamp(int,int,int,unsigned) {}
static bool alive[3]{false,true,true};
static unsigned destroyed[3]{};
namespace Vulkan {
namespace vk {
struct QueryPool {
 int value{};
 QueryPool()=default;
 QueryPool(int id):value(id){}
 QueryPool(const QueryPool&)=delete;
 QueryPool& operator=(const QueryPool&)=delete;
 QueryPool(QueryPool&& other):value(std::exchange(other.value,0)){}
 QueryPool& operator=(QueryPool&& other){release();value=std::exchange(other.value,0);return *this;}
 void release(){if(value){assert(alive[value]);++destroyed[value];value=0;}}
 ~QueryPool(){release();}
 explicit operator bool()const{return value!=0;}
 int operator*()const{return value;}
};
class CommandBuffer {public:int operator*()const{return 1;}void ResetQueryPool(int,unsigned,unsigned)const{}};
}
struct Logical {int id=1;mutable bool ready=true;mutable unsigned reads{};int operator*()const{return 1;}
 vk::QueryPool CreateQueryPool(PoolInfo)const{return {id};}
 int GetQueryResults(int pool,unsigned,unsigned,size_t,void* out,size_t,int flags)const{assert(pool==id && alive[id]);assert(flags==VK_QUERY_RESULT_64_BIT);++reads;if(!ready)return VK_NOT_READY;auto* p=static_cast<u64*>(out);p[0]=100;p[1]=200;return VK_SUCCESS;}};
struct Dispatch {PFN_vkCmdWriteTimestamp vkGetDeviceProcAddr(int,const char*)const{return Stamp;}};
struct Properties {struct {double timestampPeriod=1;}limits;};
struct Physical {Properties GetProperties()const{return {};}};
class Device {public:Logical logical;const Logical& GetLogical()const{return logical;}Dispatch GetDispatchLoader()const{return {};}Physical GetPhysical()const{return {};}};
#include "native_gpu_profile.inc"
}
int main(){using namespace Vulkan;using namespace NativeGpuProfile;Device d;vk::CommandBuffer c;
 BeginBuffer(d,c);assert(probe.next==0);EndBuffer();
 enabled=true;BeginBuffer(d,c);Ticket t;Begin(c,t,{1,1,2,640,480,64});EndBuffer();
 // An operation can span two natural submissions. The unfinished ticket must pin its slot.
 Collect(d);assert(probe.first==0&&d.logical.reads==0);
 BeginBuffer(d,c);End(c,t);EndBuffer();d.logical.ready=false;Collect(d);assert(probe.first==0);
 d.logical.ready=true;Collect(d);assert(probe.first==2&&probe.totals[0].count==1&&probe.totals[0].ns==100);
 // A full ring must drop measurement rather than reuse live GPU queries or wait.
 d.logical.ready=false;
 for(unsigned i=0;i<Buffers;++i){BeginBuffer(d,c);Ticket q;Begin(c,q,{1,1,2,640,480,64});End(c,q);EndBuffer();}
 auto next=probe.next;BeginBuffer(d,c);assert(probe.current==-1&&probe.next==next&&probe.dropped==1);EndBuffer();
 d.logical.ready=true;Collect(d);assert(probe.first==probe.next);
 enabled=false;BeginBuffer(d,c);assert(probe.current==-1);
 probe.failed=true; // Failed sessions must also recover on the next device.
 Reset();assert(!enabled && !probe.pool && !probe.failed && !probe.write);
 assert(probe.next==0 && probe.first==0 && probe.current==-1 && destroyed[1]==1);
 alive[1]=false;
 Device second;second.logical.id=2;
 enabled=true;BeginBuffer(second,c);Ticket fresh;Begin(c,fresh,{1,1,2,640,480,64});
 End(c,fresh);EndBuffer();Collect(second);
 assert(*probe.pool==2 && probe.totals[0].count==1);
 Reset();assert(destroyed[2]==1);alive[2]=false;
 Reset();assert(destroyed[1]==1 && destroyed[2]==1);
 std::puts("GPU_PROFILE_LIFETIME_OK: ring, reset, two devices, destruction before device teardown");
}
