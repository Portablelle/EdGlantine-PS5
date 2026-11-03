# Eglantine coherence and memory adaptations — 3 November 2026

Source audit: `zortos293/Eglantine` nx2 at
[`3bdd53d`](https://github.com/zortos293/Eglantine/commit/3bdd53d08adfd96b7e3e3f09344c514540ef1ce6).
This batch extends the existing PS5 adaptations, rather than replacing the pinned engine.

## Adapted

- [`d7ce3d8`](https://github.com/zortos293/Eglantine/commit/d7ce3d8c0881fc605974d4747573e8a1fcadb37f):
  translate scalar accesses at physical 4 KiB boundaries; never wrap a trailing
  scalar into address zero. GPU block transfers use the existing device-memory
  walker for fragmented backing. The native syncpoint shim and PS5 mappings remain.
- [`5bef735`](https://github.com/zortos293/Eglantine/commit/5bef7354b464a38527864756814cc6e0f0fc6567):
  clip superseded bytes from **each pending fence's copy list**, including splitting
  staging offsets. CPU notifications cancel pending copies before returning to the
  actual store; repeated writes on the same page are notified too. Speculative
  adjacent-page probes use a separate path that never clips fence copies or clears
  GPU-modified ranges. Later GPU
  bindings retain the earlier fences' publication obligations. Newer queued
  selections prevent premature dirty-state retirement; selection epochs also
  protect writes after an all-writes/preflushable policy change between channels.
  No pending-fence staging reuse is enabled.
- From the same change: deferred descriptor invalidation, direct per-table bound
  IDs, overlap-safe uniform-history rotation, empty-stage binding guards, one
  union of fence download ranges and batched shader invalidation. PS5 rejected
  shader invalidation and descriptor memory accounting include the new paths.
  Existing geometric descriptor sizing remains, including the minimum capacity.
- [`d1b7f69`](https://github.com/zortos293/Eglantine/commit/d1b7f69df786b57d5d5c845f721578bed8ba584d):
  release compute SPIR-V modules after pipeline creation; offer age-eligible
  textures in less occupied VMA blocks first. Discovery is bounded to 8192
  candidates per pass, and prefetch/deletion consume the same stable order.
  Occupancy estimates are refreshed every 60 frames; eligibility stays live.
  No change to PS5 shared-memory thresholds, minimum age, dirty-image retention,
  decoding protection or per-pass deletion/scan budgets.

Patch: `eden/tools/eden-patches/99i-eglantine-coherence-memory.diff`.
The port adapters are part of the change and must be validated with generated
native sources; testing only upstream source misses platform rewrites.

## Evaluated separately

- `fae3bc6` submission-snapshot selection: our parser does not use that upstream
  submission-time snapshot mechanism. It retains owned coherent snapshots across
  acquire suspension. Reapplying the upstream conditional would not fix this path.
- Split publication hints, partial waits, SYNC_WAIT drain omission and asynchronous
  omitted draws: not imported over the existing PS5 owner-thread synchronization.
  They depend on a different split architecture; some are explicitly unsafe opt-ins.
- Desktop-versioned cache filenames address official/fork binaries sharing a cache
  directory. Our PS5 app has a dedicated data location and cache version tags;
  no desktop cache migration or automatic cache deletion is introduced.
- Fire Emblem's DLSS substitute is title/fingerprint-specific and depends on the
  fork's temporal/spatial blit plumbing. Its latest jitter revision lacks a player
  validation. It is not a general Bananza/Mario Kart rendering improvement.
- Splatoon 69-byte vertex repacking is separate compatibility work. The upstream
  fallback can keep old buffer bindings when conversion fails after input offsets
  were changed; it must not be enabled blindly on this port.
- New desktop branding (Lichii), Qt/CI, NUP packing, Windows waits and presentation
  pacing do not replace the PS5 launcher, file budgets or native presentation.
- Semaphore scheduling already differs: this port bounds scheduler retry passes
  and retains its native acquire parser. New hardware predicates require an
  observed command stream before changing those platform-specific paths.

## Validation

Build and sanitizer checks run only on `dedie`, in the isolated directory
`/tmp/edglantine-refresh-20261103`. Results/artifacts are collected under
`artifacts/eglantine-refresh-20261103/`.

This batch produces a package only; it does not install or launch it on PS5.
No PS5 FPS improvement, game startup success or rendering correction is established
by a successful host test or native build.

Results: source and generated-native sanitizer regressions PASS, descriptor/VFS
memory checks PASS, existing native command readback suite PASS, complete ordered
patch-series comparison PASS (17 files), native PS5 compilation/package PASS.
PGO is retained; incompatible function-profile records are discarded by Clang
with warnings in the build log. Sparse and multiplayer header checks and package
isolation checks PASS. Console rendering/performance remain unvalidated.

Package: `artifacts/eglantine-refresh-20261103/EdGlantine-PS5-eglantine-refresh-00.065.000.tar.gz`.
Exact ELF, eboot, build log and SHA-256 manifest are retained alongside it.

Packaged eboot SHA-256: `294130bb6e199f04d4d546da164af49549f345a40e17751486b3be07a6000dd0`.

The final isolated Cubic review completed with zero findings and no error.
Earlier findings concerning GPU-fence publication, null-image block lookup and
speculative adjacent-page probes are corrected and covered by sanitizer regressions.
GitHub repository context was unavailable in the isolated snapshot; local source
and adapter review completed. No push was made.
