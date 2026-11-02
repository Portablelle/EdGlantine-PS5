# NX2 memory accounting and CPU readback

Integration on 2026-11-02; no deployment or console result. Existing .065 rendering
investigation, shader policy and shared CPU/GPU pool accounting remain in place.

## Provenance and selected adaptations

- [mucahidkambur dbadad0](https://github.com/mucahidkambur/EglantinePS5/commit/dbadad075ca18cced6adafea325a26c454dc94c6): concrete `Image` accounting in Vulkan GC lookahead. Rather than deriving code by text replacement from `DeleteImage`, registration/deletion/lookahead share explicit core helpers. Lookahead and deletion saturate subtraction when the pool reading is below the estimates.
- [Eglantine 2065b14](https://github.com/Djihads80/Eglantine/commit/2065b1431c0ecfeade61a7e7511889c4800b6bb9): unbacked images count zero, main device-local heap budget is counted once, and desktop texture thresholds retain budget headroom. Unused VMA block space is subtracted per heap, capped to that heap's usage. The PS5 shared-pool override and desktop-threshold exclusion remain intact.
- [Eglantine 41a81ab](https://github.com/Djihads80/Eglantine/commit/41a81ab5e3d88b53b634ed765385874728634e9f): query GPU-written buffers on CPU reads; buffer writes and DMA copies into previously CPU-read pages are downloaded at fences even when broad NX2 fence downloads are disabled.

The PS5 A64 guest uses the slow/page-table read path without fastmem. For NX2,
these cached reads now reach `HandleRasterizerDownload` even with reactive
flushing off. The first read learns the buffer pages; subsequent GPU writes to
those pages use normal fence downloads. The full desktop fastmem read-trap
machinery is not imported; NX2 with fastmem and reactive flushing disabled keeps
its existing behavior and is outside this PS5 adaptation's validation scope.

The PS5 rasterizer queries buffers independently of `ImagePages::NeverHeld` and
combines the texture/buffer answers. A clean texture cannot mask a dirty buffer.
It remembers only the queried pages, never a wider texture area containing unread
buffers. `cpu_read_skip` no longer skips this coherency query.

The desktop automatic BC3 setting, artificial VRAM cap, lazy sparse-layer backend
and BCn mip trimming are not imported. They do not match our explicit PS5 ASTC
policy and all-layers-before-publication sparse backend. Other recent Pokopia
boot/service/shader fixes already have local equivalents; no wholesale core bump.

## Build and validation

Core delta: `eden/tools/eden-patches/91-nx2-memory-readback.diff`, after `90`.
Prepared-source identity now hashes all core patches: layered patches must never
be reversed against a tree already modified by a later layer after an update.

All compilation runs on `dedie`, in `/tmp/edglantine-memory-20261102`.
After native configuration:

```sh
python3 tests-nx2/check-memory-readback.py
```

Tests extract production methods with recording backends under ASan/UBSan:
CPU read gate, mixed clean/dirty texture/buffer queries, page-bound restriction,
selective fence writes, reads crossing learned/unlearned page boundaries,
unbacked/converted/scaled image accounting, saturated
GC/deletion subtraction, and multi-heap budget/usage accounting.

Validation: native PS5 compilation/link and the integrated source/lifecycle checks
PASS on `dedie`. All five extracted production ASan/UBSan groups and the layered
patch-cache lifecycle fixture PASS. The inherited performance-settings check was
updated to expect the already-existing per-game DMA choice and its corresponding
CPU-write deferral, rather than a forced unsafe DMA setting.

The final link uses an isolated writable directory for RADV's generated symbol
map; the dependency source trees stay read-only. The build first caught a private
method exposed to the rasterizer, corrected before the final successful link.

Local artifacts (ignored by Git): `artifacts/memory-readback/eden-headless.elf`,
`memory-validation.log` (final link, integrated checks and targeted tests), and
`memory-build-final.log` (compilation and the initially stale settings check).
The binary retains the existing title/version; it is not installed or packaged
for deployment by this task.

These checks cannot establish PS5 pixels, compatibility, FPS, or a fix for
Pokopia's flicker/black sky.


The complete 90–94 source candidate now includes this integration together with
library, memory-ownership and rendering fixes. Final installation is recorded
separately by `artifacts/00.065.000-final-review/install-journal.json`; the original
standalone artifact above must still not replace the cumulative application.
Hardware rendering and performance remain unvalidated.
