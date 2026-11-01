# Native draw macro investigation

Target: keep GPU-produced draw arguments on the GPU, rather than synchronously
refreshing them into the CPU before every native Turing macro execution.

The native path in `MacroEngine::Execute` precedes the older Maxwell HLE dispatcher.
Do not apply its hashes/semantics to native programs without validation. A replacement
must match code, side effects, data RAM, registers, predicates and supported topology;
unsupported variants fall back **before** any partial execution.

`.036` collects bounded per-method refresh totals and, after a profiling rearm,
samples the four highest cumulative refresh-cost methods. At most 16 samples per
application run, 4096 events per sample. Event triples `(kind,address,value)` use
0 for engine-register reads, 1 for emitted methods, 2 for DMA-read words. Code RAM,
parameters, guest source addresses, initial registers, before/after data RAM and
completion status accompany each sample. Captures are private artifacts, not source.

`analyze-capture.py DIRECTORY` only parses bytes and displays metadata/instructions;
it does not execute guest programs. Any replay/equivalence harness runs on build-server.
No GPU optimization is claimed until a recognized replacement is implemented and
compared with the captured native semantics.

The first replacement (`.037`) targets the captured entry `0x1e7` only: six
parameters `(topology, indexCount, instanceCount, firstIndex, baseVertex,
baseInstance)`. The last five are already in Vulkan indexed-indirect layout.
It requires triangles, exact 14-instruction identity, the captured whole-SDK
fingerprint, contiguous mapped arguments, a CPU-current topology, shadow
passthrough, no topology override and the shared CB0 binding ABI. Shader constants
at CB0+0x640/+0x644 use the existing HLE BaseVertex/BaseInstance substitutions;
non-scratch bases/constants end at zero. Draw/index scratch registers are clobbered
under this recognized SDK ABI; its register-reading macros do not observe them.
Argument storage must not physically overlap the constants written by cleanup.
Any rejected condition falls back before engine writes; never replay after drawing.

Native indirect submission was previously refused by DrawManager. The new admitted
path requires the HLE engine mode and Vulkan; generic native indirect draws remain
refused. A different fixed-pipeline app_stage keys HLE shader variants separately.
A full app restart with `/data/eden-nx2/native-draw-hle-off.txt` disables the new path.

Targeted build-server ASan/UBSan test: one captured output trace, 4096 randomized
native-program versus indirect-geometry comparisons, zero counts, instance loops,
signed base-vertex bit patterns, base reset and code/address rejection guards.
This establishes macro geometry/cleanup semantics, not Vulkan rendering accuracy.
Console FPS, accepted/fallback counters and visual comparison remain required.

`.037` console capture: all candidates reject at shadow mode 1 (TrackWithFilter),
accepted=0, sampled state_fallback=232762. Thus unchanged 7 FPS (drops to 3) says
nothing about active GPU indirect performance.

`.038` preserves four dynamically written registers (index first/count, draw
begin/end), including their shadow copies. Each admitted GPU-dirty draw snapshots
20 bytes before argument reuse, into per-engine deferred staging (1024 slots,
at most 64 owners). A bounded ordered ledger preserves conditional zero-instance
updates and intervening CPU writes. A true observer or capacity limit waits and
materializes; complete CPU overwrites discard the ledger without waiting. Replay
reads, direct register reads, sunk writes and ordinary indexed draws observe the
ledger. Same-value write skipping must treat unknown registers as changed.

Staging slots are exclusively reserved until rasterizer teardown; reset/reuse is
ordered by transfer barriers, and readback adds a transfer-to-host barrier plus
scheduler wait. No copy reads live guest memory later to reconstruct old values.
Replay mode itself remains on the old execution path. Original code/ABI, mapping,
CB binding, alias and topology guards remain.

`.038` is active on console: captured 148068 accepts, zero fallbacks and zero shadow
CPU reads; user reports 8 FPS and no new visible defect. Every snapshot still uses
an outside-render-pass main transfer. `.039` moves snapshots to upload CBs after
submitting pending main producers without waiting for completion. Buffer write
versions include shader declarations, main copies/fills and query uploads. Do not
use raw write-registration ticks: configuration can submit before the draw records.
The source write generation is marked submitted only to the generation captured
before submission, preserving writes newly declared during that callback. Existing
CPU upload ordering/usage guards remain. Async queue ordering tests pass; GPU
correctness/FPS of this scheduling change still require console observation.

`.041` supersedes whole-buffer snapshot write generations with deferred main-copy
requests. Exact source-range conflicts drain before shader writes, raw copies/fills
and query outputs; overlapping CPU uploads cannot overtake a queued snapshot.
Natural render-pass/submission boundaries drain batches; CPU shadow resets cancel
pending destination requests. Resource deletion drains before backing is moved.
Grouping uses multiple nonoverlapping regions per source/destination command;
partial destination overlaps drain first and exact slot reuse supersedes only
unobserved queued requests. Queue cap is 4096; cap flush records commands without
forcing submission. Real Scheduler methods and upload guards pass the dedicated
ASan/UBSan model test on build-server. .040 features retained, GPU trial pending.

`.041` removed extra submissions but its pass-end hook still emitted nearly
one copy batch per request. `.042` keeps requests pending through ordinary pass
changes, draining only for submission, actual source write overlap, release,
CPU read or capacity. The 100-pass cancellation/grouping tests cover this case.
