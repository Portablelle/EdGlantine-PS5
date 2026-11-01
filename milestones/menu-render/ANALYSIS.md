# Welcome Tour menu / next-screen rendering

.011 video optimization measured on PS5: 7.037 → 14.957 output FPS over matching
frames 90..570, conversion 96.176 → 21.148 ms. Menu reaches 59.94 FPS, but user
reports regular black flashes and severe black regions/misplaced sprites after
confirmation. Overall rendering is not validated by this FPS count.

At 118.297 s, the .011 log starts rejecting native texture shaders:

- `0a0d7b60 b1012400 041e41ff 00114400`: scalar array-2D depth comparison,
  source A R10/R11, source B R0/R1, output R13, descriptor bank 4/offset 0x490.
  A preceding texture instruction uses a different bank. Lowering rejects it
  instead of reading this instruction's descriptor from bank 4.
- `00007361 38000027 041e0726 002f4400`: bindless scalar 2D RGB sample,
  XY R0/R1, handle R39, outputs R0/R1/R38. The lowering only admitted one channel.
  A second observed form has XY R16/R17 and handle R35, outputs R16/R17/R36.

Both errors reproduce with production LowerToMaxwell on build-server before changes.
They prevent whole draws from executing. This establishes missing passes, not
that every reported artifact or earlier menu flash has this cause.

.012 emits an explicit bindless descriptor load for the mixed-bank array depth
sample, retaining layer/XY/depth and predication. Metadata uses scratch R248/R249;
R254 cannot be used for the last metadata operand because the Maxwell visitor's
post-increment would overflow into RZ. Split bindless 2D outputs sample into
scratch before copying selected channels, preserving aliases with coordinates
or the handle. Unknown modes remain rejected. Native translator salt increases
from 0x4f554e4345a00002 to ...00003 so old pipeline entries are not reused.

Host validation: only the two focused semantic tests, 82 assertions PASS, reusing
existing Maxwell compiler libraries on build-server. Both descriptor banks, implicit/
zero LOD, channel masks, source/output aliases and the depth reference are checked.
No full desktop suite and no repeated generic native checks for this iteration,
per user preference. Native incremental build and installation completed. Console .012 follow-up: user reports fewer but persistent defects. The two .011
rejection forms no longer appear in this capture. New errors are bindless array
depth sampling (`0c0d7361 a800001e 041e41ff`), mixed-bank explicit-LOD sampling
(`18187b60 31018820 059e0f20`) and FP16 texel fetch (`04047b66 33c0440e 059e8705`,
`02017b66 33c04401 059e8705`). Overall graphics acceptance remains incomplete.

## .014 — remaining three forms

Adds only the forms observed in the .012 capture:

- Bindless vector Array2D depth sample: layer/XY from A..A+2, depth and handle
  from B/B+1. Scratch metadata stays below R254 to avoid visitor post-increment
  overflow. The depth reference and descriptor remain separate.
- Mixed-bank scalar 2D explicit LOD: XY from A/A+1, LOD from B, descriptor from
  this instruction's constant-buffer bank. Inputs are snapped before aliased
  split outputs are written.
- Scalar 2D explicit-LOD FP16 texel fetch: selected F32 channels are fetched first
  then packed into native half pairs. RGB uses zero in the last high half; odd
  destination register numbers are valid here. Both captured source/output-alias
  variants are handled. Mixed descriptor banks retain their own bank/offset.

Four captured instruction sequences pass LowerToMaxwell on build-server. No host suite,
Cubic, commit or push requested for this iteration. Native build is incremental;
console visual acceptance is distinct from admission and compilation.


### .014 console follow-up and .015

User reports apparently correct visuals, but ~14 FPS both during intro video and
on the playable screen. .014 boot is confirmed. Logs still reject a scalar 2D
FP16 gather: `06027b63 33c04407 041e8f03 000fc200` (bank 15, offset 0x110,
coordinates R6/R7, selected lanes RGBA, half pairs to R2/R3). .015 samples into
scratch and packs two selected half values per output; odd second destination
is valid, unlike the old F32 output alignment check. Descriptor banks and gather
component remain preserved. The exact capture and all four .014 forms pass the
small production-lowering smoke check on build-server; no general test suite.

.015 enables existing draw-phase counters before guest workers start, with a
three-minute presentation-based cutoff independent of HUD visibility. HUD counter
reports extend to 36 five-second samples, showing draw preparation phases; existing
Vulkan API reports identify wait sites. No PC sampling/readback or altered GPU waits.
Compare post-menu counter differences independently from the software video path.
User reports physical case crackling that ceases after closing the prototype;
logs do not identify a hardware component or establish the cause. Keep console
observations short rather than treating the capture window as a stress-test duration.

### .015 crash and .016 isolation

The app's recovery handler reopened the launcher after SIGSEGV on the GPU thread,
36 seconds into .015. Fault `eboot+0x25c3c00` is the execution-mask read in
DmaPusher::CallMethod: engine pointer RBX is null, method R15 is 0x1ac7, read
address 0x360. The preceding log records native MME start 0x18f, one parameter,
FIFO underflow. That ordering alone does not establish the cause of the bad DMA
stream. Stack entries marked `?` are unchecked scanned addresses, not a verified
call chain; in particular they do not prove parser reentrancy through a flush.

.016 isolates the new detailed profiling switch: ordinary builds leave dev_marks
false again, while retaining the FP16 gather fix and aggregate counters. No DMA
method is skipped, no fence completion is fabricated, and no guessed parser
repair is applied. Console A/B remains necessary. Exact .015 ELF/map are retained
in the dedicated host's isolated experiments/crash-015 folder. Active logs after
the automatic restart belong to the launcher; the preceding game logs were
preserved by the crash handler beside its report.


### .016 reproduction and .017 candidate

.016 repeats the same null engine execution-mask read at eboot+0x25c3c00, now
method 0x800 / address 0x108, 56 seconds after startup. No detailed profiling is
required to reproduce. .017 parses native command lists from the existing owned
per-channel scratch, populated once and kept across pending-acquire resumes.
Safe/unsafe read policy and all synchronization remain unchanged. Unbound engines
stop explicitly with channel/subchannel/method/source context instead of a null
dereference. This protects command ownership; the original malformed-stream cause
still requires console evidence. No silent dropped methods or fabricated fences.
Build and installation completed in one attached continuation, logs read only on
failure; no host suite, Cubic or Git publication.
Console .017 returned to launcher after an explicit GPU-worker exception, not a
new native SIGSEGV: channel 1 / subchannel 6 / method 0xfa7, preceded by MME 0x18f
FIFO underflow. Owned command storage did not resolve the invalid stream.


### .018 MME isolation

Select the interpreter for MME 0x18f before execution in prototype builds and bypass
memo replay for that macro. Never replay a failed JIT with possible side effects.
Other macros keep JIT. Capture at most four initial code/parameter/current-engine
DRAM snapshots and trace at most 128 emitted methods. Incremental build-server build and
PS5 installation completed; no general suite, Cubic or Git publication. Console
result pending. Shared decoder semantics remain a hypothesis requiring captured
program evidence, not an established cause.


### .019 actual console trial and .020 diagnostic refinement

The initial positive reply was withdrawn by the user before any data collection:
the app had not been relaunched. Actual .019 trial returns to launcher at 34.52s,
unbound channel 1/subchannel 6/method 0xebc, GPU 0x1f82cdd280, 59 words.
Owned and live prefixes match. No 0x18f invocation precedes failure. Submission
prefix was not found in the 256-entry diagnostic history (sequence zero), so this
capture cannot distinguish already-invalid submission data from later changes.
.020 carries each prefix with its CommandList instead of a global ring. It also
records the unsafe prefix before the normal safe/unsafe command read to separate
later CPU changes from any flush/readback effect. Neither diagnostic prefix is
used to execute, repair, skip or accept commands.

.020 incremental native build, packaging and 70-file verified installation succeeded.
User-confirmed closure; complete .019 rollback retained. Console trial pending.
No general test suite, Cubic, commit or push. Build patch hashes now reflect .020.


### .020 mutation evidence; .021 ordering comparison

Actual .020 returns at 36.41s with an explicit unbound-engine exception. Entry
2261 of 5140, GPU 0x1ec04c2980 / device 0x162103980, contains valid commands at
submission. Before-normal-read, owned and live prefixes are identical to each
other but differ from submission, at the same device address. The normal read
is not the operation introducing this observed difference. The writer and cause
remain unknown; no 0x18f invocation was recorded before the failure.

.021 disables cpu_write_defer only for EDEN_NX2_PS5_PROTO. Guest cache writes
therefore acquire the locks immediately instead of returning while their cache
notifications remain queued. This is a controlled ordering comparison, not proof
that deferred notifications caused the mutation. No command repair, skipped DMA
method or fake completion is added. Incremental build on build-server; console pending.

.021 build/packaging/installation completed on build-server with no general suite or Git
publication. Shared performance-header change rebuilt more translation units than
the prior diagnostics. 70-file staging verified, user closure confirmed, .020
rollback retained. Actual console outcome pending; no performance gain claimed.


### .021 negative comparison; .022 writer capture

.021 with synchronous notifications still mutates a valid prefix before the normal
read: 37.78s, entry 3876/5140, GPU 0x1f8342da80/device 0x15d89da80, now zeros at
the head. Unbound channel 1/subchannel 5/method 0x10be. Deferred cache notification
is not required for reproduction; this does not rule out all cache/readback paths.

.022 records device-memory writes and Vulkan OnCPUWrite notifications overlapping
the first 64 bytes of pending command entries. Register at submission, retire
on entry completion (keep across acquire resumes). Registry bounded to 65,536
active start addresses; retain latest event per category with source overlap
bytes, device range, and raw host caller for device writes. Failure report also
compares submitted/current host pointers. A CPU notification precedes a guest
store; it is not itself proof of its final written value. No repair/execution
from diagnostic copies, no fake completion or ignored DMA commands.

.022 incremental compilation, packaging and 70-file verified installation complete.
User closure confirmed; .021 rollback retained. Native Vulkan generated source
was refreshed from the updated core with prepare-vulkan-port.py before CMake.
Console writer capture pending. No general suite, Cubic, commit or push.


### .022 writer identified; .023 precise readback

User initially reached playable screen, then observed ~7 FPS (previous ~14) and
launcher recovery. At 48.55s the last device write is WriteBlockUnsafe for device
0x15fc7d000/0x1000 bytes, overlapping the command prefix at +0x100. Captured source
bytes exactly match before-read/owned/live corruption. Submit/current host pointer
is identical. No CPU-notification event was recorded; that alone cannot rule out
all guest stores. Raw caller 0x2827424 resolves after 0x400000 relocation to ELF
0x2427424 in BufferCache<Vulkan>::DownloadBufferMemory. Exact .022 disassembly
has an indirect call immediately before this return address. Exact ELF/map and
build patch retained on build-server/local ignored artifacts.

The method enumerates page-granular dirty ranges and writes their full intersections
with GPU-dirty intervals back even when the caller requested fewer bytes. .023
restricts prototype downloads to requested bytes and the actual buffer extent,
clears only those precise dirty/download intervals, and restores page GPU bits
for neighboring dirty intervals. Heavy writer registry/hooks become no-ops unless
explicitly enabled with EDEN_NX2_DMA_WRITER_TRACE. Prefix captures and DMA guard
remain. Targeted production-method harness on build-server validates neighbor bytes,
later reads, page flags and buffer boundaries: five cases PASS under ASan/UBSan. Hardware outcome
still required; no claimed cadence/stability improvement from compilation alone.

.023 incremental native build, packaging and 70-file verified installation succeeded.
User closure confirmed; full .022 rollback preserved. No general suite, Cubic,
commit or push. Heavy writer trace disabled; no real-driver validation in the
focused mock-runtime harness. Console result pending.


### .023 playable observation; .024 notification performance comparison

User confirms playable screen remains open, but reports 6 FPS and slight physical
case crackling. Logs continue to ~65s without unbound-DMA/session failure, past
previous failures. This is a single short observation, not broad compatibility.
Between the final two five-second aggregate samples, guest CPU-write callbacks
accumulate ~1.92s and Vulkan semaphore waits ~3.28s across ~28,959 calls. Cumulative
timers can overlap and do not independently establish a critical-path cause.

.024 re-enables cpu_write_defer at prototype session initialization before guest
workers/settings application. It retains exact-request readback and disabled
heavy writer tracing. This isolates the cost of the .021 notification setting;
no new lowering, synchronization bypass or shader change. Native incremental
build only; .023 focused method tests apply to the unchanged readback code.

.024 incremental build, packaging and 70-file verified installation completed.
User closure confirmed; .023 rollback retained. No new host tests, Cubic, commit
or push. Console FPS/stability comparison pending.


### .024 stop beyond captured prefix; .025 ordering fix

.024 returns at 36.28s, channel 1/subchannel 6/method 0x252, entry 20/5140, 58
words. Submission/before-read/owned/live first 64 bytes match. Failure is at +0x8c,
so the current capture cannot establish mutation timing for the later words.
.025 expands the existing small-prefix arrays to 64 words (whole 58/59-word entries).

Before prototype Vulkan FlushRegion takes cache locks, apply FlushCaching then
GPU::InvalidateGPUCache. Deferred CPU writes that report GPU-modified data are
collected separately; the latter call applies those CPU invalidations before a
GPU download can overwrite guest bytes. GPU replay now uses a thread-local RAII
flag: cache locks are acquired synchronously and ExtendDeferredWrite is bypassed,
so replay cannot merely queue the notification again. Guest threads retain
asynchronous notification behavior. Precise readback retained, heavy writer trace
disabled. Focused production guard/lock helper verifies normal defer, forced GPU
replay, nested scope restoration and another thread retaining defer, ASan/UBSan
on build-server. Native build and console result pending.

.025 incremental native compilation, packaging and 70-file verified installation
completed after confirmed closure; .024 rollback preserved. Focused replay helper
check passed under ASan/UBSan on build-server, exit 0. No general suite or Git publication.
Console FPS/stability pending; no compatibility or performance gain claimed.


### .025 black screen; .026 explicit failure/capture

User reports stuck black screen. Log reaches repeated native compute out-of-bank
methods 0x1f36 then 0x1f37 at ~38.9s, with no explicit GPU-worker exception in the
captured stderr. .025 does not establish a stability or performance improvement.
.026 removes the added FlushRegion drains and restores immediate CPU notifications
as in the limited playable .023 trial; exact-range readback remains. GPU replay's
thread-local guard remains but ordinary guest writes are synchronous.

Out-of-bank native compute now throws an explicit prototype-only runtime error,
which the existing DMA boundary captures instead of silently accepting that method.
At most four changed short (<=64 words), self-contained entry observations are
captured before execution. Observation alone never alters execution: GPU-produced
command data may legitimately differ from submission. Actual engine exceptions
remain distinct via capture_reason. Full short-entry submit/before/owned snapshots
will cover the .024 failure offset beyond the earlier 64-byte prefix. No new host
suite or test reruns; native incremental compilation and packaging only.

.026 incremental native build, packaging and 70-file verified installation complete.
User closure confirmed; .025 rollback preserved. No additional host test, Cubic,
commit or push. Console result pending; no claim that corruption is fixed.


### .026 6-FPS observation; .027 pointer readback batching

User reaches playable screen at 6 FPS. Logs active to ~64.9s without DMA capture,
invalid compute, unbound engine or worker exception in this window. Between final
aggregate samples (~5.09s), Vulkan WaitSemaphores increases by 27,869 calls / ~3.20s;
GPU work ~2.14s and guest CPU-write callbacks ~1.91s. Timers overlap. Native storage
binding currently synchronizes dirty pointer values separately, each invoking a
GPU finish. Attribution to all observed waits is not yet established.

.027 collects enabled native SSBO pointer addresses before graphics/compute
binding, deduplicates/merges exact eight-byte requests, plans dirty intersections
across buffers into one staging allocation, records copies, waits once and writes
back only those exact bytes. Remaining dirty intervals/page flags are retained.
Existing per-binding synchronization remains for skipped/cross-page/unmapped
pointers and as fallback. No broad page download or fake completion.

Focused host harness executes the production batch method with real RangeSet,
mock page tracker/runtime on build-server under ASan/UBSan: PASS. Checks one wait, exact
neighbor bytes, duplicates, two buffers, partial dirty values, remaining dirty
flags, cross-page/unmapped fallback exclusion, CPU-owned pages, empty/clean batch.
Native build and console FPS result pending; no measured gain yet.

.027 native incremental build/packaging and 70-file verified installation complete.
User closure confirmed; full .026 rollback retained. Focused batch method passes
ASan/UBSan on build-server. No general suite, Cubic, commit or push. Console gain pending.


### .027 no observed gain; .028 bounded wait attribution

User reports 6 FPS despite playable screen. Log remains active through ~68.3s
without DMA/invalid-compute/worker failure in that window. Final WaitSemaphores
delta ~29,104 calls/~3.20s per ~5.06s is comparable to .026. Pointer batching has
no observed FPS gain and does not identify the dominant waits.

.028 adds thread-local fixed-size caller histograms to BufferCacheRuntime::Finish,
Scheduler::Finish and MasterSemaphore::Wait. Count and duration, at most 24 explicit
sites plus overflow, logged every five seconds for at most 180 seconds/thread.
No map, per-call logger/lock, PC sampler or added/skipped GPU wait. Runtime anchor
and TLS state identity support exact-ELF symbolization and separate threads.
Nested durations overlap and must not be summed. Native incremental build only;
no new test suite. Actual callsite measurement pending.

.028 incremental native compilation, packaging and 70-file verified installation
complete, user closure confirmed; full .027 rollback retained. Exact .028 ELF/map
saved in dedicated experiments/waits-028. No additional tests, Cubic, commit or
push. Console callsite measurements pending; no performance gain claimed.


### .028 dominant readback confirmed; .029 upstream reader

At active window end ~81.2s, kind=0 DownloadBufferMemory caller has 29,397 calls /
3.262s; kind=1 BufferCacheRuntime::Finish 29,397 / 3.256s; timeline wait 3.154s.
These are nested observations, not additive. Runtime anchor 0x27e9d50 minus exact
ELF anchor 0x23e9d50 gives relocation 0x400000. Raw caller 0x282815b resolves to
ELF 0x242815b DownloadBufferMemory. Site rates closely match draw count. Upstream
reader is not identified by the finish-only caller histogram.

.029 extends the same bounded profiler with kind=3 MemoryManager::ReadBlock and
kind=4 RasterizerVulkan::FlushRegion, plus requested-byte totals. No wait/cache
behavior changes. This distinguishes CPU command reads, macro parameter refresh,
and render-condition reads before choosing a behavioral change. Native build only;
no extra tests. Console attribution pending.

.029 incremental native compilation/packaging and 70-file verified installation
complete after confirmed closure. Full .028 rollback retained. Exact ELF/map saved
under dedicated experiments/reader-029. No extra tests/Cubic/commit/push. Console
upstream-reader attribution pending.


### .029 DMA fetch identified; .030 direct DMA experiment

Exact .029 anchor runtime 0x27e9d40 / ELF 0x23e9d40 confirms +0x400000 relocation.
ReadBlock raw caller 0x29c6b46 / ELF 0x25c6b46 resolves to DmaPusher::DispatchCalls
(inlined Step). Last ~5.000009517s: 218,743 reads, 31,830,468 bytes, 3.340s cumulative.
Compute descriptor/shader-code/other macro readers are secondary in this window.
This identifies command-block fetch as the dominant reader, not SSBO pointer sync.

.030 uses the existing prototype DmaAccuracy::Unsafe setting for direct command
fetch. GPU accuracy stays High, so dirty macro/indirect parameters keep their
explicit high-accuracy refresh/readback paths. Owned command storage, synchronization
and invalid-method guards remain. This is a controlled DMA-accuracy tradeoff;
GPU-authored command headers and real rendering/stability still require console
validation. No new host tests for a one-setting change. Native build pending.

.030 incremental native build, packaging and 70-file verified installation complete
after confirmed closure. Full .029 rollback retained. No additional tests, Cubic,
commit or push. Actual FPS/image/stability comparison pending.


### .030 partial gain; .031 targeted parameter readback windows

User confirms correct image/playable screen, 8 FPS initially and 3 FPS deeper
into scene. Command fetch no longer dominates ReadBlock; macro parameter refresh
(inlined into MacroEngine::Execute) now accounts for most remaining readback time.
run-030-active remains active to ~56.4s without captured engine failure. This is
limited observation, not broad compatibility or stable-scene FPS comparison.

.031 keeps four 64KiB logical GPU snapshot windows. Only exact dirty requested
bytes are copied back to guest memory. Every gpu_modified_ranges.Add invalidates
overlapping windows even if already dirty. Buffer deletion or ledger Clear drops
snapshots. CPU ownership subtraction never reintroduces a readback of clean bytes.

Reuse is restricted to a thread-local exact device range around contiguous
Maxwell3D::RefreshParametersImpl segment reads. Ordinary readers and GPU writer
preparation use the existing path, preventing a snapshot created between write
declaration and actual recording from becoming reusable. Larger/cross-window reads
retain the original transfer path. No indirect parameter refresh or fence skipped.

Production DownloadBufferMemory + actual RangeSet/cache helper, mock tracker/runtime,
ASan/UBSan on build-server: PASS. Tests reuse without wait, exact CPU writes, overlapping
GPU rewrite while already dirty, CPU ownership, deletion/reset-style clearing,
full-read fallback, bounded LRU, and no cache creation/use outside the exact
parameter scope (including declared-but-not-executed GPU write). Real driver and
hardware validation remain pending. No general suite, Cubic, commit or push.

.031 final scoped cache build/packaging and 70-file verified installation complete.
User closure confirmed; full .030 rollback retained. Focused production-method
harness with parameter-boundary regression passes ASan/UBSan on build-server. Initial
unscoped candidate was never installed. No general suite, Cubic, commit or push.
Actual PS5 FPS/image/stability comparison pending.


### Integrated .032 user trial; .033 CPU notification comparison

User launched integrated .032, which also carries shader object-pool destruction
and AMD undefined-value policy improvements. Boot .032 confirmed, playable at 8 FPS.
Do not attribute the outcome solely to .031 readback reuse. Last ~5.076s aggregate
window: semaphore waits 3377/~2.700s, guest CPU-write callbacks ~2.268s, GPU busy
~2.696s; these overlap. No engine failure captured in this window.

User confirms no other chat is modifying sources/builds and authorizes continuing
here. .033 changes only session initialization cpu_write_defer back to true while
keeping .032 core/shader changes, direct DMA, parameter cache and GPU accuracy.
Prepared-core identity must match current .032 patch before incremental build.
No extra host tests for this setting change. Console result pending.

.033 incremental native build, packaging and 70-file verified installation complete
after confirmed closure. Prepared-core identity matched .032 patch; source changes
limited to session setting and package version. Full .032 rollback retained.
No extra tests, Cubic, commit or push. Console result pending.

.033 user observation: image correct, initially 10–12 FPS, 4 FPS in a later
sequence, then ~9 FPS while actually controlling the character. Do not conflate
these scenes. Existing detailed profiles expire at 180s, before the control phase.
.034 adds on-demand bounded profile rearming through a nonce file and relaxed
atomic readback-cache statistics. No renderer/cache policy changes, extra waits
or per-access logging. New epochs reset thread counters only outside active scopes.

.034 incremental build and installation succeeded; 70 staged files verified,
full .033 rollback retained. User launch/profile capture pending. No extra tests
or Git publication.

.034 profile refresh epoch 2 works during actual character control. User reports
black areas in scenery (not whole-screen flashes); no shader refusals captured.
A 5.039s cache delta: 12339 hits, 4503 misses/fills, 4215 capacity evictions,
288 GPU invalidations, zero clears, 295108608 bytes filled. Thus 93.6% of fills
replace a valid snapshot; .035 raises bounded capacity from 4 to 64 windows
(256 KiB to 4 MiB), preserving all exact-copy and GPU-write invalidation rules.
No claim that cache capacity fixes the black scenery.

.035 incremental native build and 70-file staged installation succeeded after
closure. .034 rollback retained. User confirms black scenery stays attached to
the same surfaces when moving; visual cause remains unresolved. FPS/visual trial
pending; no extra tests, Cubic, commit or push.

.035 user trial: 7 FPS in actual control; one counter in the scenery is entirely
black with no visible details. Last 5.113s cache delta: 11707 hits, 1185 fills,
zero capacity evictions, 1194 GPU invalidations, zero clears; 77660160 bytes
filled. Vulkan semaphore wait delta ~2.595s. Capacity bottleneck removed but
no demonstrated FPS improvement. Logs do not identify the black counter's
shader/material; a picture is needed to localize the missing visual pass.

.036 starts the structural native draw-macro investigation. Native Turing execution
refreshes parameters before JIT/memo/interpreter and bypasses old Maxwell HLEs.
A bounded per-method refresh profile plus selected code/state/effect samples is
installed to identify an exact supported GPU-indirect replacement. No replacement
or FPS improvement claimed yet. Native incremental build and 70-file installation
succeeded; .035 preserved. Capture in actual character control pending.

Native macro capture .036 identifies entry 0x1e7 as dominant refresh cost: between
106.646 and 111.646s, 15812 dirty calls and ~1.887s refresh time (initial epoch;
user-triggered epoch also captured code/state/effects). The program consumes six
words and loops indexed draws, restoring base registers/CB0 constants to zero.
Sample has no engine-register reads or data-RAM writes. Its five indirect words
are contiguous, in Vulkan command order. Whole-SDK hash guards the known ABI.

.037 implements the first native indexed-indirect HLE before parameter refresh,
with shape/code/SDK, shadow, topology, mapping, CB0 and physical-alias guards.
Old native indirect rejection is relaxed solely for admitted Vulkan HLE draws.
Generic .036 per-call tracing is removed. Focused ASan/UBSan semantics test on
build-server passes (captured output trace + 4096 randomized cases + rejection guards).
Native incremental compilation/installation in progress; no GPU correctness or
FPS gain claimed before console trial. Existing black counter remains unresolved.

.037 native build and 70-file staged installation completed after closure; .036
rollback retained. Native adapter type-name build error fixed and incremental
compilation resumed successfully; focused semantic test code unchanged. Hardware
trial pending: accepted/fallback counters, same-scene FPS, renderer correctness.
No commit/push/Cubic or general test suite.

.037 user: 7 FPS with drops to 3. Counter capture accepted=0 and 232762 state
fallbacks, no code/source fallback; actual shadow=1 TrackWithFilter. The HLE was
never exercised. .038 admits Track/TrackWithFilter with ordered deferred shadow
bookkeeping, immutable 20-byte GPU snapshots, exact zero-instance preservation
and CPU-overwrite cancellation. Original Replay reads and direct indexed draws
materialize only when needed; same-value CPU writes still kill unknown values.
Focused ASan/UBSan tests pass: .037 geometry tests plus 524288 mixed ledger events,
zero-instance history, partial replay, full overwrite cancellation and capacity.
Native build/installation pending; no FPS claim.

.038 native incremental build and 70-file installation succeeded; .037 retained
after confirmed closure. Targeted tests passed. Hardware trial pending, especially
accepted/copies/reads/discards counters; no FPS or visual-correction claim.

.038 console: 8 FPS, no new visual defects reported. Captured HLE accepts 148068,
all fallback counters zero, shadow_reads=0, shadow_discards=1504. HLE active;
shadow CPU stalls removed. Last ~5.10s: GPU timestamp busy ~4.53s (includes stalls),
semaphore API delta ~2.27s, guest write callbacks ~0.48s. GPU transfer snapshots
interrupt the render pass per call. .039 batches these in upload CBs, submitting
pending main-buffer source writes without a CPU completion wait. Shader write
registration, main transfer destinations and query writes are tracked by write
versions, not registration ticks. Focused asynchronous queue tests pass. Native
incremental build and 70-file installation complete; .038 preserved. Same-scene
FPS/rendering and upload/submission counters pending; no gain claimed.

.040 read-only control capture: native HLE active, user 8 FPS, ~116.6 shadow
submits/s of ~177.1 total QueueSubmit/s, ~4.28ms per API call; no CPU shadow reads.
Whole-buffer write generations lost range precision and did not acknowledge
natural submissions. CPU shadow resets also left recorded copies executing.

.041 replaces this with deferred cancellable main-buffer snapshot batches.
Argument sources are pinned on request; exact overlapping writes and releases
flush old snapshots first, nonoverlapping writes do not. Natural pass/submission
boundaries emit surviving copies in multi-region groups; CPU overwrite resets
cancel pending copies. Overlapping CPU uploads stay in main after old reads.
No special queue submission or registration-tick acknowledgement is needed.
Source/destination slot overlap and capacity are guarded. Real scheduler-method
and upload-guard ASan/UBSan test passes (262144 mixed events). Native incremental
build and 70-file installation complete; .040 retained after confirmed closure.
Other agent finished; all .040 features preserved. Hardware trial pending.

.041 user reports unchanged fluidity. Last ~5.057s: 47472 requests, 5159 cancelled,
42313 regions emitted in 34107 batches; no write conflicts, no shadow CPU reads,
no shadow-specific submissions. EndRenderPass flushing emits too early despite
true dependency checks. .042 removes that hook; ordinary pass changes leave
requests cancellable until submission/write/release/observer/capacity. Tests add
100-pass cancellation and single-command grouping cases to the real-scheduler
ASan/UBSan harness; all pass. Incremental build-server build and 70-file installation
complete after closure, .041 retained. Hardware result pending.
