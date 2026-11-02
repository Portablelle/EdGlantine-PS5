# Large sparse-guest texture updates and native PGO

Source adaptation and installation, 2 November 2026. No PS5 FPS result is
established for this build. Title PPSA99862 and the existing runtime data paths
are unchanged.

## Partial transfers

Adapted from [Eglantine 1c794af5](https://github.com/Djihads80/Eglantine/commit/1c794af56407f324eedad99478388ba0c9cf9ad6):
large single-layer 2D colour masks need uploads of changed guest blocks rather
than an entire image whenever the game streams a tile. Core patch
`98-nx2-partial-sparse-transfers.diff` extends the existing partial uploader to
images with discontinuous guest memory. It does **not** import unbound host
images, lazy device allocations, shared zero blocks or selective residency. The
ordinary fully allocated PS5 image and its initial full upload remain in place;
this saves recurring CPU reads/unswizzling/uploads, not its resident VRAM.

- Eligible images are at least 32 MiB, single-layer 2D colour, single-sample,
  one texel per format block. Converted, ASTC-accelerated, asynchronously decoded,
  unbacked, trimmed, scaled, GPU-modified and invalidated images retain the old
  path. The existing PS5 partial-transfer switch and minimum-size setting apply.
- Sparse CPU writes are translated through every physical map view, including
  aliases. Whole physical pages are dirtied before their cached-page references
  are removed. Each (physical page, map view) is decremented once and restored
  once; subsequent writes on an untracked page cannot escape the dirty range.
- Map/unmap notifications merge guest byte ranges. The host image stays indexed
  by GPU address, including when its first physical page moves or becomes a hole.
  Before its next use (also a render-target clear), old physical map views and
  their page references are retired and rebuilt from the current mapping. GPU
  indices, LRU membership and memory accounting stay intact. New physical views
  are also marked in the PS5 mixed buffer/texture coherence tracker.
- Overlapping/adjacent ranges are merged. More than one quarter of the guest
  image or 4,096 ranges selects a full refresh. Unsupported layouts also fall
  back to the established full uploader.
- The GOB-rectangle planner now stores runs of dirty blocks rather than an
  image-sized bitmap and visits only affected bands. Mips, explicit/calculated
  layer strides, horizontal padding and the NX2 byte permutation are preserved.

## Profile-guided optimization

`headless/pgo.cmake` accepts an explicit `EDEN_PGO_PROFILE`. It applies Clang PGO
only to `video_core`, `shader_recompiler` and `dynarmic`, preserving the existing
ThinLTO/Zen 2 policy and the ordinary build of the core/fibre code. Empty means
PGO off. Missing, corrupt or incompatible profiles fail configuration. A
SHA-256-named build-local copy makes changed profile contents invalidate compiler
commands even if the input filename is reused. No profile is downloaded by CMake.

The build uses the upstream [Eden-CI/PGO v020525 profile](https://github.com/Eden-CI/PGO/releases/tag/v020525),
also used by Eglantine's PGO workflow. This is a desktop training profile, not a
PS5/NX2 workload capture; new or changed functions can have no matching record.
The file's binary format requires LLVM 21, while this port pins LLVM 18. Run on
the build server:

```sh
bash tools/prepare-pgo-profile.sh /work/eden.profdata /work/eden-llvm18.profdata
EDEN_PGO_PROFILE=/work/eden-llvm18.profdata bash tools/build-headless-native.sh --graphics
```

The converter uses LLVM 21's text export and LLVM 18's writer, then compares the
round-tripped text byte for byte. It neither invents counters nor upgrades the
native compiler. Input SHA-256:
`777dd9aefb9427ed08a642b02998f32c5ac120e5d32611d8f21cf1f4e68cee57`.
Converted SHA-256:
`eaf5dd4034af1164fd3dbde8bd28b349f01c49e6706660f89db1331042019d77`.
The converted profile contains 67,467 function records. Clang uses matching
records and ignores missing/outdated ones; the focused PGO check inspects actual
native IR for nonzero function-entry counts rather than treating a successful
link as proof that useful profile data was applied.

## Build and checks

Isolated build root on `dedie`: `/tmp/edglantine-partial-pgo-20261102`.
Pinned dependencies are mounted read-only. RADV's generated linker map and
ccache's temporary files have separate writable directories under that root.
The compiler cache is read-only and does not share source/build outputs.

Run after preparing/configuring the native source:

```sh
python3 tests-nx2/check-partial-sparse.py
python3 tests-nx2/check-eglantine-pages-textures.py
python3 tests-nx2/check-pgo.py
python3 tests-nx2/check-isolation.py
```

The first two scripts compile extracted production methods under ASan/UBSan.
The new decoder differential test includes the real production decoder and
compares partial rectangles with full decoding, then applies them to a pre-write
image to detect missing coverage. It covers both byte layouts, R8/R16/RGBA/RG32,
mip chains, odd dimensions, duplicate/unsorted ranges and horizontal padding.
There are 192 deterministic layout cases. A 16,384 × 16,384 R8 mask with a 64 KiB
change reads and emits 65,536 bytes instead of 268,435,456 bytes for a full upload
(4,096 times less in this fixture, not a frame-rate multiplier).

Tracking checks cover aliased physical pages, repeated writes, changing/removing
mappings, moved first pages, clear-before-sampling, exactly-once page counts,
format exclusions and bounded fallback. The PGO check inspects native compiler
commands and real native IR, and verifies invalid inputs and disabling PGO.
Shared texture fixture declarations explicitly select recording or real decoding.

The native IR check passed with nonzero function-entry profiles on 2 functions
in the sampled DMA-pusher translation unit, 15 in constant propagation and 17 in
the A64 emitter. These are sampled units, not whole-program coverage figures.
Missing/corrupt inputs are rejected, and switching PGO off removes the flags.
Final build results and artifacts are recorded after validation below. Host
checks cannot validate PS5 driver execution, sustained memory use, rendered pixels
or performance in a game. No performance percentage or hardware improvement is
claimed without a same-scene console comparison.


## Final result

- Native PS5 compilation/link on `dedie`: **PASS**, using the standard native
  build entrypoint with its integrated source/lifetime/header checks.
- Production sparse mapping/page tracking and decoder comparisons under
  ASan/UBSan: **PASS**. The inherited memory-owner, page-batching and texture
  stride/layout groups also **PASS**.
- PGO target flags, real native IR, invalid-profile rejection and disable
  transition: **PASS**. The sampled units have 2/15/17 nonzero profile entries;
  CFG mismatches in the desktop profile are discarded and remain visible in logs.
- Native packaging, SELF inspection, alignment and PPSA99862 isolation: **PASS**.
- Local Cubic review: no issues after replacing implicit test-fixture rewriting
  with the explicit shared fixture.

Artifacts in `artifacts/partial-textures-pgo/` (ignored by Git):
`EdGlantine-PS5-partial-pgo-00.065.000.tar.gz`, `llvm-pie.elf`, `SHA256SUMS`,
`validation.log`, `package.log`, `pgo-validation.log`, `validation-summary.json`
and `pgo-build-provenance.txt`. The focused-validation log also retains the first
PGO test selector failure, corrected before the separate successful PGO check;
this was a test lookup issue, not a native build failure.

The package keeps version 00.065.000. Console installation is recorded below.
No gain in game FPS or rendering correction is established by the host checks.


## Console installation

The user confirmed the application fully closed before replacement. All 69 packaged
companion files matched the installed copies, including title metadata and runtime.
Only `/data/homebrew/PPSA99862/eboot.bin` was replaced using raw SELF transfer,
verified staging, preserved executable permission and activation by rename.
Previous executable retained at `/data/ps5-diag/edglantine-partial-pgo-4fa7fffcc2c9/eboot.bin`.

Installed SHA-256: `10b01c1f4135b33887b302b9d15b35a3453efe9dc8716ff9081c3a74914b373e`.
Journal: `artifacts/partial-textures-pgo/install-journal.json`; companion checks:
`installation-preflight.json`. User data and settings were preserved. No launch
was performed; the user will test game performance.


## First Bananza console result

The user reports about 10 FPS, falling to 4 with much movement, with black areas
still visible. A retrieved five-second frame sample reaches 3.554 FPS. No native
shader rejections or allocation failures occur in these snapshots; 26 unmapped
Device ReadBlock messages and a 759 MiB texture-upload interval need attribution.
No matched-scene baseline or isolated PGO/partial-transfer gain is established.
See `eden/docs/BANANZA_STARTUP_INVESTIGATION.md` and the measurements in
`artifacts/partial-textures-pgo/bananza-retest/`. Settings were left unchanged.
