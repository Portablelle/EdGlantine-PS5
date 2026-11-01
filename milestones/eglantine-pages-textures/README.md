# Eglantine: pages and texture strides

Targeted integration on November 1, 2026, preserving ongoing PS5 changes.

Provenance:

- [zortos293/Eglantine badc91e](https://github.com/zortos293/Eglantine/commit/badc91ebce6b6cb44eabe67f7aa0dbbc6abd9e46): batching partial pages in `MarkPartialWrite` and `RestorePartialPages`, updating the current ASID in `UpdatePagesCachedCountNoLock`.
- [zortos293/Eglantine 11a1108](https://github.com/zortos293/Eglantine/commit/11a110898fcfe16a5b9aee98c4346265825c3178): explicit layer stride (calculated fallback when zero), row alignment during swizzling, partial-band size independent of trailing padding, and downloads of textures with horizontal spacing.

The existing NX2 patch retains all its other changes. The three modified sections
were compared with their saved pre-integration state. Corresponding working
sources in `core/` are synchronized with those sections. PS5 partial-transfer
diagnostics and format exclusions remain in place. Memory budgets, the JIT and
pipelines are unchanged. The additional DMA shutdown fix is detailed below.

## Targeted tests

Run exclusively on the build server after preparing sources:

```sh
python3 tests-nx2/check-eglantine-pages-textures.py
```

Actual methods are extracted from prepared sources and compiled under ASan/UBSan
with recording backends:

- A→B→A owners at contiguous virtual addresses, increment/decrement, same owner,
  holes and discontinuous addresses.
- One thousand new pages in one call, repetition without double decrement,
  2,000 deterministic ranges compared against a per-page oracle, restoration and
  a page boundary in an unaligned image.
- Full/partial transfers: explicit 64 KiB stride, calculated fallback, multiple
  layers and mips, horizontal alignment, padded bands, writes affecting only
  padding, and fallback for unsupported multisampling.

Decoder calls are recorded: these tests validate the addresses, sizes and
alignment passed to them, not the resulting pixels or the PS5 driver.
All three groups: PASS on the build server under ASan/UBSan.

Previous states, the integration-specific delta and logs are retained locally
in `artifacts/eglantine-pages-textures/` (not versioned). No console installation
or FPS result was claimed at this stage.

The inherited startup check expected nine workers despite the existing addition
of `GPUBack`. It now expects ten and explicitly asserts the presence of `GPUBack`;
thread behavior is unchanged.

The GPU lifecycle check is also updated for the existing `!split.Active()` guard
and loading hook. The wait fixture simulates synchronization calls and backend
failure.

This check exposed an earlier regression: the CMake substitution still searched
for the old DMA wait and no longer protected the new NX2 loop against shutdown.
The adaptation retains that loop, including error checks and traces, adds the
shutdown check and now requires its replacement anchors to be present.

## Final result

Native PS5 build on the build server and all integrated checks: PASS.
Retrieved binary: `artifacts/eglantine-pages-textures/eden-headless.elf`.
The complete final build log is `build.log`; targeted tests are recorded in
`eglantine-pages-tests.log`, and DMA shutdown in `eglantine-sync-check.log`.
The title version was unchanged at this stage; this binary was not deployed.

## Installation 00.063.000

The binary was rebuilt on the build server after incrementing `contentVersion`,
then the package was validated and published on November 1, 2026, after application
closure was confirmed. 70 files verified before publication. Complete 00.062.000
rollback: `/data/ps5-diag/nx2-rollback-062-20261101-eb9d8c35`.
Archive and journal: `artifacts/00.063.000/`. No automatic relaunch; FPS and rendering
remain to be measured. The isolation check now verifies the explicit split-activation
gate already present in the sources.
