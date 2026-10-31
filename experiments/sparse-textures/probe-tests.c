#include <stdbool.h>

#include "probe.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static VkBool32 strict = VK_TRUE, feature = VK_TRUE;
static uint32_t families=1, formats=1;
static VkQueueFlags queue_flags=VK_QUEUE_GRAPHICS_BIT | VK_QUEUE_SPARSE_BINDING_BIT;
static VkResult format_result=VK_SUCCESS;
VKAPI_ATTR void VKAPI_CALL vkGetPhysicalDeviceFeatures(VkPhysicalDevice p,VkPhysicalDeviceFeatures *f) {
 (void)p; memset(f,0,sizeof(*f)); f->sparseBinding=f->sparseResidencyImage2D=feature;
}
VKAPI_ATTR void VKAPI_CALL vkGetPhysicalDeviceProperties(VkPhysicalDevice p,VkPhysicalDeviceProperties *v) {
 (void)p; memset(v,0,sizeof(*v)); v->sparseProperties.residencyNonResidentStrict=strict;
 v->limits.sparseAddressSpaceSize=1ULL<<40;
}
VKAPI_ATTR void VKAPI_CALL vkGetPhysicalDeviceQueueFamilyProperties(VkPhysicalDevice p,uint32_t *n,VkQueueFamilyProperties *v) {
 (void)p; if(!v){*n=families;return;} assert(*n>=families);
 for(uint32_t i=0;i<families;++i) v[i]=(VkQueueFamilyProperties){.queueFlags=queue_flags,.queueCount=1};
 *n=families;
}
VKAPI_ATTR VkResult VKAPI_CALL vkGetPhysicalDeviceImageFormatProperties(VkPhysicalDevice p,VkFormat f,VkImageType t,VkImageTiling til,VkImageUsageFlags u,VkImageCreateFlags flags,VkImageFormatProperties *v) {
 (void)p;(void)f;assert(t==VK_IMAGE_TYPE_2D);assert(til==VK_IMAGE_TILING_OPTIMAL);
 assert(u==(VK_IMAGE_USAGE_SAMPLED_BIT|VK_IMAGE_USAGE_TRANSFER_DST_BIT));
 assert(flags==(VK_IMAGE_CREATE_SPARSE_BINDING_BIT|VK_IMAGE_CREATE_SPARSE_RESIDENCY_BIT));
 memset(v,0,sizeof(*v));return format_result;
}
VKAPI_ATTR void VKAPI_CALL vkGetPhysicalDeviceSparseImageFormatProperties(VkPhysicalDevice p,VkFormat f,VkImageType t,VkSampleCountFlagBits samples,VkImageUsageFlags u,VkImageTiling til,uint32_t *n,VkSparseImageFormatProperties *v) {
 (void)p;(void)f;(void)t;(void)u;(void)til;assert(samples==VK_SAMPLE_COUNT_1_BIT);
 if(!v){*n=formats;return;}assert(*n>=formats);
 for(uint32_t i=0;i<formats;++i) v[i]=(VkSparseImageFormatProperties){.aspectMask=VK_IMAGE_ASPECT_COLOR_BIT,.imageGranularity={128,128,1}};
 *n=formats;
}
static uint32_t check(VkBool32 requested,VkBool32 enabled) {
 return nx2_sparse_probe(VK_NULL_HANDLE,0,VK_FORMAT_R8G8B8A8_UNORM,
 VK_IMAGE_USAGE_SAMPLED_BIT|VK_IMAGE_USAGE_TRANSFER_DST_BIT,requested,enabled).blockers;
}
int main(void) {
 assert(check(false,true)==NX2_SPARSE_DISABLED);
 assert(check(true,false)==NX2_SPARSE_NOT_ENABLED_ON_DEVICE);
 assert(check(true,true)==0);
 strict=false;assert(check(true,true)==NX2_SPARSE_NONZERO_HOLES);strict=true;
 feature=false;assert(check(true,true)==NX2_SPARSE_FEATURE);feature=true;
 queue_flags=VK_QUEUE_GRAPHICS_BIT;assert(check(true,true)==NX2_SPARSE_QUEUE);
 queue_flags|=VK_QUEUE_SPARSE_BINDING_BIT;
 families=0;assert(check(true,true)==NX2_SPARSE_QUEUE);
 families=65;assert(check(true,true)==(NX2_SPARSE_QUEUE|NX2_SPARSE_QUERY_LIMIT));families=1;
 formats=0;assert(check(true,true)==NX2_SPARSE_FORMAT);
 formats=17;assert(check(true,true)==(NX2_SPARSE_FORMAT|NX2_SPARSE_QUERY_LIMIT));formats=1;
 format_result=VK_ERROR_FORMAT_NOT_SUPPORTED;assert(check(true,true)==NX2_SPARSE_FORMAT);
 puts("PASS: disabled default, logical-device enablement, strict holes, queue/format gates and bounded queries (mock Vulkan)");
}
