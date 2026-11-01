# Next steps for the NX2 PS5 prototype

## Per-layer sparse texture residency — dedicated audit completed

This work is retained for a future task.
This note does not authorize deployment or console access.

First milestone completed: `experiments/sparse-textures/README.md`. The driver
provides bindings and advertises 2D residency, but does not guarantee zero reads
from holes. Tests of the RADV routines under ASan/UBSan and a PS5 cross-compiled
diagnostic library passed on the dedicated server. No per-layer residency path
is enabled by default.

Second milestone: 00.006.000 integrates the layer manager, budgets,
synchronization and error quarantine. It binds all visible layers before
publication. See `milestones/sparse-layers/README.md`. The remaining priority is
to prove layer-access bounds to enable selective residency, then introduce finer
GPU dependencies; no selective memory saving is claimed yet.

Reference: [Eglantine](https://github.com/Djihads80/Eglantine), revision
`6f5e137ec4eb83bbff9ea15f1ad1a8407cfc0cba`, particularly commits `6380b66`,
`97ce27a`, `940d44c` and `d4ee7fc`.

Version 00.008 integrates uploads/ASTC decoding of modified layers without
selective residency; see `milestones/eglantine-update/README.md`.

Goal: avoid reserving and retransferring every layer of large, sparsely used
textures. Allocate GPU blocks and image layers on demand, and decode only
modified ASTC layers again. PS5 gains have not been measured.

Work possible on the dedicated server without console access:

1. Inspect the port's pinned RADV driver and Vulkan layer: exposure of
   sparseBinding, sparseResidencyImage2D, residency properties, formats and
   queues compatible with vkQueueBindSparse.
2. Compare Eglantine GPU-memory paths with the already imported Eden-NS2 paths.
   Define a single owner for tracking modified blocks, layers and pages.
3. Prototype behind a disabled-by-default option, with capability detection and
   fallback to ordinary images when the format or driver does not support this
   residency. Adapt limits to the PS5 shared pool.
4. Test layer/mip calculations, uncommitted blocks, writes and remaps, barriers,
   allocation failures and release after GPU use. Cover rendering into these
   images as well as reads.
5. Build and package a separate variant on the dedicated server; retain the
   validated prototype for comparison and rollback.

Later hardware validation requires a task authorizing console access: confirm
actual driver capabilities, then compare committed memory, transfer volumes,
frame time, rendering and stability in the same scene. A successful build or
Eglantine desktop measurements are not enough to enable this path by default
on PS5. Legacy Switch 1 engine work remains out of scope.

## Eden-NS2 shader tests — fixed in 00.005.000

All eleven cases were reconciled: eight control-flow validation fixes and three
outdated expectations replaced with semantic checks. The targeted suite passes:
380 cases and 1,870,846 assertions. See `TEST-REPORT.md` and
`milestones/shader-fixes/ANALYSIS.md`. In-game graphics qualification on PS5
remains to be performed in a task explicitly authorizing console access.
