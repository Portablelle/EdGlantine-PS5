#include "probe.h"

struct nx2_sparse_report
nx2_sparse_probe(VkPhysicalDevice physical, uint32_t queue_family, VkFormat format,
                 VkImageUsageFlags usage, VkBool32 requested, VkBool32 enabled_on_device)
{
    struct nx2_sparse_report r = {0};
    VkPhysicalDeviceFeatures features;
    VkPhysicalDeviceProperties properties;
    vkGetPhysicalDeviceFeatures(physical, &features);
    vkGetPhysicalDeviceProperties(physical, &properties);
    r.sparse_binding = features.sparseBinding;
    r.residency_2d = features.sparseResidencyImage2D;
    r.strict_nonresident = properties.sparseProperties.residencyNonResidentStrict;
    r.sparse_address_space = properties.limits.sparseAddressSpaceSize;
    if (!requested) r.blockers |= NX2_SPARSE_DISABLED;
    if (!enabled_on_device) r.blockers |= NX2_SPARSE_NOT_ENABLED_ON_DEVICE;
    if (!r.sparse_binding || !r.residency_2d) r.blockers |= NX2_SPARSE_FEATURE;
    if (!r.strict_nonresident) r.blockers |= NX2_SPARSE_NONZERO_HOLES;

    uint32_t count = 0;
    VkQueueFamilyProperties queues[64];
    vkGetPhysicalDeviceQueueFamilyProperties(physical, &count, NULL);
    if (count > 64) {
        r.blockers |= NX2_SPARSE_QUERY_LIMIT | NX2_SPARSE_QUEUE;
    } else {
        vkGetPhysicalDeviceQueueFamilyProperties(physical, &count, queues);
        if (queue_family >= count || !queues[queue_family].queueCount ||
            !(queues[queue_family].queueFlags & VK_QUEUE_SPARSE_BINDING_BIT))
            r.blockers |= NX2_SPARSE_QUEUE;
    }
    const VkImageCreateFlags flags = VK_IMAGE_CREATE_SPARSE_BINDING_BIT |
                                     VK_IMAGE_CREATE_SPARSE_RESIDENCY_BIT;
    r.image_format_result = vkGetPhysicalDeviceImageFormatProperties(
        physical, format, VK_IMAGE_TYPE_2D, VK_IMAGE_TILING_OPTIMAL, usage, flags, &r.limits);
    if (r.image_format_result != VK_SUCCESS) r.blockers |= NX2_SPARSE_FORMAT;
    VkSparseImageFormatProperties formats[16];
    count = 0;
    vkGetPhysicalDeviceSparseImageFormatProperties(physical, format, VK_IMAGE_TYPE_2D,
        VK_SAMPLE_COUNT_1_BIT, usage, VK_IMAGE_TILING_OPTIMAL, &count, NULL);
    if (count > 16) {
        r.blockers |= NX2_SPARSE_QUERY_LIMIT | NX2_SPARSE_FORMAT;
    } else {
        vkGetPhysicalDeviceSparseImageFormatProperties(physical, format, VK_IMAGE_TYPE_2D,
            VK_SAMPLE_COUNT_1_BIT, usage, VK_IMAGE_TILING_OPTIMAL, &count, formats);
        for (uint32_t i = 0; i < count; ++i) {
            if (formats[i].aspectMask == VK_IMAGE_ASPECT_COLOR_BIT) {
                r.color = formats[i];
                break;
            }
        }
        if (!r.color.imageGranularity.width || !r.color.imageGranularity.height ||
            r.color.imageGranularity.depth != 1) r.blockers |= NX2_SPARSE_FORMAT;
    }
    return r;
}
