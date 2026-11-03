# EdGlantine-PS5

EdGlantine-PS5 is an experimental PS5 port based on ProsperoEden and the Eden NX2
engine, with adaptations from the Eglantine forks. It reaches gameplay in tested
scenarios, but performance, rendering correctness and stability still need work.

**Contributors welcome.** On version **00.065.000**, both Welcome Tour and Pokopia
reach gameplay. Welcome Tour regressed to about **8 FPS**, versus **21 FPS** on
.064. Pokopia reaches about **45–51 FPS**, but the user reports temporary freezes
and extensive flickering. These are experimental results, not stable compatibility.
Help with profiling, CPU/GPU optimization, memory synchronization and PS5 testing
would make a real difference. See [Contributing](#contributing) below.

## Current state

- **Installed build: 00.065.000.** Adds controller selection of folder dumps in
  the library and the homescreen name **EdGlantine PS5**. The library scan is
  independent of key/firmware setup; validated decrypted dumps can be selected
  without container keys, while NSP/XCI launches retain the setup requirement.
  NX2 dumps select the 12 GiB layout before device-memory construction; sparse
  page returns are bounded to the actual reservation. The focused bounds regression
  passed under ASan/UBSan on the dedicated host; the user confirmed both games
  start on PS5. Targeted dump-library tests and package checks passed. Includes
  the source fixes listed below. The DMA setting now also controls deferred CPU
  writes, rather than forcing the unsafe path for every NX2 title. Rendering
  with default DMA and full ASTC textures still flickers. A video confirms that
  meshes intermittently appear at other objects’ positions. The unaligned-uniform
  streaming fallback now synchronizes GPU-written constants before copying them
  through CPU memory; a regression test reproduces the old stale read and verifies
  graphics/compute binding paths under ASan/UBSan. The console retest still
  flickers at about 50.8 FPS, with no alignment-sync activations or logged shader
  compilation/Vulkan errors. A separate opt-in diagnostic reads
  `/data/eden-nx2/gpu-sync-diagnostic.txt` containing `syncshaders` before Vulkan
  initialization and logs `NX2_GPU_SYNC_DIAGNOSTIC ... applied=1` when the driver
  flag is set. Remove the file and restart the app to restore normal scheduling.
  Console retest confirmed the opt-in marker, 49.22 FPS over 60.17 seconds,
  no logged shader compilation/Vulkan errors, and unchanged asset flicker.
  Shader serialization alone did not fix the defect; it does not exclude all
  cache visibility, shader translation, or draw-state errors. The diagnostic
  has been disabled after this unsuccessful A/B test.
- **Previous performance baseline: 00.064.000.** Shares CPU preparation of texture tables and sampled
  descriptors within each stage. It preserves the .063 page batching, memory-owner
  and texture-stride fixes. The build and targeted tests passed on the build server;
  the user also confirmed testing on PS5. The 20.093-second console capture records
  8.492 seconds of CPU draw configuration and 54,383,256 sampled-descriptor cache
  hits out of 54,861,363 requests. Texture-table counters remained at zero.
  The user confirmed 21 FPS; full rendering validation is not recorded.
- **Source fixes since the tested .064 package:** publication review addressed
  shader-register preservation, memory-cache coherence, profiling and observer
  lifetimes, and remote build reliability. See [CUBIC-REVIEW.md](CUBIC-REVIEW.md)
  for the fixes and targeted tests. These changes are included in .065, but are not part of the PS5-tested
  .064 binary.
- **Current gameplay observations (.065):** Welcome Tour reaches 7.6–9.3 FPS in
  the last measured intervals. Pokopia reaches 45–51 FPS with temporary stalls;
  the user reports extensive flickering. Neither title is validated as stable.
  GPU splitting remains disabled. Comparison with .064 still requires matching
  scenes and effective settings.
- **Measured bottlenecks:** a 20.112-second .063 solo capture recorded 8.650 seconds
  of CPU draw preparation/configuration, including 3.731 seconds of descriptor
  work and 2.812 seconds of resource reads. These phases are nested and must not
  be added together. GPU command-buffer timestamps covered 5.765 seconds; this
  does not measure total GPU utilization.
- **Experimental GPU splitting:** available but disabled at startup. Explicit
  activation has caused freezes. The latest split investigation (.062) still
  observed a semaphore at 29,222 while waiting for 29,226; ordered DMA snapshots
  did not resolve it. No performance gain from splitting is established.
- **Validation limits:** targeted host tests and native build checks pass for recent
  changes, but do not establish broad game compatibility, long-session stability
  or correct rendering on PS5. The .063/.064 captures may differ in scene activity, so they do not establish
  an isolated FPS gain from the latest optimization.

The current focus is to reduce CPU draw preparation and redundant transfers while
preserving memory correctness, and to diagnose the split-mode freeze before
considering it usable. Measurements and version history are in
[TEST-REPORT.md](TEST-REPORT.md); planned work is in [ROADMAP.md](ROADMAP.md).

The latest installed build includes partial uploads for large textures with sparse
guest mappings, optional native PGO, and a CPU async-texture generation fix.
Native build, ASan/UBSan texture tests, actual PGO-use checks and packaging
passed on the build server. Earlier Bananza tests measured about 10 FPS,
falling to 4 with movement. In the latest player test, **the terrain and assets
appear after a delay; the black areas disappear once they have loaded**.
The remaining observed issue is delayed display, rather than persistent black
terrain. The subsequent Bananza GPU-fast trial, still docked at 1×, measures about
15.8 FPS over 25 seconds, with correct terrain and objects confirmed by the
player. The previous High-accuracy sample measured 8.7 FPS; the scenes are not
strictly paired, so an isolated gain is not established. See the
[partial-texture/PGO integration](milestones/partial-textures-pgo/README.md) and
[Bananza investigation](eden/docs/BANANZA_STARTUP_INVESTIGATION.md).

The installed performance update also adapts ideas from nxnative and selected
Eden nightly changes: coherent reuse of gathered SSBOs, fewer read-only binding
allocations, a better JIT constant pool, and contained texel-buffer and VP9 fixes.
The initial batch caused a startup crash when its constant store bypassed the
PS5 writable-alias adapter. The adapter is fixed, and the player confirms
Bananza starts. A targeted indirect-record initialization treatment is also
installed, with a corrected work budget for larger streamed terrain lists and
specific rejection diagnostics. Its contribution to the delayed appearance of terrain is not yet
established: the log snapshot taken before the terrain appeared contained no
activation marker. Installation changed only eboot.bin, with rollback retained
and game data preserved. Validation and provenance:
[upstream performance adaptations](eden/docs/UPSTREAM_PERFORMANCE_ADAPTATIONS.md).


A further Eglantine performance candidate reduces empty-stage buffer work and
eager initialization of fiber stacks/descriptor storage, and reclaims old costly
textures under memory pressure. It retains the current coherent command reader
and PS5 memory thresholds. See the [batch scope and validation](milestones/eglantine-performance/README.md).
No PS5 performance improvement is established yet.

A subsequent [coherence and memory batch](milestones/eglantine-refresh/README.md)
protects newer writes from pending GPU copies, handles fragmented scalar memory,
reduces descriptor and shader-cache work, and prioritizes less occupied texture
allocation blocks. It preserves the PS5 memory and synchronization policies;
console performance and rendering require player validation.


## Contributing

Please help make EdGlantine-PS5 faster and more stable. Contributions can be code,
reproducible measurements, debugging findings or documented PS5 tests.
Useful areas include:

- **CPU draw preparation:** descriptor setup, shader-resource lookup and SSBO
  binding, guided by the measured costs above.
- **GPU transfers and synchronization:** reduce redundant gather/scatter copies
  and readbacks while preserving dirty-range tracking, ownership and ordering.
- **GPU split stability:** trace semaphore producers, command submission and
  decoding to identify why progress stops after activation.
- **Rendering and regression tests:** small reproductions for texture/shader
  issues, focused tests of affected production paths and checks on real hardware.

Open an issue with the build version, hardware/software environment, settings,
reproduction steps, scene and measured FPS/frame times. For performance changes,
compare the same scene and settings before and after, and state whether rendering
or stability changed. Include relevant sanitized logs; do not attach games,
keys, proprietary SDKs or personal information.

Pull requests should explain the problem, the change and the validation performed.
Keep changes focused, credit upstream work with repository/commit links, and
preserve its license notices. Follow the remote build workflow below and run the
targeted tests relevant to your change. Host-test success alone is not a PS5
performance result; identify untested hardware behavior clearly.

## Credits

EdGlantine-PS5 builds on the work of these projects and their contributors:

- [ProsperoEden](https://github.com/blackbearreloaded/ProsperoEden): the PS5 port, native application wrapper, build infrastructure and platform adaptations used as the foundation of this project.
- [Eden NX2](https://git.eden-emu.dev/Takoroka/eden-nx2): the experimental NX2 engine on which the initial prototype was based.
- [Eden-NS2](https://github.com/0x2593/Eden-NS2): native shader support, GPU descriptors and buffers, texture streaming, and NX2 services integrated into this prototype.
- [Eglantine — Djihads80](https://github.com/Djihads80/Eglantine): GPU page tracking, ASTC layer uploads, cache validation, shader fixes and research into sparse texture residency.
- [Eglantine — zortos293](https://github.com/zortos293/Eglantine): partial-page batching, memory-owner tracking and texture layer/row stride fixes integrated in 00.063.000.
- [EglantinePS5 — heydemoura](https://github.com/heydemoura/EglantinePS5): the basis for staging-buffer sizing and reuse, one-time service-command reporting, and fragmented heap commitment adaptations.

Exact revisions and adaptation details are recorded in `prototype.json` and the
milestone documents. Original copyright notices and third-party licenses are
preserved in the source tree. These credits do not imply upstream endorsement.

## Repository and runtime layout

Builds run on the remote build server, with targeted tests and incremental changes.
Sources and patches are versioned; packages, dumps, games, keys, SDKs and reference
working copies remain local.

- Title: `PPSA99862` — **EdGlantine PS5**.
- Data, saves, configuration and caches: `/data/eden-nx2`.
- Folder dumps: `/data/eden-nx2/roms/<Game>/exefs/main`, alongside `main.npdm`,
  the other ExeFS modules and the same game's `../romfs` directory.
- The controller frontend opens at startup. Choose a game in Library and press Cross;
  explicit `--rom` launches remain supported. Each folder dump has its own NPDM title ID.
- The library lists complete ExeFS/RomFS folders and ordinary NSP/XCI entries. Hidden
  upload folders and incomplete dumps are omitted; folder dumps are managed in storage.
- Graphics and compute NX2 MME JIT enabled; legacy Maxwell macro JIT disabled.
- Experimental GPU thread splitting inactive by default; six-core + GPU placement
  applies only if the topology is validated.
- Self-update disabled; no self-replacement payload included.

Exact references are in `prototype.json`. `eden/` contains the PS5 port, adaptations
and tests. `eden/tools/eden-patches/90-nx2-prototype.diff` applies after the four
original source patches to the pinned Eden core. `core/` is the expanded working
copy of that core, not another installed engine.

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

## Building

All configuration and compilation, including shaders and C++ tests, run on the
remote Linux build server, never on the Mac. Configure the SSH destination in a
local file excluded from Git:

```sh
mkdir -p .local
cat > .local/remote-build.env <<'CONFIG'
EDGLANTINE_BUILD_HOST=build-server
EDGLANTINE_REMOTE_ROOT=/tmp/edglantine-ps5-build
CONFIG
```

`build-server` is an example alias; replace it with your Linux server.
The remote directory must contain the prepared dependencies and is mounted as
`/work` inside the container. `build-remote.sh` synchronizes this project there.
After building, `bash package-remote.sh` creates the title directory, reuses the
compiled binary, checks package isolation and retrieves the archive into
`artifacts/`. Neither script contacts the console.
`make install` is disabled in this project.

The source cache includes the NX2 patch hash: changing the patch recreates the
prepared core and reapplies the PS5 patches before reconfiguration. Dependencies
and flags come from ProsperoEden and are pinned in `eden/tools/deps.json`.
A copy of the original wrapper archive is retained in `sources/`.

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

## Limitations

A successful build does not validate a game. NX2 services remain partly simulated,
and graphics stages not implemented by the fork remain unavailable. The guest
layout reserves 12 GiB plus 8 GiB for the graphics server; PS5 on-demand backing
is retained, but actual memory use still needs measurement on the console.
PS5 shared-pool cache thresholds are preserved. The inherited HUD still shows
four CPU-load columns; the engine, its queues and internal counters have been
adapted to six cores.

Package files must only be installed under this project's separate title identity,
`PPSA99862`. The 00.007.000 update preserved its registration; the system entry
could still show 00.006.000. The earlier package record listed 00.031.000; consult
`prototype.json` and the current status above for the installed version and retained rollback.

## Pokopia rendering investigation

Read the [record of completed experiments](eden/docs/POKOPIA_RENDERING_INVESTIGATION.md)
before choosing another diagnostic. It records unsuccessful settings and fixes,
FPS measurements, capture limitations, evidence locations and remaining questions.
Do not repeat an unchanged negative experiment without new evidence.

The FSEL semantic fix is active, but flickering and the black sky remain unresolved.
Both `syncshaders` and `fullsync` were tested without visual improvement; fullsync
reduced performance and has been disabled for subsequent full app launches.
The installed capture build supports main-viewport filtering, full descriptor
snapshots and absolute paths for auxiliary requests; see the investigation record
for the protocol and its limitations.

## Bananza startup investigation

See the [startup failure record](eden/docs/BANANZA_STARTUP_INVESTIGATION.md).
The record distinguishes earlier file-open exhaustion, guest null accesses,
CRAM write retries and the corrected JIT startup crash. Bananza now starts;
the player confirms terrain and assets appear after a delay and the black areas
disappear. The delay and low frame rate remain under investigation.
