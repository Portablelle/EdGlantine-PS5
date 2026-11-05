// SPDX-License-Identifier: GPL-3.0-only
// Adapted from sainsaji/EVO-PLAYER-PS5 a54dcf516e9cfda4c26d78733bf5ccb8c10e7e0b (GPL-3.0)
// Frozen PS5 ABI; reserved fields retain the reference's meaning and layout.
#pragma once
#include <cstddef>
#include <cstdint>

extern "C" {
typedef struct SceVideodec2DecoderConfigInfo {
    uint64_t size;
    uint32_t resource_type;        /* SCE_VIDEODEC2_RESOURCE_COMPUTE          */
    uint32_t codec_type;           /* SCE_VIDEODEC2_CODEC_*                   */
    uint32_t profile;              /* profile_idc (see above)                */
    uint32_t max_level;            /* see above                              */
    int32_t  max_width;            /* e.g. 1920 (1080p), 3840 (2160p)        */
    int32_t  max_height;           /* e.g. 1088 (1080p padded), 2176 (2160p) */
    int32_t  max_dpb_frames;       /* ProsperoLight: 4                       */
    uint32_t pipeline_depth;       /* ProsperoLight: 1                       */
    uint64_t compute_queue;        /* (uint64_t) handle from AllocateComputeQueue */
    uint64_t cpu_affinity;         /* ProsperoLight: 0x3F (cores 0-5)        */
    int32_t  cpu_priority;         /* ProsperoLight: 700                     */
    uint32_t optimize_progressive; /* ProsperoLight: 1                       */
    uint32_t check_memory_type;    /* ProsperoLight: 0                       */
    uint32_t reserved;
} SceVideodec2DecoderConfigInfo;

typedef struct SceVideodec2DecoderMemoryInfo {
    uint64_t size;
    uint64_t cpu_size;             /* out: map with MapNamedFlexibleMemory prot 0x03 */
    void    *cpu;                  /* in/out: the mapped CPU workspace pointer       */
    uint64_t gpu_size;             /* out: alloc direct, MapDirectMemory prot 0x32   */
    void    *gpu;
    uint64_t cpu_gpu_size;         /* out: alloc direct, MapDirectMemory prot 0x33   */
    void    *cpu_gpu;
    uint64_t max_frame_size;       /* out: bytes for ONE decoded frame buffer        */
    uint32_t frame_alignment;      /* out                                            */
    uint32_t reserved;
} SceVideodec2DecoderMemoryInfo;

typedef struct SceVideodec2ComputeConfigInfo {
    uint64_t size;
    uint16_t pipe_id;              /* ProsperoLight: 0 */
    uint16_t queue_id;             /* ProsperoLight: 0 */
    uint8_t  check_memory_type;    /* ProsperoLight: 0 */
    uint8_t  reserved0;
    uint16_t reserved1;
} SceVideodec2ComputeConfigInfo;

typedef struct SceVideodec2ComputeMemoryInfo {
    uint64_t size;
    uint64_t cpu_gpu_size;         /* out from Query; caller 16K-aligns and re-stores
                                      the aligned value before AllocateComputeQueue */
    void    *cpu_gpu;              /* in: direct memory mapped prot 0x33 */
} SceVideodec2ComputeMemoryInfo;

/* Only used by sceVideodec2MapDirectMemory (an alternative to the split
 * gpu/cpu_gpu maps above). ProsperoLight does NOT use it — it maps the two
 * regions itself and passes them in DecoderMemoryInfo. Kept for completeness. */
typedef struct SceVideodec2DirectMemory {
    uint64_t size;
    uint64_t allocation_size;
    void    *address;
    int64_t  direct_start;
} SceVideodec2DirectMemory;

typedef struct SceVideodec2InputData {
    uint64_t size;
    void    *au;                   /* one Annex-B access unit (SPS+PPS+slice...) */
    uint64_t au_size;
    uint64_t pts;                  /* presentation ts, arbitrary units          */
    uint64_t dts;                  /* ProsperoLight: UINT64_MAX ("unknown")     */
    uint64_t attached;             /* ProsperoLight: 0                          */
} SceVideodec2InputData;

typedef struct SceVideodec2FrameBuffer {
    uint64_t size;
    void    *buffer;               /* in: one slot of the frame pool (max_frame_size) */
    uint64_t buffer_size;          /* in: that slot's size                            */
    uint32_t accepted;             /* out: non-zero once the decoder took the slot    */
    uint32_t reserved;
} SceVideodec2FrameBuffer;

typedef struct SceVideodec2OutputInfo {
    uint64_t size;
    uint8_t  valid;                /* out: 1 => `buffer` holds a decoded picture */
    uint8_t  error;                /* out: 0 => no error                        */
    uint8_t  picture_count;        /* out: 1 for a normal frame                 */
    uint8_t  padding;
    uint32_t codec;                /* out: echoes codec_type                    */
    uint32_t width;                /* out: luma width  (e.g. 1920)             */
    uint32_t pitch;                /* out: luma stride in SAMPLES (e.g. 2048)  */
    uint32_t height;               /* out: luma height (e.g. 1088)            */
    uint32_t reserved;
    void    *buffer;               /* out: NV12 (or P010 for Main10) planes;
                                      points inside the FrameBuffer slot        */
    uint64_t buffer_size;          /* out                                       */
    uint32_t frame_format;         /* out                                       */
    uint32_t pitch_bytes;          /* out: pitch in bytes (== pitch*2 for P010) */
} SceVideodec2OutputInfo;

// Imports of the firmware module: the app links tools/stubs/libSceVideodec2.c for them.

int32_t sceVideodec2QueryComputeMemoryInfo(SceVideodec2ComputeMemoryInfo *memory);

int32_t sceVideodec2AllocateComputeQueue(const SceVideodec2ComputeConfigInfo *config,
                                         const SceVideodec2ComputeMemoryInfo *memory,
                                         void **compute_queue);
int32_t sceVideodec2ReleaseComputeQueue(void *compute_queue);

int32_t sceVideodec2QueryDecoderMemoryInfo(const SceVideodec2DecoderConfigInfo *config,
                                           SceVideodec2DecoderMemoryInfo *memory);

int32_t sceVideodec2CreateDecoder(const SceVideodec2DecoderConfigInfo *config,
                                  const SceVideodec2DecoderMemoryInfo *memory,
                                  void **decoder);
int32_t sceVideodec2DeleteDecoder(void *decoder);

int32_t sceVideodec2MapDirectMemory(void *decoder, const SceVideodec2DirectMemory *memory);

int32_t sceVideodec2Reset(void *decoder);

/* Submit one AU. output->valid==0 with rc==0 means "buffered, call Flush". */
int32_t sceVideodec2Decode(void *decoder,
                           SceVideodec2InputData *input,
                           SceVideodec2FrameBuffer *frame,
                           SceVideodec2OutputInfo *output);

/* Drain a buffered picture (and at end-of-stream). */
int32_t sceVideodec2Flush(void *decoder,
                          SceVideodec2FrameBuffer *frame,
                          SceVideodec2OutputInfo *output);

}

static_assert(sizeof(void*) == 8);
static_assert(sizeof(SceVideodec2DecoderConfigInfo) == 72);
static_assert(offsetof(SceVideodec2DecoderConfigInfo, compute_queue) == 40);
static_assert(offsetof(SceVideodec2DecoderConfigInfo, check_memory_type) == 64);
static_assert(sizeof(SceVideodec2DecoderMemoryInfo) == 72);
static_assert(offsetof(SceVideodec2DecoderMemoryInfo, max_frame_size) == 56);
static_assert(offsetof(SceVideodec2DecoderMemoryInfo, frame_alignment) == 64);
static_assert(sizeof(SceVideodec2ComputeConfigInfo) == 16);
static_assert(sizeof(SceVideodec2ComputeMemoryInfo) == 24);
static_assert(sizeof(SceVideodec2DirectMemory) == 32);
static_assert(sizeof(SceVideodec2InputData) == 48);
static_assert(offsetof(SceVideodec2InputData, pts) == 24);
static_assert(sizeof(SceVideodec2FrameBuffer) == 32);
static_assert(offsetof(SceVideodec2FrameBuffer, accepted) == 24);
static_assert(sizeof(SceVideodec2OutputInfo) == 56);
static_assert(offsetof(SceVideodec2OutputInfo, codec) == 12);
static_assert(offsetof(SceVideodec2OutputInfo, buffer) == 32);
static_assert(offsetof(SceVideodec2OutputInfo, pitch_bytes) == 52);
