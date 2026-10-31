# Welcome Tour: bounded video and Vulkan measurements

Reference: installed .009 runs at 6.9–8.5 FPS after video initialization.
A confirmed global 0.5x setting reduces cached images from 192 to 48 MiB but
produces 6.9–8.2 FPS. This excludes a simple resolution-dependent fill-rate
explanation; it does not establish a CPU/video or synchronization bottleneck.

.010 preserves decoding, conversion, swizzle, writes and synchronization.
`NX2_VIDEO_PERF` reports cumulative wall nanoseconds every 30 output frames,
up to 24 reports per codec. Stages: packet preparation, avcodec_send_packet,
avcodec_receive_frame, plane allocation/copy, output allocation, conversion,
swizzle, invalidation and guest write. These stages do not overlap. AV1 decode
is not timed by the H.264-specific packet/decode/receive counters.
`NX2_GPU_PERF` / `NX2_VK_PERF` report cumulative existing performance counters
at most 24 times at five-second intervals while the GPU HUD is queried.
API indices 2/3/4/5 mean queue submit / fence wait / semaphore wait / device idle.
API time can overlap between threads and must not be added as frame time.
Existing `EDEN_VULKAN_FRAME` provides five-second FPS windows.
GPU timestamps include intra-command-buffer waits and are not ALU utilization.

For comparison, keep the 0.5x setting, same game/scene and HUD enabled; capture
at least 60 seconds after video initialization. Derive differences of cumulative
counters, never divide startup totals by the final frame count indiscriminately.
No performance gain is claimed for this measurement build.

## .010 console baseline (2026-10-31)

Boot trace confirms .010, 0.5x remains active. Warm interval, decoded/output
frames 90..570 (480 frames), 3840x2160, RGBA rather than NV12:

| Stage | Wall ms / output frame |
| --- | ---: |
| Packet preparation | 0.031 |
| H.264 send/decode | 25.724 |
| Receive | 0.017 |
| Plane allocation/copy | 1.915 |
| Output allocation | 1.785 |
| YUV709 → RGBA | **96.176** |
| Swizzle | 6.772 |
| Invalidation | 1.322 |
| Guest-memory write | 4.271 |

Warm presentation windows remain about 6.8–7.2 FPS. The conversion is therefore
an observed dominant cost, not an inference from video startup. Representative
five-second Vulkan deltas show only ~20 ms total submit CPU time, ~19 ms semaphore
wait time and ~0.1 ms fence wait time. Dispatch time is zero because this release
path does not collect it; zero must not be interpreted as no dispatch work.
Raw private captures and the derived JSON are under the workspace backups
`nx2-video-performance-20261031/run-010-final/`.

## .011 change and targeted validation

SSE2 row conversion processes four pixels together, retaining the original float
operation order. Channels clamp to [0,255], truncate, then compare the fractional
part to 0.5. This preserves lround's ties-away result without a scalar library
call per channel, and avoids the near-half rounding error of simply adding 0.5.
The original scalar helper handles non-SSE2 targets and the row tail.
No decoder, image geometry, swizzle, guest-memory or synchronization change.

On build-server, `conversion-test.cpp` compiled with Clang 21, -O3 and ASan/UBSan compares
all 16,777,216 Y/U/V combinations in each range: **33,554,432 exact pixel matches**.
Widths 0..19 test exact-sized chroma planes, odd tails and guarded unaligned output.
Synthetic 3840x2160 host benchmark: scalar 223.147 ms, SIMD 22.962 ms per frame,
matching sampled checksums. This is a Linux host measurement, not a PS5 gain.

Native rebuild updates only the two changed production files in the already
prepared source tree and its patch identity, then invokes build-headless-native;
no source re-extraction or full desktop test suite. Packaging reuses that binary.
PS5 .011 boot confirmed. Matching output frames 90..570: conversion 21.148 ms/frame
versus 96.176 (4.55x faster), decode 25.607 versus 25.724, swizzle 6.741 versus
6.772, write 4.161 versus 4.271. Output cadence 14.957 versus 7.037 fps (2.13x);
presentation warm windows about 14.2–15.6 FPS, returning to 59.94 FPS at menu.
User confirms the video image appears correct. User also reports regular black
flashes at menu and severe black areas/misplaced sprites after confirmation.
At 118 s, native texture shader rejection starts in the .011 logs; this blocks
overall graphics acceptance. It does not invalidate the measured conversion
speedup, and the FPS counter alone must not imply correct rendering.
`analyze.py` computes differences over the matching 480-frame interval.
