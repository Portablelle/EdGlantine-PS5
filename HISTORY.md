# EdGlantine-PS5 history

Earlier milestone notes, moved from the README. They describe each change as it was at the time; the current state is in [README.md](README.md), and measurements are in [TEST-REPORT.md](TEST-REPORT.md).

## EglantinePS5 adaptations — 00.040.000

Three adaptations from `heydemoura/EglantinePS5` (`a2c5a908`): Vulkan staging buffers
rounded in 16 MiB increments above 16 MiB, reuse based on actual capacity, and release
of completed/non-deferred buffers only before retrying an out-of-memory allocation;
one-time reporting of auto-stubbed commands per service/command without broadening
the existing response policy; heap commitment using progressively smaller physical
blocks down to 2 MiB, with full rollback on partial failure and preserved virtual
continuity.

Run targeted tests with `bash tests-nx2/run-eglantine-three.sh` on the build server.
Host validation does not reproduce the PS5 driver. No FPS/memory gain or fix for
the black counter is claimed. BCn mip trimming is not imported.

## Memory/readback source integration — not deployed

The source includes targeted adaptations from Eglantine and mucahidkambur's fork:
unbacked-image accounting, saturated deletion/GC counters, per-heap VRAM budget
accounting, and CPU readback of NX2 GPU-written buffers on the PS5 slow read path.
Pages first consumed by the CPU participate in later fence downloads; mixed
texture/buffer reads cannot skip dirty buffers. PS5 shared-pool accounting and
the existing ASTC policy are preserved. See the [integration and validation notes](milestones/memory-readback/README.md).
Native compilation/link, integrated checks and targeted ASan/UBSan tests passed
on `dedie`. No new console performance or rendering result is established.

## Completed validation

PS5 RADV/OpenGL linking, package inventory, imports, SELF alignment and separate
title identity checks pass. Inherited loading, memory, CPU JIT, diagnostic and GPU
thread lifecycle tests passed after their expectations were adapted to six cores
and the new NX2 calls. Dedicated tests cover concurrent deferred writes across six
cores, exclusive accesses, inclusion of the NX2 MME JIT and its PS5 allocator in
the binary, and path isolation. The 20 GiB reservation test with 6 MiB actually
committed uses Linux backing, not PS5 memory APIs.

MME build logs are in `artifacts/mme-jit/`. The graphics milestone predates compute
activation; its patch is retained in `milestones/graphics-mme.diff`.
`package.log` corresponds to the final graphics + compute build.

## Eglantine fixes — 00.032.000

The shader compiler pool now destroys each constructed object rather than its
empty storage union (`59047f0`). Undefined SPIR-V U1/U32 registers default to
false/zero to avoid the stray colors observed on AMD in Eglantine (`bb35360`).
Other types are unchanged.

To disable the AMD fix on PS5, create the empty file
`/data/eden-nx2/undef-zero-off.txt`, then fully close and relaunch the application.
Deleting it and relaunching re-enables the fix. Setting `EDEN_NX2_UNDEF_ZERO=0`
before startup also disables it. The choice is fixed for the process and logged.
Vulkan cache versions 38 (enabled) and 39 (disabled) replace version 37; switching
modes rejects the old cache. The native translator salt becomes
`0x4f554e4345a00006`. No memory/FPS gain or PS5 visual fix has yet been measured
for this change.

## Eglantine and gather integration — 00.008.000

Eglantine reference: `b40ad217ab829226841cb71f6e4c5cb05977a225`.
Fixes include page runs after remapping, rejection of truncated Vulkan caches,
NX2 docked/handheld notifications, dump metadata, decoding only modified ASTC
layers and releasing large CPU scratch buffers. The ASTC path reuses our page
tracking; `tex_partial=off` retains the full-upload fallback. Selective sparse
residency and FSR3 frame generation are not enabled.

Atomic cache writing was already present in the PS5 generator; it is retained
alongside the new read validation. The fork's RET tests are adapted to our existing
linkage checks without relaxing them. See the
[integration inventory](milestones/eglantine-update/README.md).

The gather fix and identification of the video PANIC are documented in
[milestones/gather-panic/ANALYSIS.md](milestones/gather-panic/ANALYSIS.md).
The subsequently identified Welcome Tour request is H.264, not VP8; its
initialization has been fixed since .009.

## Experimental sparse management — 00.006.000

The sparse-layer backend is integrated but disabled by default. Opting in with
`EDEN_NX2_SPARSE_LAYERS=1` uses per-layer allocations, all resident before
publication, and GPU waits before binding/release. Budgets are 64 MiB per image
and 128 MiB in total; unsupported layouts fall back to ordinary images. If GPU
completion is uncertain, allocations are retained and the error is propagated
without unsafe release.

There is no selective layer eviction or measured memory gain yet.
See `milestones/sparse-layers/README.md` for guarantees, tests and limitations.

## Shader fixes — 00.005.000

Barrier cancellation and loop exits require proof of the exit path; WARPSYNC must
match its reconvergence point. Newly supported forms (RZ vector stores, zero-LOD
cube-array sampling, RED MIN) are checked through their IR or results while
retaining invalid variants. See `milestones/shader-fixes/ANALYSIS.md`.
No shader tests are excluded.

## Eden-NS2 integration — 00.004.000

Imported revision: `e2f285ab1ecd3a2475c2ccad66f23b06b94ead5c` from
[0x2593/Eden-NS2](https://github.com/0x2593/Eden-NS2). The merge inventory and
previous prototype snapshots are in `milestones/ns2/`.

Engine changes include native shaders, GPU descriptors and buffers, texture
streaming and bounded transfers, and associated NX2 services (guest clock, audio,
video and graphics supervisor). PC/Android frontends and the Windows change to
`vfs_real.cpp` are not imported. The AV1 decoder libgav1 is pinned to
`c1deec657b32b911920c78e078cfd089faa77200` and uses standard mutexes, with examples
and external tests disabled.

PS5 source generation preserves the new deferred-pipeline and buffer-batching
paths. Partial-page tracking comes from NX2: the old PS5 tracker is not layered
on top, preventing double decrements of page counts. `tex_partial=off` still
forces full transfers; the old `tex_partial_check` counters/checkers no longer
measure this path. PS5 memory thresholds and native allocations are preserved;
the desktop fallback to another host-memory class is not enabled. GPU splitting
remains excluded in this milestone.

Six guest application cores retain their identities; virtual cores 6, 7 and 63
map to system core 3. The old modulo-six SVC fallback was removed: it contradicted
the virtual table, lost bit 63 and could turn an invalid Switch 1 identifier into
an accepted one. Validation uses the original identifiers and masks; physical
translation stays in the kernel. Core limits and clock units exposed to legacy
processes remain distinct. A dedicated test checks translations and six-core
write queues under ASan/UBSan.

`tests-nx2/build-ns2-host.sh` compiles engine tests in a separate Linux build using
an independent copy of the prepared sources. Hidden commercial-capture tests are
not enabled. Host validation does not replace execution on PS5.

## Eglantine contributions in 00.004.000

Examined revision: `6f5e137ec4eb83bbff9ea15f1ad1a8407cfc0cba`,
[Djihads80/Eglantine](https://github.com/Djihads80/Eglantine).
Two adaptations are retained: empty statistics before initialization and batched
large GPU-page notifications (small pages were already batched). QMD cleanup
inspired by `6e7edd7` was rejected: the native_semaphore suite shows that deleting
history replays a completed descriptor on action 2. Eden-NS2 preserves that history.

Dedicated tests execute the real table-update methods with a recording backend
and the real QMD scheduler under ASan/UBSan: empty, unchanged, disjoint and long
ranges; preservation of completion history and dependencies. They do not simulate
the graphics driver.

Per-layer sparse residency is tracked in [ROADMAP.md](ROADMAP.md). Selective
residency remains to be ported (per-layer ASTC uploads are integrated in 00.008):
these changes couple the Vulkan allocator, driver capabilities, GPU block tracking
and ASTC uploads. Desktop figures published in commits are not PS5 measurements.
GPU splitting, MoltenVK adaptations and SDL frontend changes are not imported
in this milestone.

## ARM caches and six-core placement — 00.003.000

`eden/headless/cpu_policy.h` sets 256 MiB for guest core 0 and 96 MiB for each of
cores 1–5, for both ARM64 and ARM32. Total: 736 MiB per active architecture,
compared with 688 MiB in the previous prototype (+48 MiB capacity). Instances
outside the six cores remain at 16 MiB and the null JIT at 8 MiB. The existing
allocator retains progressive allocation where supported by the backend. These
budgets are a starting point, not an optimization measured in a game.

Placement probes allowed CPUs with CPUID and verifies each affinity change.
It requires seven distinct physical cores for the six guest CPUs and GPU.
Auxiliary tasks use an additional physical core if available, otherwise guest
CPU SMT siblings; the GPU's SMT sibling is excluded. Known threads `HostTiming`
and `VSyncThread` follow the same rule, even when created by an already pinned thread.

Hidden, inconsistent or insufficient topology, or a rejected probe, leaves
placement to the OS. The old timing test on only three CPUs no longer infers a
complete topology. If an individual pin is rejected, the thread attempts to
restore the process's original mask. No hardware layout of the user's console
was assumed or queried.

Logs for this version are in `artifacts/six-core-cpu/`.
`tools/check-worker-affinity.py` executes production code with simulated native
APIs: seven workers, APIC/CPU permutations, inherited masks, extra CPUs, exclusion
of the GPU sibling, rejection and verified restoration. Checks of both generated
wrappers ensure they use the common policy while retaining the small null-JIT
cache. Targeted CPU diagnostics now accept cores 0–5 and identify the GPU separately
(index 6).

## MME port

`core/src/video_core/macro_jit_ps5_allocator.h` uses the port's direct-memory
functions: an RW/NX view and an RX view. The adapted Xbyak retains RX addresses
for labels and jump tables and writes through the RW view, including during growth.
There is no fallback to a writable/executable desktop mmap. Each buffer is limited
to 16 MiB; all buffers together are limited to 64 MiB, excluding metadata and
header pages and including replacements in progress.

A program is published only after generation and relocation finish. Allocation
or mapping failure selects the non-JIT path for that macro generation. It is not
retried until a new generation or instance. An error after execution begins remains
an error: already emitted commands are not replayed. The GPU remains the sole
execution owner; split-front remains excluded in this milestone.

`tests-nx2/run-mme.py` compiles differential tests against the real interpreter
on the dedicated server: arithmetic, branches/loops, register reads, MME RAM
reads/writes, callbacks, reallocating FIFO, errors, AutoGrow with relocated tables,
generation invalidation, allocation/alias rejection, limits and release. The test
backend uses real Linux RW/RX mappings; it does not simulate full game execution
or PS5 hardware.

The symbol-bearing binary and link map remain in the dedicated server's isolated
cache (`cache/ps5-eden-headless.c9cb1134b201/native-local/bin/`) for future diagnosis.
