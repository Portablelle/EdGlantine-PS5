# nxnative / Eden nightly adaptations — 2 November 2026

This batch targets redundant CPU/GPU copies and JIT compilation overhead. It
also backports two contained descriptor/video fixes. No PS5 frame-rate or
rendering improvement is established by host tests or a successful native build.

## Sources and scope

- [nxnative e5620b1a](https://github.com/seedds/nxnative/tree/e5620b1a05a5b7374e0135d6312d3e90994eab81):
  [range-based dependency tracking](https://github.com/seedds/nxnative/blob/e5620b1a05a5b7374e0135d6312d3e90994eab81/docs/reference/rendering.md#cpu-reads-after-a-drain-wait-only-for-later-writes),
  [CPU overhead and staging](https://github.com/seedds/nxnative/blob/e5620b1a05a5b7374e0135d6312d3e90994eab81/docs/reference/frame-rate.md#cpu-cost-and-pacing),
  and [Bananza findings](https://github.com/seedds/nxnative/blob/e5620b1a05a5b7374e0135d6312d3e90994eab81/dm/games/040074A01BF12000/README.md).
- [Eden nightly 7a6d055094](https://git.eden-emu.dev/eden-ci/nightly/releases):
  the November 1 nightly, published November 2 in Europe/Paris. Changes were
  selected individually; the pinned NX2 engine was not replaced with the desktop
  engine, and its newer build-tool requirements were not imported.

The SSBO work is an original Vulkan adaptation of the dependency/invalidation
principle, not a copy of nxnative's Metal replay or its geometry batching. The
nightly changes retain their existing source license notices.

## Implemented

### Reuse unchanged gathered SSBOs after fixing write publication

`99b-nxnative-gather-coherence.diff` replaces the previous unconditional
re-gather policy. A cache entry records the write generation when its copy is
prepared. Copy/fill commands invalidate it; shader/texel-buffer/transform-feedback
write notifications invalidate it before binding and again **after** the producing
draw/dispatch, through the existing `FlushStorageWrites` boundary. A gather made
after a write was announced but before the shader ran cannot survive that boundary.

Invalidation is deliberately conservative: all gathered aliases are invalidated
in O(1), even for an unrelated source write. Private gather destinations are not
guest source buffers and do not invalidate other gathers. Written groups keep
their gather/scatter path. Buffer deletion retires every dependent view. Exact
source handles/offsets/sizes and write stamps are compared after the hash filter;
matching fingerprints alone cannot authorize reuse. Generation wrap invalidates
all entries. Non-prototype builds retain the old no-reuse behavior.

Read-only groups no longer allocate a per-draw vector of scatter sources. Only a
writable group captures those sources, including a read-to-write promotion in the
same draw. This is separate from the persistent cache's exact source metadata.

`NX2_GATHER_REUSE active=true invalidation=post_producer` identifies activation at
the first gather. `EDEN_NX2_GATHER_REUSE=0`, set before launch, retains conservative
re-gathering for A/B comparison. Existing storage gather/reuse counters remain in
use. No DMA, GPU accuracy, split-mode or shader scheduling setting is changed.

### JIT constant pool

Adapted from [Eden be972d7fdc, #4516](https://git.eden-emu.dev/eden-emu/eden/commit/be972d7fdc50376d231d4f6b0ca912adc958aadd):
mixed pair hashing, compact constant indices, contiguous 128-bit payloads and a
single insertion lookup on the ordinary path. Existing alignment and the trap
before the pool are preserved. Unlike the upstream change, this adaptation keeps
capacity checks, permits duplicates at capacity, and throws `std::length_error`
for a new constant before insertion/store, even if soft assertions return. It
does not mark allocating operations `noexcept`. Addresses remain stable. This targets JIT construction, not execution of an already warm block.

### Contained nightly backports

`99c-eden-nightly-backports.diff` also includes:

- [Texel-buffer descriptors, 3e6a5566 / #4591](https://git.eden-emu.dev/eden-emu/eden/commit/3e6a5566cff1818c3a91e1824e6b672fd3eeb144):
  build a view only for descriptor sets, and convert the format only for a
  non-null device address in descriptor-buffer mode. A null buffer no longer
  attempts to translate pixel format 255.
- [VP9, 0731f40f / #4590](https://git.eden-emu.dev/eden-emu/eden/commit/0731f40f4d86227f05da3fffbc44831065b53a8a):
  snapshot segmentation and probabilities with the frame instead of reading a
  future frame's metadata during delayed encoding. Entropy and segmentation
  probabilities are taken from one guest-memory read, avoiding the duplicate
  probability-table read in the upstream backport.

## Existing mechanisms and deferred ideas

| Candidate | Outcome for this batch |
| --- | --- |
| Conditional-Phi tracking of bindless handles | Already in the pinned NX2 patch, including per-block tracking-cache invalidation. |
| Gather-coordinate adjustment from #4565 | Already present; the PS5 RADV path was already included. |
| NX2 GOB order, partial texture uploads, staging-capacity reuse, descriptor memoization, PGO | Already implemented; not imported twice. |
| Batch small array/cube uploads as in nxnative | Eden already dispatches full ASTC layers together and batches image-copy regions. A Metal-specific direct-upload path is not a drop-in optimization for this backend. |
| Native ARM execution, Metal matrix/mesh paths, tile-renderer store elimination | Require a different CPU/backend implementation; no equivalent PS5 change established in this audit. |
| Remove waits or loosen barriers globally | Not justified. Existing negative `syncshaders`/`fullsync` tests do not prove aliasing or ordering correct. |
| Early submissions / GPU splitting | Existing PS5 submission policy and unresolved split-mode freeze are preserved. |
| Viewport Y flip, Eden 035f4611 / #4558 | Rejected during Cubic review: at negative Y scale its position-dependent branch introduces a discontinuity at the clip-height boundary. Existing conversion retained; focused boundary regression added. No PS5 rendering correction claimed. |
| Desktop mmap VFS or affinity changes | Not imported over the PS5 file/memory budgets and platform-specific CPU policy without evidence on this platform. |
| Bananza terrain/NaN shader fixes from nxnative | Useful shader/resource identifiers, but not evidence that our translator has the same defect. Black surfaces remain unconfirmed. |

## Validation and artifacts

Run only on `dedie`:

```sh
python3 tests-nx2/check-gather-reuse.py
python3 tests-nx2/check-nightly-backports.py
```

The tests extract the production methods and use recording memory/Vulkan
backends, under ASan/UBSan. They cover same-tick writes after a gather, aliases,
copy/fill wiring, read-only reuse, writable promotion/scatter, source changes,
actual constructed hash collisions, sparse views, deletion and generation wrap.
The read-only fixture makes **2 gathers over 1,000 draws with two groups**, versus
2,000 with reuse disabled. It also checks that read-only bindings retain no
scatter-source vector. This is not a game FPS multiplier.

Constant-pool tests cover exact 128-bit payloads, stable addresses, full/empty
capacity and repeated rejection without corrupting existing constants. The
constructed set of 4,096 constants has one old hash value and 4,096 mixed hash
values; this is a collision fixture, not a representative game benchmark.
Viewport boundary continuity, null texel-buffer descriptors and delayed VP9 metadata have separate
focused regressions. These checks do not validate PS5 pixels or video playback.

Native PS5 compilation and packaging: **PASS** on `dedie`. Sparse-header and
multiplayer-header consistency checks, source identity/isolation and packaged
PPSA99862 identity checks passed. The existing real scheduler/upload-guard test
also passed **262,144 mixed events under ASan/UBSan**. The native build retains
PGO; unmatched desktop-profile control-flow records are discarded by Clang and
remain visible in the log.

The isolated root is `/tmp/edglantine-upstream-opt-20261102`; local artifacts and logs are under
`artifacts/upstream-opt-20261102/`: the `.tar.gz` package, exact
`upstream-opt.llvm-pie.elf`, `build.log`, `snapshot-regression.log`,
`source-provenance.txt` and `validation-summary.json` (hashes and validation).
PGO and PPSA99862 are preserved. The user then requested installation and
confirmed the application and launcher were fully closed. All 69 companion files
matched the package. Only `/data/homebrew/PPSA99862/eboot.bin` was replaced with
verified staging, preserved permissions and rename. The previous executable is
retained at `/data/ps5-diag/edglantine-upstream-opt-26f2d97292e9/eboot.bin`.
Journal: `artifacts/upstream-opt-20261102/install-journal.json`.
Initial batch SHA-256: `04859f5b6a06bda8724e43c5174229d92c4d57cf0870e98c512e5f2d33e7e8d5`.
No launch was requested or performed. Game data, saves, settings and caches are
preserved; PS5 rendering and FPS remain unvalidated for this binary.

Cubic retry completed in an interactive PTY without a subscription error. Its
capacity-test finding is addressed with explicit exhaustion handling and a
regression where assertions return. A second finding exposed a discontinuity in
the upstream viewport patch; that backport was removed and a boundary regression
was added. Final review completed with **zero findings** and no error. Repository
context/settings could not be loaded (`Repository not found`); local file review
still ran. No push was made.


## Startup hotfix: generated JIT writable alias

The initial batch crashed in Bananza before any draw. Exact ELF symbolization
identified the compact constant-pool store writing the protected JIT view. The
existing port generator only recognized the old assignment and silently missed
the new one. Raw-source tests with writable storage did not cover that adapter.
`headless/jit-constant-pool.cmake` now redirects the actual generated store through
`writableAddress` and rejects missing or duplicated source anchors. The regression
now tests this generator and real shared RW/RX mappings: original SIGSEGV
reproduced, corrected writes/values and RX protections pass under ASan/UBSan.

Native build/package and clean Cubic review passed. The hotfix is installed after
full closure confirmation; all 69 companions matched. Journal and exact ELF:
`artifacts/upstream-opt-jit-alias-fix/`. The player confirms gameplay starts; black terrain and low FPS persist. See [the Bananza investigation](BANANZA_STARTUP_INVESTIGATION.md).

The player recording and cached reset shader now support a targeted native
indirect-record initialization candidate (`99d-native-indirect-reset.diff`).
It matches the complete lowered SDK program and restores its five stores using
coherent memory operations before retaining the normal Vulkan draw. It is not
a port of nxnative's general raw-address pool table. Validation and console
results are tracked in the Bananza investigation.
