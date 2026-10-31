/* Experimental capability audit only: never creates or binds an image. */
#pragma once
#include <vulkan/vulkan.h>
#include <stdint.h>

enum nx2_sparse_blocker {
    NX2_SPARSE_DISABLED = 1u << 0,
    NX2_SPARSE_FEATURE = 1u << 1,
    NX2_SPARSE_QUEUE = 1u << 2,
    NX2_SPARSE_FORMAT = 1u << 3,
    NX2_SPARSE_NONZERO_HOLES = 1u << 4,
    NX2_SPARSE_NOT_ENABLED_ON_DEVICE = 1u << 5,
    NX2_SPARSE_QUERY_LIMIT = 1u << 6,
};
struct nx2_sparse_report {
    uint32_t blockers;
    VkBool32 sparse_binding, residency_2d, strict_nonresident;
    VkResult image_format_result;
    VkDeviceSize sparse_address_space;
    VkSparseImageFormatProperties color;
    VkImageFormatProperties limits;
};
/* enabled_on_device is the actual logical-device feature state, not availability.
 * requested must stay false in the normal prototype. A zero blockers result is
 * only admission to further experiments, never hardware/render validation.
 * The initial design requires zero reads from holes. A fully resident view-based
 * design needs a separate proof before relaxing that requirement. */
struct nx2_sparse_report nx2_sparse_probe(VkPhysicalDevice physical, uint32_t queue_family,
                                        VkFormat format, VkImageUsageFlags usage,
                                        VkBool32 requested, VkBool32 enabled_on_device);
