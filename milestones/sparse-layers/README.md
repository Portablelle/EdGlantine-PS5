# Safe sparse layers — NX2 prototype 00.006.000

## Integration

The Vulkan cache's original-image creation path now calls `TryMakeSparseLayerImage`
before the ordinary allocator. It runs only when `EDEN_NX2_SPARSE_LAYERS=1` is
explicitly present. Missing, empty or any other value selects the ordinary path.
The package does not set this option.

This initial integration is deliberately **fully resident before publication**:
one allocation per layer, plus a single allocation if the mip tail is shared,
and binding of every visible sublevel. No shader, upload, ASTC decode, rendering
or download receives a partially bound image. There is no API for evicting a layer
from a published image. This avoids assuming that PS5 driver holes read as zero.
**This milestone does not yet provide selective layer streaming or a measured
memory gain.**

Rescaled images stay on the ordinary path. Formats and usages actually supplied
by the cache, including ASTC substitutions and mutable views, are preserved.
Admission requires a multilayer 2D color image, one sample, sparse 2D support and
the appropriate queue. Vulkan creation and actual requirements determine format
support. Multiple aspects, metadata, nonstandard blocks and unsupported layouts
are rejected before binding.

## Allocations and lifetime

`vk_sparse_layers.h` plans offsets and sizes using bounded calculations:
texel granularity, layers/mips, individual/shared tails, alignment, range limits
and budgets. Allocations use only a device-local memory type allowed by
`memoryTypeBits`, without spilling into a desktop budget. Conservative lab limits:
**64 MiB per image and 128 MiB total sparse memory per process**. These are not
budgets for the entire engine.

States: Empty → Allocated → Binding → Resident → Retired; Quarantined if GPU
completion is unconfirmed. Layers become accessible to the cache only after the
bind and its fence succeed.

To change/destroy mappings, the backend finishes recorded commands, waits for
the submission worker, then waits for the device under the submission mutex.
The bind is submitted under the same mutex; its fence must complete before
publication. This deliberately global approach can cost frame time. The mutex
is never held during `Scheduler::Finish`, because the worker must be able to
acquire it. This backend targets the current cache, the sole GPU-command owner.
Future use by other producers/queues must extend the protocol.

On partial failure, wait for the GPU, destroy the virtual resource and its fence,
then free physical allocations. BindSparse is not assumed atomic. If the wait
fails, handles and allocations are retained, the budget remains charged, new
sparse admissions are blocked and the error propagates as device loss. This
quarantine is deliberately unrecoverable within the process: no unsafe release
or silent retry. It may retain up to the experimental budget until process exit.

`vk::Image` has a specific backing owner for these images: moves and replacements
transfer ownership, and destruction never passes them to `vmaDestroyImage`.
They are not marked Unbacked. Ordinary VMA paths retain their behavior.

If admission or sparse allocation fails with confirmed recovery, the cache tries
an ordinary image. When the experimental option is active, this fallback cannot
become the fork's old unbacked sparse fallback; if the ordinary image does not
fit, allocation failure propagates. Historical fallback behavior is unchanged
when the experimental option is disabled.

## Checks

- Default policy and production manager under ASan/UBSan: RGBA/BC mips and layers,
  shared/individual tails and entirely tail-resident images, overflow, limits,
  global budget, allocation failure, partial bind, exceptions, failed waits,
  quarantine, retirement and destruction/release order.
- Actual `vk::Image` and the source-extracted `Image::Release` body: move,
  replacement, self-move, reset, single release and distinction from ordinary
  backing, under ASan/UBSan.
- Targeted engine suite: 380 cases, 1,870,846 assertions passed.
- Native build and final checks: definitive results in `TEST-REPORT.md`.

Tests mock the device, allocations and GPU completion. They do not establish
PS5 kernel-call behavior or console rendering. The RADV harness in
`experiments/sparse-textures/` complements them with mapping calculations
extracted from the pinned driver.

## Next step

To save memory per layer, track actual view accesses, read/written layers,
filtering and accessible sublevels; publish only proven resident sets or provide
safe hole semantics. Then replace global waits with targeted dependencies and
lifetime proof for every user. Do not enable these optimizations merely by
changing the PRT flag or budget.
