# Eglantine performance adaptations — 2 November 2026

This batch adapts two upstream changes to the PS5 source patch series:

- [46b2577](https://github.com/Djihads80/Eglantine/commit/46b2577bf78870ed85cbb790a9dc3c82cc77f4a7): skip empty graphics buffer stages and redundant uniform-buffer disables; reject missing uniform-address translations.
- [a407703](https://github.com/Djihads80/Eglantine/commit/a407703f6d29a5ab73328b4ededb12cf29b2758d): avoid eager initialization of fiber stacks and the Vulkan descriptor ring; permit old costly textures to be reclaimed under memory pressure; bound buffer lookups to the device address space.

The GC keeps the existing PS5 shared-memory thresholds, work budget, decoding
protection, download-before-deletion and image accounting. Native prefetch and
deletion share the costly-image predicate and the pass cutoff; each pass has
its own bounded scan allowance so protected old images cannot starve the normal
pass. The extra old-image
pass uses 1800 frames by default; `EDEN_NX2_TC_OLD_AGE=0` disables it. Unlike the
upstream version, it respects `EDEN_NX2_TC_MIN_AGE` and stops admitting costly
evictions once memory drops below the expected budget. It is frame-based, not a
fixed number of seconds. Buffer range validation covers the end of the requested
range as well as its first address, before page-table lookup or allocation.

Descriptor entries are assigned before publication; the ring capacity, frame
rotation and scheduler ownership are unchanged. Fiber canaries and context setup
remain initialized; unused stack bytes no longer require eager zeroing.

## Excluded from this batch

The Linux `fallocate(PUNCH_HOLE)` memory change is not a PS5 mechanism. The ASTC
submit-before-BCn change was already adapted by `99-nx2-bcn-decode-submit.diff`.

[8f1435f](https://github.com/Djihads80/Eglantine/commit/8f1435f8db104351fa3388551eee9d12d2043b40)
introduces producer-side command-page copies and partial waits for the split
front. Its synchronization and GPU-written-page tracking differ from this port's
owned snapshots and exact dirty-range readback cache. It is not applied here.
GPU splitting remains disabled; existing command coherence is retained. The
earlier cache test reduced simulated waits from 64 to 1, but player retesting
did not establish an overall FPS gain. See the Bananza investigation history.

Splatoon vertex repacking and Fire Emblem-specific rendering/keyboard changes
are separate compatibility work, not included in this performance batch.

## Validation

`eden/tests-nx2/check-eglantine-performance.py` executes the actual patched
collector with the real LRU container, including its generated native version
and batching/dirty-texture retention, plus the real buffer lookup/binding
methods, under ASan/UBSan on `dedie`. It covers recent/old textures, recovery
below budget, decoding, downloads, bounded work, disabled old eviction, minimum
age, early frames, unmapped bindings and invalid/overflowing device ranges.

Native compilation and packaging run in `/tmp/edglantine-perf-20261102` on
`dedie`, isolated from the previous build, with the existing PGO profile.
Results and artifacts: `artifacts/eglantine-perf-20261102/`.
No PS5 FPS gain or rendering improvement is established by these host checks.

Results: source and generated-native sanitizer tests PASS, existing command
coherence suite PASS, native build/package PASS, sparse and multiplayer header
checks and package isolation PASS. PGO retained; incompatible function-profile
records were discarded by the compiler with warnings. Installed after the player confirmed app closure; console retest pending.

Native lookahead accounts for clean and oversized evictions as well as batched
downloads, stopping at the first relevant pressure transition. Regressions cover
5000 protected old dirty images before a younger clean image, and budget recovery
that must retain a dirty image without downloading it.

Final local Cubic review: zero findings, no error. Remote repository context was
unavailable (`Repository not found`); local file review completed.

Installation replaced only `PPSA99862/eboot.bin` after verifying all 69 companion
files match. Previous binary: `dae8638c99652d3c7d11920eadf021e22d1b1f98639ac775e69cb4dd2fc7aeb4`.
Installed binary: `a20cb8d1587cdb095c07d1afc0a4c4c99e7cac6ce817b95470a9e9bc763ba3a5`.
Rollback: `/data/ps5-diag/edglantine-performance-e27aafc7d830/eboot.bin`.
The install journal records verified staging and publication. Game data and
settings were preserved; the application was not launched automatically.
