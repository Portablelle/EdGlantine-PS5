#include <cassert>
#include <stdexcept>
#include <string>
#include "video_core/renderer_vulkan/vk_sparse_layers.h"
using namespace Vulkan::SparseLayers;
struct Mock : Backend {
    std::string events;
    unsigned allocations{}, freed{}, drains{}, fail_allocation{}, fail_drain{};
    bool fail_bind{}, throw_bind{}, destroyed{};
    VkDeviceMemory Allocate(VkDeviceSize bytes, uint32_t types) override {
        assert(bytes && types==3); events += 'A';
        return ++allocations == fail_allocation ? VkDeviceMemory{} : (VkDeviceMemory)(uintptr_t)allocations;
    }
    void Free(VkDeviceMemory) noexcept override { assert(destroyed); ++freed; events += 'F'; }
    bool Drain() noexcept override { events += 'W'; return ++drains != fail_drain; }
    bool Bind(const Plan& p, std::span<const VkDeviceMemory> memory) override {
        events += 'B'; assert(memory.size()==p.layers.size());
        for(size_t i=0;i<memory.size();++i) assert(!p.layers[i].bytes || memory[i]);
        if (throw_bind) throw std::runtime_error("bind allocation failure");
        return !fail_bind;
    }
    void DestroyImage() noexcept override { assert(!destroyed); destroyed=true;events+='D'; }
};
int main() {
 assert(!Requested(nullptr) && !Requested("") && !Requested("0") && !Requested("true") && Requested("1"));
 VkImageCreateInfo ci{VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO};
 ci.imageType=VK_IMAGE_TYPE_2D;ci.extent={257,129,1};ci.arrayLayers=2;ci.mipLevels=3;ci.samples=VK_SAMPLE_COUNT_1_BIT;
 VkMemoryRequirements memory{8<<20,65536,3};
 VkSparseImageMemoryRequirements r{};
 r.formatProperties={VK_IMAGE_ASPECT_COLOR_BIT,{128,128,1},0};
 r.imageMipTailFirstLod=2;r.imageMipTailSize=65536;r.imageMipTailOffset=2<<20;r.imageMipTailStride=2<<20;
 auto plan=MakePlan(ci,memory,std::span{&r,1});assert(plan);
 assert(plan->layers.size()==2 && plan->bytes==16*65536);
 assert(plan->layers[0].tiles.size()==2);
 assert(plan->layers[0].tiles[1].memoryOffset==6*65536);
 assert(plan->layers[1].tiles[0].subresource.arrayLayer==1);
 assert(plan->layers[1].tails[0].resourceOffset==4<<20);
 assert(plan->layers[1].tails[0].memoryOffset==7*65536);
 {
  Mock b;Residency x{b};assert(x.Initialize(*plan));assert(x.GetState()==State::Resident);
  assert(committed==plan->bytes && b.events=="AAWB");
  assert(!x.Initialize(*plan)); x.Retire();assert(b.events=="AAWBWDFF");
  x.Retire();assert(committed==0);
 }
 { Mock b;b.fail_allocation=2;Residency x{b};assert(!x.Initialize(*plan));assert(b.events=="AADF");assert(committed==0); }
 { Mock b;b.fail_bind=true;Residency x{b};assert(!x.Initialize(*plan));assert(b.events=="AAWBWDFF");assert(committed==0); }
 { Mock b;b.throw_bind=true;Residency x{b};try{x.Initialize(*plan);assert(false);}catch(const std::runtime_error&){} assert(b.events=="AAWBWDFF");assert(committed==0); }
 // Shared tail allocated exactly once, plus two layer allocations; no shared-tail double free.
 r.formatProperties.flags=VK_SPARSE_IMAGE_FORMAT_SINGLE_MIPTAIL_BIT;
 auto shared=MakePlan(ci,memory,std::span{&r,1});assert(shared);
 assert(shared->layers.size()==3 && shared->layers.back().bytes==65536);
 assert(shared->bytes==15*65536);
 { Mock b;Residency x{b};assert(x.Initialize(*shared));x.Retire();assert(b.freed==3); }
 // Tail-only image has no tile allocation, but preserves the single shared tail.
 r.imageMipTailFirstLod=0;auto tail=MakePlan(ci,memory,std::span{&r,1});assert(tail && tail->bytes==65536);
 { Mock b;Residency x{b};assert(x.Initialize(*tail));assert(b.allocations==1); }
 // BC3 granularity remains in texels; the queried 256x256 tile is 64 KiB.
 r.formatProperties={VK_IMAGE_ASPECT_COLOR_BIT,{256,256,1},0};r.imageMipTailFirstLod=2;
 auto bc=MakePlan(ci,memory,std::span{&r,1});assert(bc && bc->bytes==8*65536);
 r.formatProperties.aspectMask=VK_IMAGE_ASPECT_METADATA_BIT;assert(!MakePlan(ci,memory,std::span{&r,1}));
 r.formatProperties.aspectMask=VK_IMAGE_ASPECT_COLOR_BIT;
 r.imageMipTailOffset=UINT64_MAX;assert(!MakePlan(ci,memory,std::span{&r,1}));r.imageMipTailOffset=2<<20;
 r.imageMipTailStride=UINT64_MAX-65535;ci.arrayLayers=3;assert(!MakePlan(ci,memory,std::span{&r,1}));
 r.imageMipTailStride=2<<20;ci.arrayLayers=2;ci.extent.width=UINT32_MAX;ci.extent.height=UINT32_MAX;
 assert(!MakePlan(ci,memory,std::span{&r,1}));
 ci.extent={257,129,1};r.formatProperties.imageGranularity.width=0;assert(!MakePlan(ci,memory,std::span{&r,1}));
 // A driver block that is not one 64 KiB page (AMD reported 65549x339860304) is rejected.
 r.formatProperties.imageGranularity={65549,339860304,1};assert(!MakePlan(ci,memory,std::span{&r,1}));
 r.formatProperties.imageGranularity={127,128,1};assert(!MakePlan(ci,memory,std::span{&r,1}));
 r.formatProperties.imageGranularity={128,128,1};assert(MakePlan(ci,memory,std::span{&r,1}));
 assert(!MakePlan(ci,memory,{}));
 // Global budget rejects admission before allocations. Existing commitments stay charged.
 committed=GlobalBudget;
 { Mock b;Residency x{b};assert(!x.Initialize(*plan));assert(b.allocations==0); }
 assert(committed==GlobalBudget);committed=0;
 // A failed completion after a partial bind retains image, allocations, fence and budget.
 { Mock b;b.fail_bind=true;b.fail_drain=2;Residency x{b};assert(!x.Initialize(*plan));
   assert(x.GetState()==State::Quarantined);assert(!b.destroyed && b.freed==0);x.Retire();assert(b.events=="AAWBW"); }
 assert(quarantined && committed==plan->bytes);
 { Mock b;Residency x{b};assert(!x.Initialize(*plan));assert(b.allocations==0); }
 // Restore only the mock process's synthetic counters. Production never clears quarantine.
 quarantined=false;committed=0;
 puts("Sparse layers: layouts, tails, overflow, budgets, publication, partial failure, quarantine and retirement PASS");
}
