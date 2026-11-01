# Eglantine — PS5 integration 00.008.000

Examined source: Djihads80/Eglantine, `b40ad217ab829226841cb71f6e4c5cb05977a225`.
Diff from our reference `6f5e137ec4eb83bbff9ea15f1ad1a8407cfc0cba`;
ASTC optimization from `97ce27ab35153884d2fd05c278433928e429cd91`.
Source patches are retained here for provenance; they must not be reapplied to
the final prototype.

## Adaptations

- End contiguous physical-page runs on map/unmap; reset counters for replaced
  pages, including untracked mappings and holes. The port's CPU backing and
  translation generations are preserved.
- Vulkan cache: reject truncated headers and write through a temporary file in
  the core. The PS5 port already generated an atomic writer; it is retained,
  waiting for the serialization worker and saving only when necessary. A failed
  save preserves the previous valid file.
- Docked/handheld notifications: NX2-specific refresh event, propagation from
  ApplySettings and detection of actual mode changes. Command 210 retains the
  fork's experimental interpretation.
- ExeFS dumps: read NACP and icons from the game directory, including
  updates/title-id/exefs; prefer the NACP version. Otherwise fall back to
  ResourceSizeTable.Product.NNN in the neighboring RomFS, a heuristic that does
  not necessarily distinguish hotfixes. Directory names are not parsed.
- ASTC: select affected layers from our dirty-page tracking, restore page counters
  exactly once, decode in Vulkan per layer and mip, and batch staging toward
  32 MiB (a single layer may exceed that budget). Eligible images >=64 MiB use
  this optimization; other paths retain full transfers. ASTC-to-BC transcoding,
  rescaled images, asynchronous decoding, unbacked images and guest sparse
  mappings are excluded. Levels retained after trimming large mips are respected.
- Release CPU upload scratch buffers over 64 MiB on the next frame and add
  upload-volume counters for future comparisons.
- Adapt the fork's RET R0/R55 tests to our explicit return-register high-word
  validation; the RET fix itself was already in our engine.

ASTC tracking uses the same `tex_partial` setting as existing partial transfers:
disabling it restores full uploads. Vulkan allocations remain resident; no
assumption that holes read as zero is introduced. The 00.006 sparse budgets are
unchanged and remain opt-in.

## Not integrated

- “FSR3” and frame generation: experimental implementation with history-management
  issues; not imported.
- Forcing a Vulkan 2D/3D view type different from what the shader expects: the
  MoltenVK workaround is insufficient to guarantee valid PS5 sampling.
- Qt/Android UI and Qt library scanning: not used by the PS5 frontend.
- Selective sparse residency and lazy GPU-region allocation: require a PS5-driver
  adaptation; not enabled by this import.
- QMD history cleanup: the previous rejection remains in effect.

The Welcome Tour gather fix and rejected-video-codec trace are coordinated in
`../gather-panic/ANALYSIS.md`. This version does not provide a VP8 decoder and is
not claimed to fix the PANIC.

## Validation

Builds and tests run exclusively on the build server, with isolated copies under
`/tmp/ps5-nx2-prototype-20261030`. Native builds use the configured dedicated-host
build image; Linux engine tests use `nx2-host-tests-build` (includes OpenSSL).
Final validation: 395 cases / 1,877,310 assertions passed; native and package
checks passed. See `../../artifacts/eglantine-update/TEST-REPORT.md`.
