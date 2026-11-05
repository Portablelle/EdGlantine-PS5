# 00.066.002 — Lichii ports, Welcome Tour, November 5, 2026

Test build of `main` after #36 plus #37: Lichii's Ampere GPU timestamps in
nanoseconds, the continuous-range cache, no upload of a target the clear
overwrites, the occlusion counter pausing instead of resetting, the alpha-ref
pipeline key and exact Preflushable downloads. It was installed over FTP:
70 files, and `param.json` reads 00.066.002. 00.066.001 was installed before
it without #37.

**Welcome Tour, as reported by the player: 8–20 FPS, about 15 on average.**
The previous report was about 10 FPS, so this is better, but the scenes and
runs are not the same, and this is not an A/B on one binary.

Counters from the 50 s of the session's `stderr.log` that follow loading
(19 windows of about 5 s, logs in `artifacts/lichii-perf-002/logs/`):

- **GPU thread:** 27,421 draws/s and 511 ms/s in `draw`. The finer phases are
  not measured in this build.
- **Host GPU:** busy 243 ms/s, fence drains 117 ms/s and queue wait
  17 ms/s. The host GPU is not what limits the frame rate.
- **Draw memo:** hits on 4.70 of 4.79 M requests/s, and the resource memo on
  4.76 M of them.

The hardware video decoder did not load:
`EDEN_HW_VIDEODEC module-load rc=0x80020002 path=/system/common/lib/libSceVideodec2.sprx`.
The file is on the console, but the app's sandbox cannot see that path, so
videos go to FFmpeg. Nothing shows that this costs gameplay FPS.

---

# Bananza startup hotfix — JIT constant writable alias, November 2, 2026

Initial nxnative/nightly package crashes after 22 seconds, CPUCore_0, before any
draw. Exact ELF: ConstantPool::GetConstant writes protected JIT memory. The port's
CMake alias substitution only recognized the old store and missed the compact one.
The new adapter handles both known forms and fails on missing/duplicate anchors.

ASan/UBSan: original SIGSEGV reproduced with real shared RW/RX mappings; actual
CMake-generated fixed method preserves constant values, RX operand addresses and
protection, plus explicit capacity failure. Native PS5 build/package and header/
isolation checks: PASS on dedie. Cubic: zero findings. User confirmed full closure;
69 companions matched, only eboot.bin replaced with backup. No automatic launch.
Artifacts/journal/exact ELF: `artifacts/upstream-opt-jit-alias-fix/`.
**Installed; console launch, rendering and FPS retest pending.**

---

# nxnative / Eden nightly performance candidate — November 2, 2026

Native PS5 build and package: **PASS** on `dedie`, in an isolated build root.
Coherent reuse of gathered SSBOs and removal of read-only scatter-source
allocations; improved JIT constant-pool lookup; selected texel-buffer
and VP9 backports. Existing PGO, title identity and gameplay settings preserved.

Focused production-method ASan/UBSan tests pass, including real constructed hash
collisions, same-tick post-producer invalidation, read-to-write binding promotion,
constant-pool capacity, viewport boundary continuity, null texel buffers and delayed VP9
metadata. The read-only two-group fixture needs 2 gathers over 1,000 draws;
conservative mode needs 2,000. These are synthetic counts, not a game FPS gain.
The existing real scheduler/upload-guard test passes 262,144 mixed events.
Native sparse/multiplayer header checks and package isolation pass.

Package and exact ELF: `artifacts/upstream-opt-20261102/`.
**Installed after the user confirmed full application closure; no console rendering/FPS result.**
All 69 companion files matched, so only eboot.bin was replaced through verified
staging, preserved permissions and rename, with the prior binary retained.
Journal: `artifacts/upstream-opt-20261102/install-journal.json`. Cubic retry completed without
a subscription error. Its constant-pool finding was addressed with explicit
exhaustion handling and a returning-assertion regression. Its second finding
removed the unvalidated viewport backport because it introduced a coordinate
discontinuity; baseline conversion and a boundary regression are retained. Final
local review: zero findings, no error; repository context unavailable. No push.
[Provenance, limits and deferred candidates](eden/docs/UPSTREAM_PERFORMANCE_ADAPTATIONS.md).

---

# 00.064.000 — CPU resource and descriptor preparation

Incremental build on build-server and PS5 installation succeeded. Base .063
preserved, full .063 rollback retained. Handle tables prepared once per base/size
within each config_stage; root/size reread per descriptor. Resolved sampled
descriptors reused in PushImageDescriptors, complete keys with MAX_VARIANTS policy.
Queue/pointers/rescaling and written images remain processed in the same order.
No state retained across stages/draws; splitting remains disabled by default.

Focused build-server ASan/UBSan test: PASS. Real reference/optimized function and
actual table block extracted. Parameters, edge cases, errors, mapping, collisions
and a fresh call covered, with fake backends; pixels/RADV not validated by this test.
NX2_RESOURCE_MEMO counters added. The user confirmed testing .064 on PS5.
Console capture: 20.093 s, CPU draw configuration 8.492 s, including cfg_desc
3.413 s and cfg_read 2.965 s; push_images 0.723 s. These wall-time counters are
nested and must not be added. Sampled-descriptor memo: 54,861,363 requests,
54,383,256 hits; texture-table counters: zero requests/hits.
The user subsequently confirmed 21 FPS on .064, matching the .063 reference.
No FPS improvement is observed in this feedback. Different scene activity limits the comparison;
no isolated FPS gain or complete rendering validation is established.
Frontend frame dimensions are 1920x1080, with queued output and driver videoout at
3840x2160. The 1080p intermediate is also present in .063 logs and is a plausible
contributor to pixelation, not proof of every internal scene resolution or a .064
regression. Measurement: artifacts/profile-064/measurement.json.
No commit/push/Cubic during the implementation and installation.
Details: artifacts/profile-064/CHANGE.md.

---

# 00.063.000 — Eglantine pages/textures package and installation

The integrated binary was rebuilt on `build-server`: PASS; native and package
checks: PASS. The isolation check was updated for split mode being available but
unarmed at startup (an explicit request is required), without changing that behavior.
70 files were verified in staging in raw SELF mode before activation.
The user confirmed the application was closed. Full installation, without relaunch.
Full 00.062.000 rollback: `/data/ps5-diag/nx2-rollback-062-20261101-eb9d8c35`.
Local journal: `artifacts/00.063.000/install-journal.json`.
Games, saves and settings preserved. User feedback: 21 FPS in game.
Solo profiling (without enabling the split): 20.112 s, CPU draw preparation/configuration
8.650 s, including cfg_desc 3.731 s and cfg_read 2.812 s. Counters are nested;
do not add phase durations. Measured GPU command-buffer timestamps: 5.765 s;
this does not measure total hardware utilization.
Details: artifacts/profile-063-solo/measurement.json. The user did not specify rendering quality.

---

# Eglantine pages/textures integration — November 1, 2026

Three focused adaptations from zortos293/Eglantine (`badc91e`, `11a1108`):
partial-page batching, current ASID ownership, and layer/row strides in texture
transfers. Existing changes were preserved; only three engine-patch sections
were replaced from a saved copy of their current state.

Native PS5 build on `build-server`: PASS; integrated checks: PASS.
Focused tests of the actual methods under ASan/UBSan: PASS (A→B→A, exactly-once
accounting over 2,000 ranges, layers/mips/padding/alignment).
The fixture records decoder calls: it validates transfer parameters, not pixels or RADV.

Three inherited checks were adapted to existing GPU changes (ten workers, loading
hook, split dependencies in waits). The DMA test exposed an obsolete CMake
substitution: the loop could ignore shutdown. The shutdown guard was restored
without removing error checks or NX2 traces; substitution anchors are now mandatory.
The test for shutdown without a signal and backend-error propagation passes.

Binary and logs: `artifacts/eglantine-pages-textures/`.
No deployment, commit or push at this integration stage. Title version unchanged;
no FPS improvement or PS5 rendering result measured for this integration.
Details: [milestone](milestones/eglantine-pages-textures/README.md).

---

# 00.062.000 — native DMA snapshot on the cache owner

Incremental build on build-server and PS5 installation succeeded. In native split
mode, new blocks are copied on the backend after earlier work; exact dirty-range
check, coherent ReadBlock when dirty/safe, Unsafe when clean. Owned buffer retained
when resuming acquire; solo mode and settings unchanged. snapshots/bytes/dirty counters.

Focused build-server ASan/UBSan test using real GpuSplit + production helper: PASS.
Queued write, stale20 versus coherent99; owner, range/neighbors, clean without
readback, forced safe mode, and snapshot stability after mutation. Observer/lifecycle
preserved. The freshness risk is addressed in code; the console freeze cause and
cost remain to be measured.
Console: channel3, current29222 required29226 remained constant over twenty samples.
14 DMA snapshots / 724 bytes, dirty0, no new snapshot after sample1.
Ordered copying does not resolve this observed wait; no dirty header captured.
No FPS gain claimed. No commit/push/Cubic. Details: artifacts/profile-062/CHANGE.md.

---

# 00.061.000 — compute producers and pre-split state

Incremental build on build-server and PS5 installation succeeded. Atomic baseline
since worker startup, serialized before activation. QMD signal/state/planned releases,
native callbacks scheduled (20) then written (21 or 1 for addition). Max releases
and direct reductions are covered without enabling CSV or changing the game.

Focused build-server ASan/UBSan test: PASS. Baseline, QMD signal/state/plan, callback
queue/write, counters, matching and serialization, capture gate, independent file
and lifecycle. Approximate latest values; not all producers are covered.
Console: baseline CPU0x1000 last write14924; after activation, channel3 GEQUAL
minimum14928 but14924 remained constant over twenty samples. Only one additional
request/write, CPU0x2020. Last inspected QMD flags7 (loaded/scheduled/completed),
zero dependencies/deferred; QMD counters unchanged after activation. This does not
prove that all QMDs completed. Expected producer not observed after handoff;
no freeze fix or FPS gain claimed.
No commit/push/Cubic. Details: artifacts/profile-061/CHANGE.md.

---

# 00.060.000 — wait values and release reports

Incremental build on build-server and PS5 installation succeeded. Dedicated observer
extended with channel/ASID/GPU and CPU addresses, current/required values, operation,
polls; native report requests, written, invalidated, unsynced, last report and
GPU/ASID or physical-alias matching. No Matches bypass, CSV activation or extra wait.
Capture limited to twenty independent samples.

Focused build-server ASan/UBSan test: PASS. Real observer + query hook, output read
back, counters and matching, capture disabled, independent file and lifecycle.
Approximate fields and cumulative counters; not all producers are covered.
Console: twenty complete samples, 53,381 polls. Channel 3/ASID 1, GEQUAL GPU
0x11d4940000/CPU 0x1000, constant value 16,953, required minimum 16,957.
No matching report captured; the only request/write was GPU 0x11d4941020,
CPU 0x2020, value 6479. This does not prove the absence of all producers or earlier
releases. No FPS gain claimed.
No commit/push/Cubic. Details: artifacts/profile-060/CHANGE.md.

---

# 00.059.000 — reliable observer output

Incremental build on build-server and PS5 installation succeeded. Dedicated append
file, checked open/write, partial writes/EINTR handled. prepared before creation,
entered at thread entry, then samples/complete and joined on shutdown. Explicit
first-write errors before backend startup; later errors retained.
Startup remains unarmed. The freeze is not claimed fixed.

Focused build-server ASan/UBSan test: PASS. Dedicated output despite fully buffered
and locked stderr, samples read before unlocking, failed open/write, recovery,
append, early stop and restart.
Console: prepared/entered, then twenty samples and complete retrieved. Published/
consumed positions advance at roughly 13k words/s; backend mostly waiting for work,
last callback always ReadNativeSemaphoreWord, symbolized with the exact ELF
(bias 0x400000). No permanent queue lock. Semaphore address, value and release not
captured; the same function does not prove the same address.
No commit/push/Cubic. Details: artifacts/profile-059/CHANGE.md.

---

# 00.058.000 — independent measurement of both workers

Incremental build on build-server and PS5 installation succeeded. Separate native
observer, twenty atomic snapshots at ~1-second intervals, without worker or logger
locks; direct writes to the stderr descriptor. Clean stop/join, new instance on
restart. Unarmed startup; remote activation after launch.

Focused test of the real code on build-server under ASan/UBSan: PASS. Snapshot during
delayed backend callback and frontend drain, then output despite locked stderr FILE
while both workers wait; completion, wakeup, early stop and restart.
Approximate snapshots of latest milestones, without stack or cross-field consistency
guarantees. Console: activation and backend ready, first 32 entries completed,
freeze confirmed. No observer snapshot retrieved after 23 seconds. Raw fd 2 writes
not verified; observer execution/output not established. The host test does not
validate console redirection. Blocked call still unknown; no FPS gain.
No commit/push/Cubic. Details: artifacts/profile-058/CHANGE.md.

---

# 00.057.000 — capture waits after split activation

Incremental build on build-server and PS5 installation succeeded. Bounded trace after
one second of waiting: frontend drain/space, backend idle, last executed entry,
positions and symbolization anchor. DMA waits also reported. No synchronization
bypass; startup remains unarmed.

Focused build-server ASan/UBSan test: PASS. Delayed-callback snapshot, empty backend,
completion and wakeup after timeout, stop and rearm. Unchanged stress tests not rerun.
Console activation confirmed: backend ready and first 32 entries completed.
No drain/space/idle/DMA timeout emitted despite markers in the exact ELF; allocator
logging continues. Blocked call not located. Visual state after activation awaiting
confirmation; no FPS gain claimed.
No commit/push/Cubic. Details: artifacts/profile-057/CHANGE.md.

---

# 00.056.000 — unsplit startup, remote activation in game

Incremental build on build-server and PS5 installation succeeded. Startup on the
single-owner path; explicit arming via split-enable.request once the character is
controllable. Independent profiling marker, arming reset for a new session.
Completion fixes and loading hook preserved.

Focused build-server ASan/UBSan test: PASS. Unarmed startup, explicit activation,
then real-pthread stress, owner, ordering, waits, data, errors and restart.
Console before activation: controllable character, 21 FPS, correct image. After
activation: request consumed, backend ready, first 32 entries completed, then no
new report and unchanged stderr between two captures. User confirmed the freeze;
blocked call beyond the bounded trace still unidentified. No measured gain.
No commit/push/Cubic. Details: artifacts/profile-056/CHANGE.md.

---

# 00.055.000 — loading progress on the render thread

Incremental build on build-server and PS5 installation succeeded. Previous versions
and playable .050 retained. No commit/push/Cubic. Completion fix .054 preserved.

The port had disabled frontend loading without transferring it. The backend now
runs Eden::LoadingTick while waiting, with a 1 ms timeout only during loading.
The frontend does not touch the renderer when split mode is active. After guest
presentation, normal waits resume without loading polling.

Focused test of the real split on build-server under ASan/UBSan: PASS. Deferred
initialization completed by the backend hook without an extra command, owner
verified, plus ordering, wrap, owned payload, offsets, wakeup/error/stop/restart tests.
Native compilation succeeded; unchanged completion test not rerun.
Details: artifacts/profile-055/CHANGE.md. Console result: stuck at 99%, with no new
command after the initial entries completed.

---

# 00.054.000 — fix the acknowledgement / full-queue cycle

Incremental build on build-server and PS5 installation succeeded. Previous versions
and playable .050 retained. No commit/push/Cubic. The blocked .053 callback is
SignalCommand, symbolized with the exact ELF (see profile-053/block-observation.json).

New completion_lock independent of write_lock; the producer releases its lock
after enqueue before waiting for completion. The backend can acknowledge even
when another producer holds write_lock on a full queue.

Build-server ASan/UBSan tests: old cycle reproduced; corrected code passes the full
queue case and 100 completion races. Producer cancellation test against generated
PS5 code: PASS. Native PS5 compilation succeeded. Details: artifacts/profile-054/CHANGE.md.

Console .054: still stuck at 91%. Trace now confirms end=28: SignalCommand returns,
but no new entry follows. The lock fix is retained; it is insufficient for startup.
Vulkan loading progress was disabled on the frontend after split activation without
being transferred to the backend. .055 restores this service on the renderer owner
while waiting before the first frame; the stall cause remains to be confirmed.

---

# 00.053.000 — bounded trace of the first backend callbacks

Incremental build on build-server and PS5 installation succeeded; .052 and latest
playable .050 retained. No commit/push/Cubic. Instrumentation only; native compilation
succeeded, unchanged queue stress not rerun.

Begin/end trace for the first 32 entries, type/position/callback target, exact ELF
relocation anchor. .052 reaches ready and first_batch_words=20 then stalls at 91%:
the problem occurs after backend initialization and wakeup.
Details: artifacts/profile-053/PROFILE.md. Capture .053: entries 0–27 completed,
entry 28 (pos 79, callback) has no exit. Runtime anchor 0x27f1390 / ELF 0x23f1390,
offset +0x400000. Target 0x29d4590 / ELF 0x25d4590 = RunWorker $_4 thunk,
SignalCommand. Exact disassembly confirms the blocking branch under write_lock.
The full-queue test reproduces the old code's locking cycle; .054 separates the
completion lock from the producer lock.

---

# 00.052.000 — blocking waits and backend readiness

Incremental build on build-server and PS5 installation succeeded; rollback .051 and
earlier playable versions retained. No commit/push/Cubic.

Addresses a backend starvation risk: PS5 Drain/space and work waits use
condition_variables after a brief spin, with progress, shutdown and error
notifications. Ready handshake after thread registration, bounded
entry/named/ready/first_batch traces. The .051 stall at 91% remains to be diagnosed
on console; no live stack available.

Focused build-server ASan/UBSan test: PASS. Frontend <20 ms CPU for a backend delayed
100 ms, plus 1.2 M-method stress, wrap, owned payload, offsets, owners, sync, errors,
stop and restart. Native PS5 build succeeded. Host tests do not validate console
startup. Details: artifacts/profile-052/CHANGE.md.

Console .052: stuck at 91% again. entry/named/ready and first_batch_words=20 traces
confirmed: the thread initializes correctly and begins its first sequence. The
stall occurs afterward, not before ready. Exact cause still unknown; changing waits
did not restore startup. .053 adds bounded begin/end traces of initial entries
and callback targets.

---

# 00.051.000 — first PS5 CPU-split port

Incremental build on build-server and PS5 installation succeeded; rollback .050
retained. No commit/push/Cubic. Mode 1 enabled: decoding frontend, engine backend,
PS5 MME JIT, indirect HLE and renderer. Mode 2 frontend-mirror macros not ported.
High GPU accuracy and owned command snapshots preserved; semaphore/fence reads on
the backend, GEQUAL High ordering preserved. SSBO shortcut removed.

PS5 pthread backend, 1 MiB stack, consistent global guard, owner checks, exception
propagation, normal drain and join. Placement on a spare physical core when one is
available in the verified topology; fallback permitted otherwise. Frontend animation
suspended once the backend owns the renderer.

Focused build-server ASan/UBSan tests: PASS. Real split cpp/header in the pthread
branch, 1.2 M methods, wrap, copied parameters/offsets, owner, sync after reset,
DMA accuracy changes, exception, restart and shutdown. Mocked placement test: PASS.
Native PS5 compilation succeeded. These host tests do not yet validate PS5 rendering.

Details and harness: artifacts/profile-051/CHANGE.md and host-harness.
Console .051: loading stuck at 91%, game not started. Cache of 358 pipelines loaded
(504 ms), then only backend creation reported. No explicit error in retrieved logs.
Backend liveness/execution not established; scheduling starvation is possible but
not confirmed by a stack. Existing debugger unavailable (TCP 744 refused), no attach.
.052 replaces native active/atomic.wait waits with blocking CVs and adds a ready
handshake and startup milestones. No .051 gain claimed and no 30 FPS established.

---

# 00.050.000 — reuse CPU preparation of SSBO views

Incremental build on build-server and PS5 installation succeeded; rollback .049
retained. No commit/push/Cubic. Read-only views in the same group can reuse its
buffer already prepared within the draw, when CPU sources are clean and
key/size/offset/alignment guards pass. Source writes and frees invalidate the
shortcut. The first pass retains synchronization and usage over the full range.
Writes, dirty CPU, missing/invalid group: full path. Batch reset for each draw.
NX2_PREPARED_STORAGE exposes requests/hits for clean candidates.

Focused build-server ASan/UBSan test of real frontend/runtime methods with mocked
queue/allocations: PASS (aliases, invalidations, dirty CPU, writes, shapes/offsets/
alignment and draw reset). Details: artifacts/profile-050/CHANGE.md.
User result .050: 21 FPS, correct image. Over 20.099 s: 760925 reuse requests, zero
hits. host_storage 1.675 s, close to .049's 1.625 s; no gain. This shortcut is unused
in the scene; removal planned for the next functional build. Earlier sampler and
gathered-buffer gains remain useful.
Read-only PokeDinner fork audit: artifacts/pokedinner-source-audit.json.
No external patch or new version installed during that audit.

---

# 00.049.000 — remove the zero-hit cache and detail bindings

Incremental build on build-server and PS5 installation succeeded; rollback .048
retained. No commit/push/Cubic. Handle-word memo removed (zero hits); direct u32
reader restored. Sampler memo and disabled-diagnostic guard retained.

Three subcounters in the existing CPU window: host_uniform, host_storage,
host_texel. Included in host_stage_bind, without waits or operation reordering.
Native compilation succeeded; no extra suite for this removal and these counters.
Details: artifacts/profile-049/CHANGE.md.

User result .049: 21 FPS, correct image. Twenty-second detailed CPU window:
host_storage 1.625 s, host_uniform 0.666 s, host_texel 0.038 s (included in
host_stage_bind 2.505 s with measurement overhead). Stage_resources 1.346 s,
fill_views 1.119 s, push_images 1.038 s. No visible FPS gain over .048; removing
the handle cache barely changes the phases. SSBO preparation becomes the .050 target.

---

# 00.048.000 — repeated resource reads within a draw

Incremental build on build-server and PS5 installation succeeded; rollback .047
retained. No commit/push/Cubic. Bounded 64-entry tables with complete keys for u32
handles and sampler IDs, recreated at every ConfigureImpl. Original typed reader
on a miss. CaptureNativeSampler avoids TLS state when diagnostics are disabled.
NX2_DRAW_MEMO counters: separate requests/hits for handles and samplers.

Focused test of the real header on build-server under ASan/UBSan: PASS, 200000 reads,
collisions, zero, exceptions, new instance on the next draw and sampler IDs.
Details: artifacts/profile-048/CHANGE.md. User result: 21 FPS, correct image.
Over 25.114 s: samplers 68622825 requests / 67886784 hits (98.93%); handles
68622825 requests / zero hits. Detailed twenty-second CPU window: stage_resources
1.466 s (versus 3.855 s in .047, with more draws), fill_views 1.086 s,
host_stage_bind 2.243 s, push_images 1.039 s. The sampler cache is useful; the
handle cache has no reuse and is removed in .049. The sampler memo and diagnostic
guard gains are combined in this result, not isolated.

---

# 00.047.000 — focused CPU subcounters

Incremental build on build-server and PS5 installation succeeded; rollback .046
retained. No commit/push/Cubic. Counters only, no optimization claimed.
Seven components within the existing rearmable twenty-second CPU window: pointer
synchronization, stage resources, SSBO bindings, image views, stage buffer bindings,
image descriptors and descriptor-queue acquisition. SSBO bindings are included in
stage resources: nested durations, not exclusive costs to sum.
Details: artifacts/profile-047/PROFILE.md.

Incremental native compilation succeeded; no extra suite for these counters.
Console capture retrieved: stage_resources 3.855 s (including SSBO bindings 0.271 s),
fill_views 0.993 s, pointer synchronization 0.169 s; host_stage_bind 1.961 s,
push_images 0.914 s, descriptor acquisition 0.023 s. Detailed twenty-second window,
25.173 s between reports. First CPU candidate: shader-resource resolution outside
SSBO bindings. User did not specify .047 FPS.

---

# 00.046.000 — CPU preparation of texture arrays

Incremental build on build-server and PS5 installation succeeded; rollback .045
retained. No commit/push/Cubic. Preserves .044/.045 fixes that yielded 18 FPS in user testing.

Root/size/mapping validated once per descriptor per draw; exclusions use the same
local root. Content and root reread on the next draw. thread_local CPU scratch
cleared every ConfigureImpl; capacity of all three vectors reused.

Focused test of the real buffer_source reader on build-server under ASan/UBSan:
PASS. 1024 elements, new root on the next draw, rejection checks preserved.
Details: artifacts/profile-046/CHANGE.md. User result: still 18 FPS.
Measurement confirms unchanged phases: configuration 9.878 s / detailed twenty-second
window, resource reads 5.112 s, descriptors 2.907 s. Gather 21.28 GB/s, scatter
11.02 GB/s, reuse avoids 270.71 GB/s of payload copying. No .046 gain observed.
This optimization does not affect the observed expensive path; .047 separates CPU
components before the next fix. Visual state not specified.

---

# 00.045.000 — correct gathered-SSBO invalidation polarity

Incremental build on build-server and PS5 installation succeeded; rollback .044
retained. No commit/push/Cubic. SynchronizeBuffer returns true without an upload
and false after an upload: BindMultiRangeStorage now invalidates in the latter
case. Exact write invalidations and .044 owner tracking preserved. No change to
gather/scatter for writable groups.

Focused test of the real function on build-server under ASan/UBSan: PASS. Clean
sources, upload, then 10000 unchanged bindings; actual integration-point polarity
verified. See artifacts/profile-045/CHANGE.md. User console result: 18 FPS (up from 8).
Over 25.154 s: 65194 gathers and 836726 reuses (~92.77%), gather 21.35 GB/s,
scatter 11.05 GB/s and ~271.42 GB/s of payload copying avoided at this rate.
GPU timestamps cover 6.530 s over 25.154 s (intervals include internal waits).
Detailed twenty-second CPU window: configuration 9.863 s, including resource reads
5.062 s and descriptors 2.959 s. CPU cost stands out after redundant copies are
removed. Visual state of .045 not specified.

---

# 00.044.000 — reuse fragmented read-only SSBOs

Incremental build on build-server and PS5 installation succeeded; rollback .043
retained. No commit/push/Cubic. Focused build-server ASan/UBSan test: PASS,
200000 cases and correct removal of a gathered owner.
Details: artifacts/profile-044/CHANGE.md.

Reuses gathered copies of read-only groups until an overlapping source write.
Invalidation on shaders, uploads/copies, fills and queries, with gathered-owner
tracking. Conservative writable groups unchanged. Gather/scatter/reuse volume
counters and GPU copy samples added to verify the mechanism and the cost missing
from .043 measurements.

Console result: 8 FPS, correct image. Over 25.327 s: 3.555 TB gathered,
134.215 GB scattered, zero reuse. About 140.36 GB/s of gather payload (excluding
double read/write traffic). Invalidation condition is inverted:
SynchronizeBuffer=true means no upload was required. This old condition prevents
all reuse; fixed in .045. No .044 gain observed.

---

# 00.043.000 — CPU profiling and targeted GPU operations

Incremental build on build-server and PS5 installation succeeded; rollback .042
retained. No commit/push/Cubic. Changes .040–.042 remain integrated.

The existing marker enables twenty seconds of CPU phases and GPU sampling
(draws 1/64, compute 1/8), with shaders and actual pass dimensions. Query reads
without WAIT, no added submission, bounded ring without reusing an in-flight pair.
Focused ASan/UBSan test of the real implementation on build-server: PASS (ticket
across a submission, NOT_READY, saturation, disabling). GPU intervals may include
earlier work: they are not exclusive durations to sum.

Console capture retrieved while controlling the character. Over twenty seconds of
detailed phases: configuration 5.238 s, including resource reads 2.596 s and
descriptors 1.685 s. Sampled GPU draws are short; work outside draws is not yet
attributed. No gain claimed. See artifacts/profile-043/PROFILE.md and the focused
test retained with the package.

---

# 00.042.000 — retain shadow copies across passes

Incremental build on build-server and PS5 installation succeeded after confirmed
closure. 70 files verified in staging; rollback .041 retained. No commit/push/Cubic.

Removes early snapshot emission at every pass end. A pass end or change does not
modify arguments; requests remain cancellable and batchable until a submission,
conflicting source write, CPU read, free or capacity limit. Other guards and .040
improvements preserved. No CPU wait added.

Focused build-server ASan/UBSan test: PASS. Real scheduler methods and upload guard,
previous 262144 mixed events plus two explicit cases: 100 pass changes followed by
cancellation produce zero copies; 100 requests surviving across passes produce
one multi-region command at submission. No general suite.

User feedback: unchanged FPS. PS5 window of 5.107 s: 47520 requests, 42458
cancellations (89.35%), 5062 regions in 132 commands / 118 batches, 40 write
conflicts, no special shadow submission or shadow CPU readback. Batching works but
provides no observable smoothness gain. GPU command time: 4.506 s;
WaitSemaphores API: 2.348 s (40 calls), QueueSubmit: 0.585 s (307 calls).
These durations overlap and must not be added. Long retirement waits originate in
FenceManager::WaitFence, symbolized with the exact .042 ELF and load offset.
GPU time also includes internal waits; it does not demonstrate compute-unit saturation.

---

# 00.041.000 — deferred, cancellable, batched shadow copies

The other agent finished; .040 staging, service and heap improvements preserved.
Incremental build on build-server and PS5 installation succeeded after confirmed
closure. 70 files verified in staging; rollback .040 retained. No commit/push/Cubic.

Removes whole-buffer generation tracking and special snapshot submissions.
Deferred requests, bounded at 4096, cancelled if the shadow is fully rewritten
before emission. Surviving copies are grouped by source/destination pair, with
multiple regions and one barrier pair per batch. Emitted in the main buffer at a
natural boundary, before an overlapping source write, before freeing, on CPU
observation or at capacity. Writes outside the arguments do not trigger a batch.
CPU uploads overlapping a pending read stay after it in the main buffer. No CPU
wait added for conflicts; staging reserved and source retained until completion.
Previous geometry, ABI and shadow protections remain.

Focused build-server ASan/UBSan test: PASS. Real Scheduler methods and upload guard
extracted from production sources, ordered GPU model: cancellation, exact ranges,
write/copy/reuse, boundaries, freeing, batching, destination overlaps, capacity and
262144 mixed events. No general suite; geometry and shadow ledger unchanged,
previous tests not rerun.

Trial .041: unchanged smoothness. Capture: no special shadow submission or shadow
CPU read, but 34107 batches for 47472 requests in ~5.057 s, without write conflicts.
Emission at every pass end remains too frequent.

---

# 00.040.000 — Vulkan transfers, auto-stub logging and fragmented heap

Source: heydemoura/EglantinePS5, `a2c5a9084c5d4c1d2a79db6d87480b0fe44b8f2b`.
Three selected adaptations; no BCn mip reduction imported.

Focused tests on build-server, ASan/UBSan with leak detection: PASS.

- Staging: 16 MiB threshold, 341 → 352 MiB instead of 512 MiB, actual capacity,
  deferred/in-use entries retained, cursor reset.
- Heap: contiguous virtual range with bounded physical blocks, mapping failure
  at every block, exhausted memory, full scratch, alignment and address overflow;
  full release of partial acquisitions. Production helper exercised with a mocked
  backend; PS5 kernel calls are not executed on the host.
- Services: first report per service/command, silent repeats, disabled policy
  preserved, eight concurrent threads.

The native path explicitly reads `use_auto_stub.GetValue()`; the implicit conversion
rejected by the first build was fixed. Native build, integrated checks and package
(version, imports, alignment and PPSA99862 isolation): PASS.
PS5 installation succeeded after confirmed closure: 70 files verified in staging,
full activation, rollback .039 retained at
`/data/ps5-diag/nx2-rollback-039-20261031-f330a829`. Application not relaunched.
No FPS/memory gain measured.
Archive: `artifacts/00.040.000/Eden-NX2-PS5-prototype-00.040.000.tar.gz`.
Build/test logs and package retained in that directory.

---

# 00.039.000 — batch shadow copies outside render passes

Incremental build on build-server and PS5 installation succeeded after confirmed
closure. 70 files verified in staging; rollback .038 retained. No Cubic, commit or push.

Shadow copies recorded in the transfer buffer executed before the main buffer,
without interrupting the render pass for every copy. If main-buffer source writes
are declared, they are submitted first without a CPU wait. Tracks shader writes,
copies/fills and query writes; distinguishes uploads already ordered in the
transfer buffer. Write generations do not depend on a declaration tick, since
preparation may submit a context before recording the draw. Transfer barriers and
shadow CPU-read rules preserved. disable_buffer_reorder retains the earlier main path.

Focused build-server ASan/UBSan test: PASS. Asynchronous queue model (upload before
main), GPU/CPU rewrites, read-only repeats, submission during preparation and
524288 ordered events compared with expected logical values. Previous geometry
and shadow-tracking tests cover unchanged code and were not rerun. A missing
counter header was fixed during the native build; incremental resumption succeeded.
No general suite.

Actual batching, FPS and PS5 .039 rendering results pending. No gain claimed.

---

# 00.038.000 — native indirect drawing and deferred shadow tracking

Incremental build on build-server and PS5 installation succeeded after confirmed
closure. 70 files verified in staging; rollback .037 retained. No Cubic, commit or push.

.037 never used HLE: shadow=1 (TrackWithFilter) triggered every fallback. .038 keeps
code/SDK, topology, address, CB0 and alias guards, but allows Track and
TrackWithFilter with deferred tracking of firstIndex, indexCount, drawBegin and
drawEnd registers and their shadow copies.

Immutable 20-byte GPU copies before argument reuse; staging reserved per engine
(1024 slots, at most 64 owners). History bounded at 8192 events. Zero counts
correctly preserve previous values. An actual read/Replay reread or capacity limit
materializes state; full CPU rewrites cancel pending work. Writes equal to an old
CPU cache value are still accounted for. Transfer/CPU barriers and wait before
read; staging reserved until destruction after GPU completion. Replay itself
retains the old macro path.

Focused build-server ASan/UBSan tests: PASS. Real trace and 4096 geometry/base
comparisons; deferred tracking over 524288 mixed events, zero counts, partial
rewrites, observation, full cancellation, immutable copies and capacity limit.
No general suite. Native compilation and packaging succeeded.

User trial .038: 8 FPS, no new visible defect compared with .037. Capture: 148068
accepted HLE calls, no fallback, 148068 shadow copies, zero shadow CPU rereads and
1504 rewrite cancellations. GPU path active, but small FPS gain. Per-draw copies
still interrupt render passes in this version.

---

# 00.037.000 — first native macro replaced by a GPU indirect draw

Incremental build on build-server and PS5 installation succeeded after confirmed
closure. 70 files verified in staging; rollback .036 retained. No Cubic, commit or push.

Macro 0x1e7: topology + five arguments already in Vulkan indexed-indirect format.
For the recognized SDK and accepted forms, the draw directly consumes GPU arguments
without CPU RefreshParameters. Guards before any write: exact code/SDK, dirty
parameters, CPU-current triangle topology, mapped contiguous addresses, shadow
passthrough, compatible CB0 binding and no physical overlap with its constants.
Other cases retain the existing path. No replay after drawing. Shader bases use
existing HLE substitutions; their constants and non-temporary registers end at
zero. Recognized SDK ABI for temporary draw registers. Native indirect admission
limited to Vulkan HLE mode. Generic .036 trace removed from the execution path.

Focused build-server ASan/UBSan test: PASS. Real MME trace, 4096 randomized geometry
and base-reset comparisons; zero counts, instance loops, signed bases, code and
address rejection. No general suite. A type-name error in the adapter was fixed
during native compilation; the incremental build then succeeded. Test semantics unchanged.

User trial: 7 FPS with drops to 3. Capture: accepted=0, state_fallback=232762,
code_fallback=source_fallback=0; shadow=1 (TrackWithFilter) blocks all calls.
The new GPU path was therefore not exercised. The black counter remains unresolved;
no gain or 30 FPS target validated at this stage. Can be disabled with
`/data/eden-nx2/native-draw-hle-off.txt`, followed by a full prototype restart.
No game save/settings changes.

---

# 00.036.000 — identify native draw macros

Incremental build on build-server and PS5 installation succeeded after confirmed
closure. 70 files verified in staging; rollback .035 retained. No extra test,
Cubic, commit or push. No GPU replacement or FPS gain claimed yet.

The native Turing path calls RefreshParameters before JIT/interpreter execution
and bypasses legacy Maxwell HLEs. Per-method counters: calls, dirty calls, reread
time and parameter count. After rearming during actual control, bounded capture
of a few expensive methods: code, parameters, source addresses, registers, RAM
before/after and write/read events. Limits: 16 samples per run, 4096 events per sample.
PS5 capture retrieved: macro 0x1e7 dominates; code/state/trace saved.
The .037 focused test reuses this capture.

---

# 00.035.000 — targeted parameter-cache capacity

Incremental build on build-server and PS5 installation succeeded after confirmed
closure. 70 files verified in staging; rollback .034 retained. No extra tests,
Cubic, commit or push.

Cache: 64 windows of 64 KiB instead of 4, at most 4 MiB retained. Motivation:
.034 measurement during actual control showed 93.6% of fills replacing a valid
entry. Invalidations on every GPU write and copies of only requested/modified
bytes unchanged. User trial: 7 FPS during actual control; no established FPS gain.
Last ~5.113 s window: 11,707 hits, 1,185 fills, zero capacity evictions,
1,194 GPU invalidations and zero clears. Vulkan semaphore waits ~2.595 s in that
window; CPU/GPU durations may overlap.

The user sees black areas attached to the same environment surfaces. No shader
rejection captured; visual cause not established, no visual fix claimed for this
capacity change.

---

# 00.034.000 — rearmable measurements during character control

Incremental native build on build-server and PS5 installation succeeded after
confirmed closure. 70 files verified in staging; rollback .033 retained.
No extra tests, Cubic, commit or push.

Marker `/data/eden-nx2/profile-refresh.request`: a distinct nonce restarts bounded
GPU/API counter and wait-site windows. Per-thread states reset outside active
scopes. Lightweight parameter-cache counters: hits, misses, fills, bytes, evictions,
invalidations and clears. Aggregates remain cumulative and durations may overlap.
No rendering/cache policy change. User trial: character control reached, black
areas in the environment. Rearming epoch=2 confirmed. Over 5.039 s: 12,339 hits,
4,503 misses/fills, 4,215 capacity evictions, 288 GPU invalidations, no clear;
295,108,608 bytes filled. This motivates higher capacity; it does not establish
the cause of visual defects. No shader rejection in this capture's logs.

---

# 00.033.000 — CPU deferral with the integrated .032 engine

Incremental native build on build-server, packaging and installation succeeded.
70 files verified before activation; user confirmed closure, rollback .032 retained.
No new test, Cubic, commit or push.

Only behavioral change: cpu_write_defer=true at session startup. Prepared engine
matches the .032 patch before compilation; shader-pool and AMD undefined-value
fixes preserved, alongside direct DMA and targeted parameter cache. .032 shader
regressions cover unchanged code and were not rerun. User trial: correct image,
10–12 FPS on an initial screen, 4 FPS in a later sequence, then about 9 FPS during
actual character control. No engine stop in logs captured through ~221 s;
bounded counters expire before the control phase.

---

# 00.032.000 — shader-pool leak and AMD undefined values

PS5 compilation on `build-server` and integrated build checks: PASS.
Packaging and PPSA99862 isolation check: PASS. Archive retrieved locally.
PS5 installation subsequently performed at the user's request: 70 files verified
in staging before activation, full closure confirmed.
Rollback .031: `/data/ps5-diag/nx2-rollback-031-20261031-44b2fb0e`.
Journal: `/data/ps5-diag/nx2-install-032-20261031-44b2fb0e/install-journal.json`.
No application or game launched by the installer. Later user trial: game launched,
playable screen at 8 FPS; .032 boot confirmed in logs.

- Eglantine `59047f0`: destroy T objects constructed in pool chunks, freeing in
  particular allocations owned by Phi instructions.
- Eglantine `bb35360`: undefined SPIR-V U1/U32 replaced by false/zero by default.
  Disable with `EDEN_NX2_UNDEF_ZERO=0` or marker `/data/eden-nx2/undef-zero-off.txt`,
  read at session startup; full application restart required. Choice logged and
  available in release builds.
- Vulkan cache versions: 38 enabled, 39 disabled (previously 37), evaluated after
  startup settings. Switching modes rejects the old cache. Native translator
  salt: `0x4f554e4345a00006`.
- Focused regression against prepared production headers, built on build-server
  under ASan/UBSan/LSan: PASS. Empty pool, chunk moves, consolidation, reuse,
  repeated release and final destruction; 19 objects each owning an allocation,
  all destroyed. Three processes test the default, explicit disabling/enabling,
  mode/cache consistency and persistence after an in-process environment change.
- General engine suite not rerun. Focused tests do not simulate AMD rendering:
  no memory/FPS gain or visual PS5 effect measured.

Archive: `Eden-NX2-PS5-prototype-00.032.000.tar.gz` (43782142 bytes).
SHA256: `1c4352ae977acbfa99a0dbe89c3854e6cd780ebf087e176a27841d51953c442f`.
Local logs: `artifacts/00.032.000/{build,package,shader-regression-032}.log`.
No commit or push.

User capture .032: over ~5.08 s, 3377 Vulkan semaphore waits / ~2.70 s and ~2.27 s
of cumulative CPU-write callbacks. Durations overlap. This does not measure the
isolated effect of the .031 cache or either .032 fix.

---

# 00.031.000 — targeted parameter-readback cache

Incremental native build on build-server, packaging and installation succeeded.
70 files verified before activation; user closed the prototype, rollback .030
retained. No general suite, Cubic, commit or push.

Up to four logical 64 KiB GPU windows can be reused only within exact/contiguous
RefreshParametersImpl ranges. Only requested GPU-modified bytes are copied to the
game. Every recorded GPU write invalidates overlapping windows, even if the range
was already dirty; buffer deletion/reset clears them. Readers outside parameter
refresh and large/window-crossing reads retain the existing path. This scope
excludes GPU-write preparation before the write is recorded.

Production method + real cache/RangeSet, mocked tracker/runtime on build-server,
ASan/UBSan: PASS. Reuse without waits, exact copies, new GPU write to an already
dirty range, CPU ownership, reset, full fallback, bounded LRU, and no reuse outside
the parameter range, particularly between write declaration and execution.
This does not qualify the actual driver.

PS5 .031 FPS/image/stability result pending.

---

# 00.030.000 — direct DMA block reads

Incremental native build on build-server, packaging and installation succeeded.
70 files verified before activation; user confirmed closure, rollback .029 retained.
No extra test, Cubic, commit or push.

The prototype selects existing DmaAccuracy::Unsafe for DMA blocks, the dominant
reader confirmed in .029. GPU accuracy remains High, modified indirect/macro
parameters retain explicit readback, and owned command storage and guards remain
active. No false fence signal.

This compares DMA accuracy settings; it does not generally validate GPU-produced
commands. Trial .030: playable screen/correct image according to the user, initially
8 FPS then 3 FPS further on. Logs active through ~56.4 s without a captured error
in that window. Wait volume falls, but remaining small macro-parameter rereads
still dominate. The initial gain does not resolve heavier-scene frame rates.

---

# 00.029.000 — readback origins and volume

Incremental native build on build-server, packaging and installation succeeded.
70 files verified before activation; user confirmed closure, rollback .028 retained.
No extra test, Cubic, commit or push.

Same bounded histogram as .028, extended at MemoryManager::ReadBlock and
RasterizerVulkan::FlushRegion calls with requested volumes. Intended to distinguish
readers causing waits without changing synchronization. Exact .029 ELF/map retained
on build-server. PS5 measurement: playable screen reached. Runtime anchor 0x27e9d40
minus ELF anchor 0x23e9d40 confirms relocation 0x400000. Raw ReadBlock caller
0x29c6b46, ELF 0x25c6b46: DmaPusher::DispatchCalls, inlined Step. Last
5.000009517 s interval: 218,743 reads, 31,830,468 bytes, 3.340 s cumulative.
Other measured readers are secondary. No FPS gain claimed for this measurement.

---

# 00.028.000 — bounded GPU-wait attribution

Incremental native build on build-server, packaging and installation succeeded.
70 files verified before activation; user closed the prototype, rollback .027
retained. No extra test, Cubic, commit or push.

Thread-local histograms at BufferCacheRuntime::Finish, Scheduler::Finish and
MasterSemaphore::Wait entry: count/duration per caller, 24 sites plus overflow,
reports every five seconds, at most three minutes per thread. Runtime anchor for
exact symbolization; .028 ELF/map retained on build-server. Nested durations cannot
be added. No wait added/removed or cache change.

Measurement build, no FPS gain claimed.

Measurement .028: playable screen reached. Runtime anchor 0x27e9d50 and ELF anchor
0x23e9d50 establish relocation 0x400000. Raw caller 0x282815b maps to ELF
0x242815b, BufferCache<Vulkan>::DownloadBufferMemory: 29,397 calls / ~3.262 s
during the active five-second window, close to the draw count. Other recorded
waits remain secondary in that window. Reader origin still needs distinguishing;
.029 extends the measurement.

---

# 00.027.000 — batched exact SSBO-pointer reads

Incremental native build on build-server, packaging and installation succeeded.
70 files verified before activation; user closed the prototype, rollback .026
retained. No general suite, Cubic, commit or push.

Active SSBO pointers batched before native graphics/compute binding. Their
GPU-modified intersections use one staging allocation and wait per batch.
Only requested bytes are written back; neighbors remain dirty. Existing individual
path serves as fallback, especially for holes and page crossings.

Production method, real RangeSet, mocked tracker/runtime, build-server ASan/UBSan:
PASS. One wait, exact bytes, duplicates, two buffers, partially modified values,
remaining state, CPU-owned exclusion, holes/page crossings, empty/clean batch.
This does not validate the actual driver.

Trial .027: playable screen according to the user, still 6 FPS. Logs active through
~68.3 s, without DMA capture, out-of-range compute or worker exception in that
window. Waits remain ~29,104 calls / ~3.20 s over the last ~5.06 s interval,
comparable to .026. No FPS gain observed; dominant origin remains to be measured.

---

# 00.026.000 — explicit compute stop and modified-block observations

Incremental native build on build-server, packaging and installation succeeded.
70 files verified before activation; user closed the prototype, rollback .025
retained. No new test, Cubic, commit or push.

Immediate CPU notifications restored, drains added to FlushRegion in .025 removed,
precise .023 readback preserved. Out-of-bank compute methods fail explicitly in
the prototype; DMA captures the block instead of letting the engine accept those
methods and repeat errors.

At most four observations compare complete short entries (<=64 words) with their
submitted state before execution. A difference alone neither modifies nor stops
the stream: GPU-produced data may legitimately change. Capture reason distinguishes
observation from engine exception. PS5 result pending; no general corruption fix
or frame-rate improvement claimed.

Actual .026 trial: playable screen reached according to the user, 6 FPS. Logs
active through ~64.9 s without DMA capture, out-of-bank compute, unbound engine or
worker exception in that window. Limited observation, not exhaustive validation.

---

# 00.025.000 — CPU notifications before GPU readback

Incremental native build on build-server, packaging and installation succeeded.
70 files verified before activation; user closed the prototype, rollback .024
retained. No general test, Cubic, commit or push.

Before FlushRegion locks, FlushCaching applies CPU notifications, then
InvalidateGPUCache applies collected invalidation ranges. A thread-local scope
forces the GPU path to acquire locks without requeuing writes; deferral remains
active on guest threads. Precise .023 readback preserved. Captures expanded to
64 words to cover complete small blocks.

Only focused build-server ASan/UBSan check: extracted real scope and locking
function; normal deferral, forced locking, nested scopes and another thread's
independence: PASS. This does not qualify the actual driver.
Trial .025: user reported a frozen black screen. Logs reach ~38.9 s and repeat
out-of-bank compute methods 0x1f36/0x1f37; no explicit GPU-worker stop captured in
stderr. The ordering fix did not prevent these invalid commands. No stability or
frame-rate success claimed.

---

# 00.024.000 — CPU deferral restored, precise readback preserved

Incremental native build on build-server and installation succeeded, 70 files
verified before activation. User confirmed closure, rollback .023 retained.
No new test, Cubic, commit or push.

Session startup re-enables cpu_write_defer, disabled for comparison .021.
Precise .023 GPU readback and disabled heavy tracing remain unchanged. The five
focused .023 cases cover the same readback code and were not rerun.

Trial .024: DMA stop at 36.28 s, channel 1 / subchannel 6 / method 0x252,
58-word block, error at +0x8c. First 64 bytes identical at submission, before read
and in the owned copy; later words were not captured at submission. No conclusion
on their mutation timing. .025 captures up to 64 words and applies CPU
notifications/invalidation before GPU readback, with synchronous handling only
on the GPU thread.

---

# 00.023.000 — GPU readback limited to the requested range

Incremental native build on build-server, packaging and installation succeeded.
70 files verified before activation; user closed the prototype, rollback .022
retained; .014 remains the visually tested fallback. No general suite, Cubic,
commit or push.

DownloadBufferMemory now bounds prototype readbacks to the request and buffer
limits. Only actually copied intervals are cleared; page flags restored for
neighboring GPU data still dirty. Heavy .022 provenance ledger disabled by default.
Prefix captures and explicit stop on missing engine preserved.

Only focused check: extracted production method, real Common::RangeSet, mocked GPU
runtime and page flags on build-server, ASan/UBSan: 5 cases PASS. 4-byte read,
unaligned 1-byte read, page crossing, full buffer and multi-buffer request.
Neighboring bytes, subsequent reads, asynchronous intervals and GPU flags verified.
This does not validate the actual Vulkan driver or console.

Trial .023: user confirms the playable screen remains open, 6 FPS and slight
physical buzzing. Logs active through about 65 s without a new DMA stop, beyond
earlier failures. Observation limited to this trial, not general stability
validation. Frame rate insufficient. .024 preserves precise readback and restores
CPU deferral to isolate its impact after comparison .021.

---

# 00.022.000 — provenance of writes into pending commands

Incremental native build exclusively on build-server, packaging and installation
succeeded. 70 files verified before activation; user closed the prototype,
rollback .021 retained. No general test, Cubic, commit or push.

Bounded capture of the last Write/WriteBlock/WriteBlockUnsafe into a pending
command prefix: range, source bytes and raw host caller address. Vulkan CPU
notifications and host pointers at submission/failure also retained. A CPU
notification does not prove the final value of a guest write; absence of an event
does not cover uninstrumented direct writes. Copies never repair or execute commands.
Actual result: playable screen briefly opened, ~7 FPS according to the user, then
return to launcher at 48.51 s. Trace identifies a 4 KiB engine write to device
0x15fc7d000 via DeviceMemory::WriteBlockUnsafe. Source bytes at offset 0x100
exactly match the corrupted command prefix. Host pointer unchanged. Raw caller
0x2827424; after relocation 0x400000, ELF 0x2427424 in
BufferCache<Vulkan>::DownloadBufferMemory. Immediately preceding indirect call
verified in the exact ELF retained on build-server. Readback path confirmed;
circumstances marking the page GPU-modified remain to be determined.
Heavy tracing removed in .023.

---

# 00.021.000 — immediate CPU notifications in the prototype

Incremental build exclusively on `build-server`, packaging and installation
succeeded. 70 files verified before activation; user closed the application,
full rollback .020 retained. No general test, Cubic, commit or push.

Only behavioral change: cpu_write_defer=false by default under EDEN_NX2_PS5_PROTO.
CPU-write notifications immediately acquire cache locks instead of being deferred.
This isolates a write-order hypothesis; .020 proves a block mutation between
submission and read but does not identify its writer. DMA captures and guards preserved.
Actual .021 trial: return to launcher at 37.78 s, entry 3876/5140, channel 1 /
subchannel 5 / method 0x10be. At GPU 0x1f8342da80 and device 0x15d89da80,
the valid submitted prefix is replaced by zeros before normal read. Before-read,
owned and live copies agree. CPU-notification deferral is therefore not required
for the mutation; the writer remains unknown.

---

# 00.020.000 — DMA prefixes attached to batches

Incremental native compilation on `build-server`, packaging and installation
succeeded. 70 files verified before activation, user closed the application,
rollback .019 retained. No general test, Cubic, commit or push.

Submission prefix now travels with its `CommandList` instead of depending on
bounded shared history. On stop, capture also contains the prefix before normal
read, owned block and current memory prefix, with GPU/CPU addresses and initial
parser state. These copies are diagnostic only; commands and synchronization
retain the same path.
Trial .020: return to launcher at 36.41 s. Entry 2261/5140, GPU 0x1ec04c2980,
device address 0x162103980 identical at submission and execution. Submitted
prefix is a valid command sequence; its content changes before normal read.
Before-read / owned / reread-after-failure prefixes identical. The normal reader
therefore does not introduce this observed change. Writer remains unidentified.
No 0x18f call recorded before the stop. .021 disables CPU-notification deferral
as a controlled comparison, without claiming this mechanism is proven responsible.

---

# 00.019.000 — capture the rejected DMA block

Incremental build on build-server and installation succeeded. 70 files verified,
rollback .018 retained. No general test, Cubic, commit or push.

The user corrected the initial response: the game had not been relaunched.
Actual trial reproduces return to launcher after menu confirmation: explicit GPU
stop at 34.52 s on channel 1 / subchannel 6 / method 0xebc. 59-word block,
GPU 0x1f82cdd280; owned words identical to the memory prefix reread after failure.
No 0x18f call recorded. Submission prefix absent from bounded history (sequence 0);
no conclusion on when these data became invalid. .020 replaces that history with
batch-attached prefixes and also captures before the flushing read.

---

# 00.018.000 — isolate MME 0x18f before execution

Incremental build on `build-server`, packaging and PS5 installation succeeded.
User closed the application; 70 files verified before activation. Rollback .017
retained; .014 remains the visually tested fallback. No general suite, Cubic,
commit or push.

Macro 0x18f selects the interpreter before any execution and bypasses the memo
cache. No failed JIT execution is replayed. Other macros retain their path.
At most four captures save initial code, parameters and DRAM; at most 128 emissions
are traced. This is isolation, not a gain or an already validated hardware fix.

Trial .018: return to launcher after explicit GPU exception at 35.52 s,
channel 1 / subchannel 7 / method 0x70 / remaining count 8186, GPU block
0x1f82d47780 + 8. No macro 0x18f call recorded before the stop; this trial
therefore does not resolve the JIT/interpreter comparison.

---

# 00.017.000 — owned copy of native DMA commands

.016 reproduces the same SIGSEGV after 56 seconds in DmaPusher::CallMethod,
null engine and method 0x800. Removing detailed tracking was insufficient: it is
not required for the crash. Exact source of the invalid stream remains unknown.

.017 replaces the direct guest-memory view with channel-owned scratch for native
commands, retained during a suspended acquire. Safe/unsafe reads respect the
existing setting. Already-owned prefetches and non-native channels keep their
path. A command without a bound engine fails with explicit context before
dereferencing, without being ignored or falsely signaling GPU completion.
Stability candidate, not a proven root cause.

Incremental build exclusively on `build-server`, packaging and installation chained
in an attached execution; final result successful, logs retained in files.
No general suite, Cubic, commit or push. User closed the application; staging
verified and activation succeeded. Rollback .016; .014 remains the visually tested
fallback. .017 returns to launcher after explicit GPU exception: unbound DMA engine,
channel 1 / subchannel 6 / method 0xfa7. No new native crash report. An MME 0x18f
FIFO error precedes the stop; its causal role remains to be established.

---

# 00.016.000 — isolate the .015 crash

The user-reported return to launcher corresponds to a .015 crash, not a normal
game exit. Native report: SIGSEGV on the GPU thread after 36 s, read at 0x360 in
DmaPusher::CallMethod from a null engine pointer. An MME "parameter FIFO underflow"
error precedes the crash; its causal role is unproven. Stack addresses marked `?`
do not prove reentrancy.

.016 disables only detailed dev_marks hooks added in .015 for ordinary builds;
the FP16 shader remains identical. A controlled comparison, not a demonstrated
root cause or speculative parser fix. Incremental build on `build-server`:
12 objects, packaging and direct installation. No new host test, Cubic, commit or push.

User closed the app before replacement. Rollback .015 preserved; .014 remains
available as the latest visually tested fallback. Trial .016 pending.

---

# 00.015.000 — FP16 gather and post-menu measurement

Incremental native build on `build-server` (31 objects), packaging and direct
installation. Only host check: the actually rejected gather and four .014 cases
pass production lowering. No general suite, Cubic, commit or push.

FP16 gather: four selected values preserved, then packed in pairs into R2/R3
outputs, without the F32 alignment previously imposed incorrectly. Descriptor
bank/offset and gather component preserved; other modes rejected.

Playable-phase measurement: draw-preparation counters enabled before worker startup;
stop after three minutes of presentation, even with hidden HUD. At most 36
five-second reports. No PC sampling, readback or GPU-wait changes. Nested phase
durations must not be added.

Installation: verified staging then activation, rollback .014 retained. Trial .015
pending. Physical noise reported on .014 disappears when the user closes the app;
hardware cause unidentified, no hardware diagnosis drawn from logs.

---

# 00.014.000 — three remaining texture forms

Incremental PS5 build on `build-server` (29 objects), packaging from the same binary,
immediate installation after confirmed closure. No Cubic, commit or push.
Only host check: four actually captured instruction sequences pass production
lowering. No desktop suite or general test.

Additions: bindless Array2D depth in vector layout; explicit-LOD 2D sample in another
bank; explicit-LOD FP16 2D fetch with packed outputs, odd registers and input/output
aliases. Unsupported masks still rejected, synchronization intact. Translator salt
incremented.

Installed: verified staging then activation, rollback .013 retained at
`/data/ps5-diag/nx2-rollback-013-20261031`. Games and saves preserved.
Instruction acceptance and compilation do not validate rendering: visual PS5 trial pending.

---

# 00.013.000 — fixes following Cubic review

Incremental native compilation on `build-server` (18 objects), packaging and direct
installation after confirmed closure. No new host test or general suite.
Four concrete fixes came from the initial review: nonempty save import after filtering, no upload
redirects, unique memory-cache generation across instances, and preservation of
the color matrix reported by FFmpeg.

70 files verified in staging, activation succeeded. Only one console rollback
retained: .012 at `/data/ps5-diag/nx2-rollback-012-20261031`. Older copies deleted
on request, approximately 862 MiB freed; games and saves preserved.

Video performance and partial rendering improvement measured on .011/.012 below.
No complete .013 graphics validation: three remaining texture forms identified on
.012 still need implementation.

---

# 00.012.000 — menu / next-screen textures

Incremental PS5 compilation on `build-server`, packaging and direct installation.
Two focused tests against production lowering and Maxwell IR: **82 assertions
passed**, existing host libraries reused. No full desktop suite or repeat of
general native checks, per user preference.

Two rejections from .011 logs reproduced before fixing: bindless 2D RGB with
separate outputs, Array2D depth comparison using a second descriptor bank.
Registers, aliases, bank/offset and depth reference preserved; translator salt
incremented for caches. Video gain from .011 retained.

Installed on PS5 after confirmed closure: 70 files verified in staging, activation
by rename with full .011 rollback. Console visual result: partial improvement
according to the user, defects remain. Earlier two rejections absent from .012
capture; new rejections concern bindless Array2D depth, multi-bank explicit LOD
and FP16 fetch. Complete rendering correctness not validated.

---

# 00.011.000 — SSE2 video conversion

PS5 compilation and integrated native checks on `build-server`: PASS. Package:
inventory, imports, alignment, PPSA99862 isolation PASS. Packaged from the already
built binary. Full desktop suite not rebuilt.

Focused Clang 21 -O3 ASan/UBSan test on `build-server`: **33,554,432 pixels exactly
match** scalar calculation, covering all YUV combinations in both ranges.
Widths 0..19, unpadded chroma, odd tails and unaligned output with sentinels: PASS.
Synthetic Linux benchmark: 223.147 ms scalar versus 22.962 ms SSE2 per 4K frame;
this does not measure PS5 performance.

Installed: 70 files verified in raw SELF mode before activation. User confirmed
closure. Rollback .010 retained at `/data/ps5-diag/nx2-rollback-010-20261031`.
Games, saves and settings preserved. PS5 comparison over the same 480 frames
(90..570): conversion **96.176 → 21.148 ms/frame** (×4.55), video output rate
**7.037 → 14.957 frames/s** (×2.13). Presentation during video ~14.2–15.6 FPS,
menu 59.94 FPS. Decoding stable at ~25.6 ms/frame; no resolution or synchronization
change. Video image correct according to the user. Overall graphics qualification
FAILED: black flashes in the menu and major visual defects after confirmation.
Logs capture native shader rejections (multi-bank descriptors, bindless 2D RGB
outputs). Focused fixes in progress; cause of each artifact not established.

User-requested cleanup: staging .006 and rollbacks .006/.007/.008/.009 deleted,
645,741,871 bytes freed. Earlier mentions of these paths below no longer identify
available console rollbacks. .010 remains the only retained console rollback.

---

# 00.010.000 — video / Vulkan measurement

PS5 compilation on `build-server`: PASS. Integrated native checks (JIT, affinities,
GPU synchronization/shutdown, HUD) and package (inventory, imports, alignment,
PPSA99862 isolation): PASS. Full desktop suite not rebuilt. Packaged directly from
the built binary, without a second compilation.

Installation: 70 files verified in raw SELF mode before activation. User closed
the prototype. Full .009 rollback: `/data/ps5-diag/nx2-rollback-009-20261031`.
Games, saves and settings preserved.

Console .010 measurement confirmed by boot trace: 480 4K frames (90..570),
conversion 96.176 ms/frame, decoding 25.724 ms, swizzle 6.772 ms, write 4.271 ms.
Slow windows ~6.8–7.2 FPS. Conversion is the dominant cost. No gain claimed for
this baseline. See `milestones/video-performance/ANALYSIS.md` for protocol and limits.

---

# 00.009.000 — H.264 initialization

PS5 build on build-server and built-in native checks: PASS. Package inventory, alignment,
imports and prototype isolation: PASS. Focused video-init regression against the
prepared production header: 20 assertions PASS under ASan/UBSan. The complete
host engine suite was not rebuilt or rerun, per user request; prior .008 results
below do not constitute a full .009 test run.

Installed on 2026-10-31: 70 files hash-verified in raw SELF mode. Full .008 rollback
retained. Actual installed param.json confirms .009. No post-update game launch.
H.264 format-3 admission is fixed; full playback remains unvalidated.

---

# Eden NX2 00.008.000 — Eglantine and gather

Build and tests exclusively on `build-server`. No commercial game run by this chat.

- PS5 compilation and native checks passed: NSO loading, JIT budgets and aliases,
  six cores, affinities, GPU-thread synchronization and shutdown.
- Focused engine suite: **395 cases / 1,877,310 assertions passed**.
- Gather regression run first: **3 cases / 5541 assertions passed**.
- Memory: real Map/Unmap/WalkBlock methods on test backing, holes and remapping
  inside a contiguous sequence, unaligned copies and untracked mapping: ASan/UBSan PASS.
- ASTC: real layer selection and reads; boundaries, unaligned image, preserved mips,
  out-of-image ranges and full fallback: ASan/UBSan PASS.
- Vulkan cache: portable and generated PS5 writes executed with a fake driver and
  real filesystem; replacement, failure preserving the old file, 12 truncated-header
  sizes and wrong version: ASan/UBSan PASS.
- Metadata: NACP/icons in an update tree and fallback RomFS version tested in the
  engine suite. Fork RET tests adapted to the return link's high word.
- Package: PPSA99862 identity, inventory, imports, alignment and isolation PASS.
- Package tests: six cores, QMD history, graphics/compute MME and PS5 allocator,
  PAuth/RETAB policy, sparse ownership/synchronization and exclusive monitor PASS.

Archive: `Eden-NX2-PS5-prototype-00.008.000.tar.gz` (43757718 bytes).
SHA256: `3367be929eed65092b2b4939d2b553f330da54a90e062365a0e89a4c01ede95b`.
Final source patch: `57866d469302426aa12ed193e12cc1bdd97bf9ae97678cbad74d69ab6d78c9c2`.
PS5 build patch retained in `build-nx2-prototype.diff`:
`e6b581622603a5158d4c49038a1556cc31e2f93a3f83414a5d8f3c6714c48351`.
Only the RET test fixture was adapted after the build; all production sources
are identical. No PS5 rebuild needed for this test correction.

The Linux suite is not hardware qualification. No PS5 memory/FPS gain measured
here. Selective sparse residency remains absent and the sparse backend remains
opt-in. FSR3 frame generation and the view-dimension bypass are not imported.
VP8 decoding rejection remains; the gather fix therefore does not guarantee that
the Welcome Tour PANIC disappears. Any installation is tracked by the other chat.
