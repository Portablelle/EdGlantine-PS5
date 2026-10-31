/* Minimal host model around extracted production RADV routines. No GPU emulation. */
#include <vulkan/vulkan.h>
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define GFX9 9
#define DIV_ROUND_UP(a,b) (((a)+(b)-1)/(b))
#define align(a,b) (((a)+(b)-1)&~((b)-1))
#define MIN2(a,b) ((a)<(b)?(a):(b))
#define RADV_PS5_PAGE_BYTES 0x4000ULL
#define RADV_PS5_LARGE_BYTES 0x200000ULL
#define VK_FROM_HANDLE(t,n,h) struct t *n = (struct t *)(uintptr_t)(h)
struct radeon_winsys_bo { int unused; };
struct radeon_surf {
 uint32_t prt_tile_width, prt_tile_height, prt_tile_depth;
 union {
  struct { uint64_t surf_slice_size, prt_level_offset[16]; uint32_t prt_level_pitch[16]; } gfx9;
  struct { struct { uint64_t slice_size_dw, offset_256B; uint32_t nblk_x; } level[16]; } legacy;
 } u;
};
struct radv_image {
 struct { int base; VkFormat format; } vk;
 struct { struct radeon_surf surface; } planes[1];
 struct { struct radeon_winsys_bo *bo; } bindings[1];
};
struct radv_buffer { struct { int base; } vk; struct radeon_winsys_bo *bo; };
struct radv_device_memory { struct radeon_winsys_bo *bo; };
struct radv_physical_device { struct { int gfx_level; bool has_sparse_cpu_binds; } info; };
struct radv_device { int vk; struct radv_physical_device *pdev; };
struct vk_queue_submit {
 uint32_t wait_count; int *waits;
 uint32_t buffer_bind_count, image_opaque_bind_count, image_bind_count;
 const VkSparseBufferMemoryBindInfo *buffer_binds;
 const VkSparseImageOpaqueMemoryBindInfo *image_opaque_binds;
 const VkSparseImageMemoryBindInfo *image_binds;
};
static const struct radv_physical_device *radv_device_physical(struct radv_device *d) { return d->pdev; }
static struct radv_device_memory *radv_device_memory_from_handle(VkDeviceMemory h) { return (void *)(uintptr_t)h; }
static uint32_t vk_format_get_blocksize(VkFormat f) { return f == VK_FORMAT_BC3_UNORM_BLOCK ? 16 : 4; }
static uint32_t vk_format_get_blockwidth(VkFormat f) { return f == VK_FORMAT_BC3_UNORM_BLOCK ? 4 : 1; }
static uint32_t vk_format_get_blockheight(VkFormat f) { return vk_format_get_blockwidth(f); }
static unsigned util_logbase2(unsigned n) { assert(n); return 31u - (unsigned)__builtin_clz(n); }
struct call { uint64_t offset, size, memory_offset; bool bound; };
static struct call calls[32];
static unsigned num_calls, fail_call, waits;
static VkResult wait_result;
static VkResult radv_bo_virtual_bind(struct radv_device *d, int *base, struct radeon_winsys_bo *parent,
 uint64_t offset, uint64_t size, struct radeon_winsys_bo *memory, uint64_t memory_offset) {
 (void)d; (void)base; (void)parent;
 assert(num_calls < 32);
 calls[num_calls++] = (struct call){offset,size,memory_offset,memory != NULL};
 return num_calls == fail_call ? VK_ERROR_OUT_OF_DEVICE_MEMORY : VK_SUCCESS;
}
static VkResult vk_sync_wait_many(int *device, uint32_t count, int *syncs, int flags, uint64_t timeout) {
 (void)device; (void)syncs; (void)flags; assert(count); assert(timeout == UINT64_MAX);
 assert(num_calls == 0); ++waits; return wait_result;
}
struct radv_ps5_memory { int64_t physical; uint64_t bytes; };
static unsigned maps, fail_map;
static int64_t zero_physical = 0x800000;
static int64_t radv_ps5_zero_block(void) { return zero_physical; }
static bool radv_ps5_map_fixed(uint8_t *at, uint64_t bytes, int64_t physical) {
 assert((uintptr_t)at % RADV_PS5_PAGE_BYTES == 0);
 assert(bytes % RADV_PS5_PAGE_BYTES == 0);
 assert(physical % RADV_PS5_PAGE_BYTES == 0);
 ++maps; return maps != fail_map;
}
