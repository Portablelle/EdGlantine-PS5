// Worker-thread only. No query-result WAIT flag or new queue submission.
namespace NativeGpuProfile {
namespace {
constexpr unsigned Buffers = 64, Regions = 16;
struct Sample { Label label; bool ended{}; };
struct Buffer { std::array<Sample, Regions> samples{}; unsigned used{}, read{}; bool submitted{}; std::uint64_t epoch{}; };
struct Total { Label label; std::uint64_t count{}, ns{}, maximum{}; };
struct Probe {
 vk::QueryPool pool;
 PFN_vkCmdWriteTimestamp write{};
 std::array<Buffer, Buffers> buffers{};
 std::array<Total, 129> totals{};
 std::uint64_t next{}, first{}, epoch{}, dropped{};
 int current{-1};double period{};
 std::chrono::steady_clock::time_point report{};
 bool failed{};
} probe;
bool Same(const Label& a,const Label& b) {
 return a.kind==b.kind && a.first==b.first && a.second==b.second && a.width==b.width && a.height==b.height;
}
}
void Collect(const Device& device) {
 if (!probe.pool || probe.failed) return;
 while(probe.first<probe.next) {
  auto& buffer=probe.buffers[probe.first%Buffers];
  if(!buffer.submitted) break;
  while(buffer.read<buffer.used) {
   const auto& sample=buffer.samples[buffer.read];
   if(!sample.ended) goto report;
   std::array<u64,2> stamps{};
   const unsigned query=(probe.first%Buffers)*Regions*2+buffer.read*2;
   const auto result=device.GetLogical().GetQueryResults(*probe.pool,query,2,sizeof(stamps),stamps.data(),sizeof(u64),VK_QUERY_RESULT_64_BIT);
   if(result==VK_NOT_READY) goto report;
   if(result!=VK_SUCCESS) {probe.failed=true;std::fprintf(stderr,"NX2_GPU_SAMPLE unavailable result=%d\n",int(result));return;}
   const auto ns=stamps[1]>=stamps[0]?static_cast<u64>(double(stamps[1]-stamps[0])*probe.period):0;
   if(buffer.epoch==probe.epoch) {
    Total* total=&probe.totals.back();
    for(size_t i=0;i+1<probe.totals.size();++i)if(!probe.totals[i].count||Same(probe.totals[i].label,sample.label)) {total=&probe.totals[i];break;}
    if(!total->count)total->label=sample.label;
    ++total->count;total->ns+=ns;total->maximum=std::max(total->maximum,ns);
   }
   ++buffer.read;
  }
  ++probe.first;
 }
report:
 const auto now=std::chrono::steady_clock::now();
 if(now-probe.report<std::chrono::seconds(5))return;
 probe.report=now;
 auto ranked=probe.totals;
 std::sort(ranked.begin(),ranked.end(),[](const auto& a,const auto& b){return a.ns>b.ns;});
 for(size_t i=0;i<12 && ranked[i].count;++i) {
  const auto& t=ranked[i];
  std::fprintf(stderr,"NX2_GPU_SAMPLE epoch=%llu kind=%u first=%llx second=%llx area=%ux%u stride=%u samples=%llu ns=%llu max_ns=%llu dropped=%llu\n",
   static_cast<unsigned long long>(probe.epoch),t.label.kind,static_cast<unsigned long long>(t.label.first),static_cast<unsigned long long>(t.label.second),
   t.label.width,t.label.height,t.label.stride,static_cast<unsigned long long>(t.count),static_cast<unsigned long long>(t.ns),static_cast<unsigned long long>(t.maximum),static_cast<unsigned long long>(probe.dropped));
 }
}
void BeginBuffer(const Device& device,vk::CommandBuffer command) {
 probe.current=-1;
 Collect(device);
 if(!enabled.load(std::memory_order_relaxed)||probe.failed)return;
 const auto requested=epoch.load(std::memory_order_relaxed);
 if(probe.epoch!=requested) {probe.epoch=requested;probe.totals={};probe.dropped=0;probe.report=std::chrono::steady_clock::now();}
 try {
  if(!probe.pool) {
   probe.write=reinterpret_cast<PFN_vkCmdWriteTimestamp>(device.GetDispatchLoader().vkGetDeviceProcAddr(*device.GetLogical(),"vkCmdWriteTimestamp"));
   probe.period=device.GetPhysical().GetProperties().limits.timestampPeriod;
   if(!probe.write||probe.period<=0) {probe.failed=true;return;}
   probe.pool=device.GetLogical().CreateQueryPool({VK_STRUCTURE_TYPE_QUERY_POOL_CREATE_INFO,nullptr,0,VK_QUERY_TYPE_TIMESTAMP,Buffers*Regions*2,0});
  }
  if(probe.next-probe.first>=Buffers) {++probe.dropped;return;}
  const auto slot=probe.next++%Buffers;
  probe.buffers[slot]={};probe.buffers[slot].epoch=probe.epoch;
  command.ResetQueryPool(*probe.pool,slot*Regions*2,Regions*2);
  probe.current=static_cast<int>(slot);
 } catch(const std::exception& error) {probe.failed=true;std::fprintf(stderr,"NX2_GPU_SAMPLE disabled: %s\n",error.what());}
}
void EndBuffer() {
 if(probe.current>=0)probe.buffers[probe.current].submitted=true;
 probe.current=-1;
}
void Begin(vk::CommandBuffer command,Ticket& ticket,Label label) {
 if(probe.current<0)return;
 auto& buffer=probe.buffers[probe.current];
 if(buffer.used==Regions){++probe.dropped;return;}
 const auto region=buffer.used++;
 buffer.samples[region].label=label;
 ticket.query=(probe.current*Regions+region)*2;
 probe.write(*command,VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,*probe.pool,ticket.query);
}
void End(vk::CommandBuffer command,const Ticket& ticket) {
 if(ticket.query<0)return;
 probe.write(*command,VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT,*probe.pool,ticket.query+1);
 const unsigned region=ticket.query/2;
 probe.buffers[region/Regions].samples[region%Regions].ended=true;
}
}
