# Sparse texture residency: PS5 NX2 lab

Status: audit and host tests passed on the build server; diagnostic library
cross-compiled for PS5. **No engine integration, no per-layer sparse activation,
no deployment.** This document describes the initial 00.005.000 milestone.
The manager later integrated in 00.006.000 is described in
`../../milestones/sparse-layers/README.md`; it uses full residency before
publication without relying on zero-filled holes.

## Verified findings in the pinned driver

PS5 RADV: `7b59ef27c1b09b9671bc4153c41940c3155c3af2`.
Examined sources: the copy actually prepared for the build under
`/work/mihawk-vulkan-review/.deps/work/radv-src` on the dedicated server.
Hashes of tested units are in `../../artifacts/sparse-audit/source-hashes.json`.

- The winsys sets `has_sparse=true`, `has_sparse_cpu_binds=true` and
  `has_sparse_prt=false`. RADV advertises `sparseBinding` and
  `sparseResidencyImage2D` when sparse queues are not disabled. Graphics/compute
  families then expose the sparse-binding bit. These are findings from the
  pinned source, not queries to the PS5.
- `shaderResourceResidency` and `residencyNonResidentStrict` remain false.
  Unbound ranges point to a shared physical 2 MiB block, initially zeroed.
  Writes can change its contents, so it does not guarantee zero for later
  reads from holes.
- Vulkan 2D granularity is expressed in **texels**: 128×128 for RGBA8 and
  256×256 for BC3, or 64 KiB per tile in both cases. Binding then converts BC
  coordinates to compressed blocks. Do not apply the format's factor of 4
  again to the Vulkan result in this driver.
- The GFX9+ path separates layers, then mips, and uses per-layer mip tails.
  Actual offsets/strides/sizes must still be queried from each image's sparse
  memory requirements after creation; dimensions and format alone are insufficient.
- PS5 mappings require multiples of 16 KiB. Virtual ranges are reserved in
  2 MiB granules, while bindings can be finer.
- CPU bindings wait for supplied semaphores before changing mappings. A submission
  mutex does not replace waiting for GPU work that uses the old mappings.
- Binds are not transactional: failure on the second row can leave the first bound.
  Multi-part unbind has the same issue. A failure result does not imply that no
  mappings changed.

## Prepared components

`probe.c`/`probe.h` query physical capabilities, the selected family and the
format with the requested usages. Diagnostics distinguish physical availability
from logical-device enablement. They allocate no images and submit no work.
The experimental request is explicit; the disabled case is tested. For the first
design, which assumes holes read as zero, the probe blocks when
`residencyNonResidentStrict` is false. This does not mean every sparse use of the
driver is forbidden: a design guaranteeing access only to resident subresources
must be studied separately.

`extract-driver.py` extracts production functions from RADV units without rewriting
their algorithms. The harness replaces the device, winsys and system calls with
mocks that record mappings and inject errors. Tests execute the actual calculations
and call order under ASan/UBSan:

- RGBA8 and BC3 granularities; layer and mip offsets; edge tiles;
- multiple rows, opaque mip tail and unbind;
- wait before mapping and refusal to map if the wait fails;
- error after an initial bind and an initial unbind segment;
- PS5 alignment, range overflow and unavailable shared block;
- disabled diagnostics, features not enabled, rejected queue/format, no zero-read
  guarantee and lists exceeding diagnostic bounds.

All pass. `run-dedicated.sh` also compiles `probe.c` with `prospero-clang` and
creates `libnx2-sparse-probe.ps5.a`. This is a diagnostic library, **not an ELF
to launch or a new emulator version**. It is not linked into any existing package.
The tests execute neither GPU work nor PS5 memory APIs.
Logs and artifacts: `../../artifacts/sparse-audit/`.

## Next porting stage

1. Add a per-image/layer planner based on actual requirements: granularity,
   alignment, memoryTypeBits, individual/shared mip tails, metadata and sizes
   checked for overflow. Define global limits suitable for the PS5 shared pool;
   do not copy desktop per-image budgets.
2. Choose safe hole semantics. Without strict PRT, retain ordinary images by
   default. Study views restricted to resident layers and make every destination
   resident before transfers, ASTC compute or rendering. Sampling and filtering
   that can cross a boundary must also be covered; a list of written layers alone
   is insufficient.
3. Explicitly manage the allocated → partially bound → bound → in use → retired →
   unbound → freed lifecycle. On partial failure, retain allocations that may
   remain mapped until recovery is proven or the device is destroyed in a
   controlled manner. Eglantine's `roll_back()`, which frees after BindSparse
   failure, cannot be copied unchanged.
4. Synchronize old GPU users, binding, then uploads/decoding and new readers.
   Cover other queues too. Test remapping, destruction and fence failures;
   `submit_mutex` alone is insufficient.
5. Connect the residency owner to the already imported NX2 tracker without
   duplicating page notifications. Once these invariants are covered on the
   dedicated server, integrate behind a disabled option and build a separate variant.

No driver capability flags need changing at this stage. Forcing PRT/strict to
true without implementation would create a false guarantee. Later console
validation must confirm actual queries, data read after bind/remap, barriers
and rendering under memory pressure. It requires a task explicitly authorizing
console access.
