int main(void) {
 struct radv_physical_device pdev = {.info={.gfx_level=GFX9,.has_sparse_cpu_binds=true}};
 VkSparseImageFormatProperties format = {0};
 fill_sparse_image_format_properties(&pdev,VK_IMAGE_TYPE_2D,VK_FORMAT_R8G8B8A8_UNORM,&format);
 assert(format.imageGranularity.width==128 && format.imageGranularity.height==128);
 assert(format.imageGranularity.depth==1 && format.flags==0);
 fill_sparse_image_format_properties(&pdev,VK_IMAGE_TYPE_2D,VK_FORMAT_BC3_UNORM_BLOCK,&format);
 assert(format.imageGranularity.width==256 && format.imageGranularity.height==256);
 assert(format.imageGranularity.depth==1 && format.flags==0);
 struct radv_device device = {.pdev=&pdev};
 struct radeon_winsys_bo bo = {0};
 struct radv_device_memory memory = {.bo=&bo};
 struct radv_image image = {.vk.format=VK_FORMAT_R8G8B8A8_UNORM};
 struct radeon_surf *s = &image.planes[0].surface;
 s->prt_tile_width=128; s->prt_tile_height=128; s->prt_tile_depth=1;
 s->u.gfx9.surf_slice_size=0x100000;
 s->u.gfx9.prt_level_offset[1]=0x40000;
 s->u.gfx9.prt_level_pitch[1]=256;
 VkSparseImageMemoryBind tile = {.subresource={VK_IMAGE_ASPECT_COLOR_BIT,1,2},
  .offset={128,0,0}, .extent={128,256,1}, .memory=(VkDeviceMemory)(uintptr_t)&memory, .memoryOffset=0x10000};
 VkSparseImageMemoryBindInfo bind = {.image=(VkImage)(uintptr_t)&image,.bindCount=1,.pBinds=&tile};
 assert(radv_sparse_image_bind_memory(&device,&bind)==VK_SUCCESS);
 assert(num_calls==2);
 assert(calls[0].offset==0x250000 && calls[1].offset==0x270000);
 assert(calls[0].size==65536 && calls[1].size==65536);
 assert(calls[0].memory_offset==65536 && calls[1].memory_offset==131072);
 // Partial edge tiles consume full physical tiles; the second array layer stays separate.
 num_calls=0; tile.offset.x=0; tile.extent=(VkExtent3D){17,3,1};
 assert(radv_sparse_image_bind_memory(&device,&bind)==VK_SUCCESS);
 assert(num_calls==1 && calls[0].offset==0x240000 && calls[0].size==65536);
 // BC3 coordinates are in texels, converted to 4x4 blocks by the production code.
 image.vk.format=VK_FORMAT_BC3_UNORM_BLOCK;
 s->prt_tile_width=64; s->prt_tile_height=64; s->u.gfx9.prt_level_pitch[1]=128;
 tile.offset.x=256; tile.extent=(VkExtent3D){256,512,1}; num_calls=0;
 assert(radv_sparse_image_bind_memory(&device,&bind)==VK_SUCCESS);
 assert(num_calls==2 && calls[0].offset==0x250000 && calls[1].offset==0x270000);
 assert(calls[0].size==65536 && calls[1].memory_offset==131072);
 // Unbinding uses the same ranges but no physical allocation.
 tile.memory=VK_NULL_HANDLE; num_calls=0;
 assert(radv_sparse_image_bind_memory(&device,&bind)==VK_SUCCESS);
 assert(num_calls==2 && !calls[0].bound && !calls[1].bound);
 // CPU mapping changes must follow the submission's waits.
 struct vk_queue_submit submission={.wait_count=1,.image_bind_count=1,.image_binds=&bind};
 num_calls=0; wait_result=VK_TIMEOUT;
 assert(radv_queue_submit_bind_sparse_memory(&device,&submission)==VK_TIMEOUT);
 assert(waits==1 && num_calls==0);
 wait_result=VK_SUCCESS;
 assert(radv_queue_submit_bind_sparse_memory(&device,&submission)==VK_SUCCESS);
 assert(waits==2 && num_calls==2);
 // Failure on row two leaves row one applied: no transactional rollback can be assumed.
 num_calls=0; fail_call=2;
 assert(radv_sparse_image_bind_memory(&device,&bind)==VK_ERROR_OUT_OF_DEVICE_MEMORY);
 assert(num_calls==2); fail_call=0;
 // Per-layer mip tails use opaque offsets without image-tile reinterpretation.
 VkSparseMemoryBind tail={.resourceOffset=0x3f0000,.size=65536,.memory=(VkDeviceMemory)(uintptr_t)&memory,.memoryOffset=0x20000};
 VkSparseImageOpaqueMemoryBindInfo opaque={.image=bind.image,.bindCount=1,.pBinds=&tail}; num_calls=0;
 assert(radv_sparse_image_opaque_bind_memory(&device,&opaque)==VK_SUCCESS);
 assert(num_calls==1 && calls[0].offset==tail.resourceOffset && calls[0].memory_offset==tail.memoryOffset);
 // Platform range checks, 16 KiB alignment and multi-piece unbind errors.
 struct radv_ps5_memory mem={.physical=0x400000,.bytes=0x400000};
 assert(radv_ps5_vrange_bind((void*)0x1000000,65536,&mem,0x10000));
 assert(maps==1);
 assert(!radv_ps5_vrange_bind((void*)0x1000001,65536,&mem,0));
 assert(!radv_ps5_vrange_bind((void*)0x1000000,65536,&mem,UINT64_MAX));
 assert(!radv_ps5_vrange_bind((void*)0x1000000,UINT64_MAX,&mem,0));
 assert(!radv_ps5_vrange_bind((void*)0x1000000,65536,&mem,1));
 assert(maps==1);
 maps=0; assert(radv_ps5_vrange_unbind((void*)0x1000000,0x410000)); assert(maps==3);
 maps=0; fail_map=2;
 assert(!radv_ps5_vrange_unbind((void*)0x1000000,0x410000)); assert(maps==2);
 maps=0; zero_physical=-1;
 assert(!radv_ps5_vrange_unbind((void*)0x1000000,65536)); assert(maps==0);
 puts("PASS: production RADV RGBA/BC3 layer+mip offsets, edge tiles, opaque tails, unbind, waits, partial failures, PS5 alignment/bounds");
}
