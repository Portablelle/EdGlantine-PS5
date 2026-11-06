# EdGlantine-PS5

**An experimental NS2 emulator for jailbroken PS5 consoles.**

EdGlantine-PS5 runs the Eden NX2 engine natively on the PS5. It is built on
[ProsperoEden](https://github.com/blackbearreloaded/ProsperoEden), the PS5 port of
Eden, and brings in work from the Eglantine and Eden-NS2 forks.

Pokopia is playable, and other NS2 games reach gameplay, but this is still a
prototype. Expect low frame rates, rendering glitches and crashes. Nothing here
is a stable compatibility claim.

> **Contributors welcome.** Profiling, GPU memory, rendering correctness and
> console testing are where help matters most. See [Contributing](#contributing).

---

## Contents

- [Current state](#current-state)
- [What's new](#whats-new)
- [Features](#features)
- [Installing and game files](#installing-and-game-files)
- [Known issues and limits](#known-issues-and-limits)
- [Building](#building)
- [Repository layout](#repository-layout)
- [Contributing](#contributing)
- [Credits](#credits)
- [Further reading](#further-reading)

---

## Current state

**Installed build: 00.066.000** (title `PPSA99862`, shown as **EdGlantine PS5**),
the release of `main` with NUP support and the fixes up to
[#34](https://github.com/Portablelle/EdGlantine-PS5/pull/34).
The `.0xx` part of `00.066.0xx` numbers test builds. Only the main version is a
release.

### Games

| Game | State | Notes |
|------|-------|-------|
| **Pokopia** | **Playable**, 45–50 FPS | Starts correctly, and the sky is no longer black. From some camera angles, a few assets flicker and can swap places. The frame rate drops to about 30 depending on what is in view. See the [Pokopia investigation](eden/docs/POKOPIA_RENDERING_INVESTIGATION.md). |
| **Donkey Kong Bananza** | Not playable, 5–20 FPS | No rendering problem seen any more, but the frame rate is too low to play. See the [Bananza investigation](eden/docs/BANANZA_STARTUP_INVESTIGATION.md). |
| **Welcome Tour** | Not playable, about 10 FPS | Some assets seem to be missing and show black. |
| **Mario Kart World** | Stops at the first load | Runs out of graphics memory during the first load. History in [issue #20](https://github.com/Portablelle/EdGlantine-PS5/issues/20). |

These are the latest results reported by the player (November 5, 2026), not
repeated benchmarks.
Scenes and settings differ between runs. Exact numbers and conditions are in
[TEST-REPORT.md](TEST-REPORT.md).

### Where the time goes

A 20-second capture on .063 recorded **8.65 s of CPU draw preparation**.
That includes 3.73 s of descriptor work and 2.81 s of resource reads. These
counters are nested, so they do not add up. GPU command buffers covered 5.77 s.
CPU draw preparation is the main known bottleneck.

---

## What's new

Recent work, newest first. Each item links to its pull request.

### Lichii shader fixes ([#44](https://github.com/Portablelle/EdGlantine-PS5/pull/44))

Four shader recompiler changes ported from Lichii into the core. None has been
tried on a console yet.

- **Atomic loops on AMD.** When several shader threads update the same word
  with an emulated atomic (float add, increment, small stores), each retry now
  starts from the value the last exchange returned. Reloading the word could
  keep returning a stale value on AMD, so the loop never ended and the GPU was
  lost (OoT's first autosave, seen on a desktop AMD card).
- **Depth-compare textures.** A depth-compare texture always gets a float
  image, even when its descriptor looks like an integer format. RADV rejected
  the shader otherwise (a crash in OoT's opening house).
- **More shaders lowered.** Two more instruction forms (`SHF` with a register
  shift and `LOP3` with a constant buffer or uniform operand) can use registers
  that the lowering keeps for itself, instead of rejecting the shader.
- **No silent register mix-ups.** The gradients of `TXD` and the data of the
  global `ATOMG` and `RED` atomics are now checked like other operands. Before,
  a register in the range the lowering keeps for itself was read from the
  emulated uniform state instead of the guest value.

### Lichii fixes, third batch ([#45](https://github.com/Portablelle/EdGlantine-PS5/pull/45))

Two more changes ported from Lichii into the core, each adapted to it. None
has been tried on a console yet. The terrain-layer clear and the cheaper
storage buffer bindings from this batch are in
[#47](https://github.com/Portablelle/EdGlantine-PS5/pull/47) instead.

- **OoT white flashes.** Before a macro reads occlusion reports from memory, it
  now waits for the reports whose results the host GPU has not delivered yet.
  Before, it read the old counts, and leaves and terrain flashed white for a
  few frames whenever the camera moved. The wait is capped at 200 ms.
- **Fewer copies in memory tracking.** Page runs that are already sorted are
  merged where they lie and counted without two extra copies.

### Lichii fixes, second batch ([#43](https://github.com/Portablelle/EdGlantine-PS5/pull/43))

Four more changes ported from Lichii into the core. None has been tried on a
console yet.

- **Fewer cache invalidations.** When the GPU writes memory, for example
  constant buffer data on almost every draw, the texture, query and shader
  caches are only asked to invalidate it if they ever registered something on
  those pages. This saves CPU time in draw preparation.
- **Cheaper draw bindings.** An index buffer that is already bound is not bound
  again, and a large buffer that is used again is not re-marked page by page.
- **NS2 game cards.** An XCI is checked for NS2 metadata before the guest
  clock and memory layout are chosen, as NSP and NUP files already were.
- **Swapchain recreation.** The device is idle before an old swapchain is
  destroyed. A suboptimal image is still presented, and an out-of-date
  swapchain is recreated before anything is drawn to it.

### Lichii GPU and shader fixes ([#41](https://github.com/Portablelle/EdGlantine-PS5/pull/41))

Seven fixes ported from Lichii into the core. None has been tried on a console
yet.

- **Black scenes on AMD.** Shaders that end some pixels early inside nested
  branches no longer write their colours before those pixels are discarded.
- **Movie crash.** Two threads can no longer read the list of CPU-written memory
  at the same time.
- **Crash after a failed pipeline.** Draws that follow a graphics pipeline that
  failed to build are dropped instead of reaching the driver.
- **Global `ATOM.CAS`.** Shaders that use a 32-bit compare-and-swap on a raw
  address now compile.
- **Depth-stencil copies.** Reinterpreting a depth-stencil image copies the
  depth aspect only, with the right image layout.
- **OoT sky and culling.** Multiplies by 0 and 1 are simplified, so the shader
  sees the real buffer pointer. Native 64 KiB uniform banks are uploaded again
  once per frame, so tables next to the code don't go stale.

### Fixes from viejunerd's build for Mario Kart World and the GPU thread

Taken from [viejunerd's EglantinePS5 build](https://github.com/viejunerd/Eglantine-PS5-)
(`tools/eglantine-patches`). None of them has been tried on a console yet.

- **Compact memory for Mario Kart World.** It is on for this game unless the
  game's own settings turn it off. Written memory that is mostly zeroes is kept
  in 16 KiB pages.
- **Smaller kernel tables.** Each memory manager sizes its page reference counts
  to its own region, not to all of the console's memory.
- **Smaller GPU queue.** Command lists keep 32 entries in place instead of 512,
  so the GPU thread's queue takes about 2 MiB instead of about 25 MiB.
- **No more abort on a 4 GiB vertex stream.** It is clamped and logged, which
  is what aborted Mario Kart World as it booted in viejunerd's build.
- **Out-of-range syncpoints are dropped** and logged once, instead of crashing.
- **Controller callbacks after the applet resource exists.** A motion sample
  during boot could crash the app.
- **No global Vulkan pipeline cache.** It hung NS2 games at 98% on every launch
  after the first in viejunerd's build. Per-game caches are kept.
- **OoT's movies play.** The game asks for its AV1 decoder with NV12 output,
  which was refused, and the game stopped on its menu. AV1 now goes through
  dav1d, built into FFmpeg for the PS5. It decodes several frames at once,
  where libgav1 fell behind on the 1080p menu movie.
  `EDEN_NX2_AV1_LIBGAV1=1` keeps libgav1.
- **Bananza's VP9 movies on the PS5 decoder.** Its VP9 movies (up to 4K) were
  decoded by FFmpeg on the CPU. They now go to the PS5's hardware decoder, and
  any stream it refuses or fails on goes back to FFmpeg at the next keyframe.
  `EDEN_NX2_VP9_HW=0` keeps FFmpeg. Not yet tried on a console.
- **The GPU thread wakes on new work.** While channels wait on a semaphore, it
  used to sleep a fixed 1 ms. It now wakes as soon as work arrives, and checks
  the semaphores every 0.25 ms.

### NUP packages ([#28](https://github.com/Portablelle/EdGlantine-PS5/pull/28))

`.nup` files can go in `roms/` next to NSP and XCI. A NUP is Eglantine's
single-file package: a game with its updates and DLC. The Library reads its
name, cover, update and DLC. When the game starts, the update is applied and the
DLC is offered to it. The reader comes from Eglantine. The DLC support comes from
[viejunerd's EglantinePS5 build](https://github.com/viejunerd/Eglantine-PS5-).

### Pokopia shaders and memory breakdown ([#27](https://github.com/Portablelle/EdGlantine-PS5/pull/27))

- **Two Pokopia shaders run again.** The native translator rejected them, so
  their dispatches were skipped. Wide local spills (`LDL`/`STL` of 64 and 128
  bits) and one-term predicate LUTs (`UPLOP3`) are now translated.
- **Refresh journal.** Every 5 s, the logs list the images refreshed most often.
  In Pokopia this points to a triple-buffered texture the game rewrites from the
  CPU, a likely cause of the sprites that swap places.
- **Descriptor buffers can be turned off.** Create
  `/data/eden-nx2/descriptor-buffer-off.txt` to turn them off, for A/B tests.
- **Memory breakdown.** Every 5 s, the logs show what fills the graphics pool:
  allocated images, staging buffers and per-heap Vulkan statistics.

### Graphics memory on the PS5 ([issue #20](https://github.com/Portablelle/EdGlantine-PS5/issues/20))

Mario Kart World runs out of the PS5's shared graphics memory while it loads.
Four changes so far:

- **Crash reports say so.** A guest memory exhaustion now appears in the crash
  report and the logs ([#21](https://github.com/Portablelle/EdGlantine-PS5/pull/21)).
- **Staging buffer pool.** Upload and download buffers are sized, reused and
  released as they are on PS5 builds of Eglantine
  ([#24](https://github.com/Portablelle/EdGlantine-PS5/pull/24)).
- **ASTC one layer at a time.** Large ASTC textures are decoded layer by layer,
  and idle staging buffers are trimmed
  ([#25](https://github.com/Portablelle/EdGlantine-PS5/pull/25)).
- **Earlier collection, chunked uploads.** Converted textures upload in chunks of
  at most 32 MiB. The texture cache starts collecting earlier. A readback that the
  pool cannot afford is skipped instead of ending the session
  ([#26](https://github.com/Portablelle/EdGlantine-PS5/pull/26)).

The game gets further with each step, but it still does not reach its title
screen. About 3.4 GiB of graphics memory that is not images remains to be
explained.

### Hardware video decoding ([#22](https://github.com/Portablelle/EdGlantine-PS5/pull/22), [#23](https://github.com/Portablelle/EdGlantine-PS5/pull/23))

- **PS5 hardware decoder.** H.264 and VP9 videos can be decoded by the PS5's own
  decoder (`libSceVideodec2`). Any stream it cannot take goes to FFmpeg as before.
- **Turning it off.** Set `EDEN_PS5_HW_VIDEODEC=0` to turn the hardware decoder off.
- **Faster conversion.** Turning video frames from YUV into RGBA now runs on
  several threads.
- **Not yet confirmed on a console.** Whether real game videos use the hardware
  path has not been checked.

### Fixes ported from upstream ([#2](https://github.com/Portablelle/EdGlantine-PS5/pull/2)–[#19](https://github.com/Portablelle/EdGlantine-PS5/pull/19))

About twenty small fixes ported one by one, each with its own pull request, for
example:

- NS2 detection inside NSP files.
- Six-axis sensor ranges and Mii arguments.
- Audio-out and video-decoder lifetimes at shutdown.
- Shader-removal and descriptor-bitmap performance.
- Mixed-case RomFS folders in dumps.

---

## Features

Everything from ProsperoEden, plus:

- **NS2 games** on the Eden NX2 engine, with native shaders, GPU
  descriptors, texture streaming and NX2 services from Eden-NS2.
- **Six guest CPU cores** pinned to their own physical cores, with the GPU thread
  on a separate one, when the console's topology allows it.
- **Game formats:** NSP, XCI, NUP, and decrypted folder dumps (`exefs/` and
  `romfs/`).
- **Updates and DLC:** from `updates/`, from a game's own folder in `roms/`, or
  packed inside a NUP.
- **Vulkan through RADV** (Mihawk's PS5 Mesa), with ProsperoEden's launcher,
  Library, settings per game, profiles and save transfer.
- **Macro JIT** for graphics and compute (NX2 MME). It runs in PS5 direct
  memory with separate writable and executable views.
- **Hardware H.264/VP9 decoding**, with FFmpeg fallback.

---

## Installing and game files

The app installs as its own title, **`PPSA99862`**, separate from ProsperoEden or
any other build. Its data, saves, settings and caches live in `/data/eden-nx2`.

Put your own **keys, firmware and games** in the game files folder; see
ProsperoEden's [install guide](eden/docs/INSTALL.md). Games go in `roms/`:

```
roms/
├── Some Game.nsp                 # a game file
├── Another Game.nup              # a NUP: game + update + DLC in one file
├── Third Game/                   # a game folder, with its update and DLC beside it
│   ├── Third Game.xci
│   └── Third Game [Update].nsp
└── Dumped Game/                  # a decrypted dump
    ├── exefs/main                # with main.npdm and the other ExeFS modules
    └── romfs/
```

- **Folder dumps** do not need container keys. NSP, XCI and NUP files still need
  the usual setup.
- **Launching:** the controller menu opens at startup. Choose a game in the
  Library and press Cross.
- **Self-update** is disabled. New builds are installed by hand, with the
  previous files kept as a rollback.

---

## Known issues and limits

- **Low frame rates.** Only Pokopia is playable. Bananza (5–20 FPS) and Welcome
  Tour (about 10 FPS) are too slow, and CPU draw preparation is the main known cost.
- **Rendering.** In Pokopia, some assets flicker and swap places from certain
  camera angles. In Welcome Tour, some assets show black.
- **Graphics memory.** Large games can run out of the PS5's shared graphics pool
  (issue #20).
- **GPU thread splitting** is available but off at startup. Turning it on has
  frozen games.
- **Sparse texture residency** is off by default (`EDEN_NX2_SPARSE_LAYERS=1` opts
  in). It does not yet save any memory.
- **Partly simulated services.** Some NX2 services are simulated, and graphics
  stages the engine does not implement are unavailable.
- **Builds are not game validation.** A passing build or host test does not
  validate a game; only console runs do.
- **HUD CPU columns.** The inherited HUD shows four CPU columns, while the engine
  uses six cores.

---

## Building

All configuration and compilation, shaders and C++ tests included, runs on a
**remote Linux build server**. Nothing is built on the Mac.

**1. Point the scripts at your server.** Use a local file that Git ignores:

```sh
mkdir -p .local
cat > .local/remote-build.env <<'CONFIG'
EDGLANTINE_BUILD_HOST=build-server
EDGLANTINE_REMOTE_ROOT=/tmp/edglantine-ps5-build
CONFIG
```

`build-server` is an example SSH alias.

**2. Build.** `build-remote.sh` syncs `eden/` to the server and builds inside the
container. The remote directory must already hold the prepared dependencies; it
is mounted as `/work`.

```sh
bash build-remote.sh
```

**3. Package.** `package-remote.sh` makes the title folder, checks its isolation
and copies the archive into `artifacts/`. Neither script contacts the console,
and `make install` is disabled.

```sh
bash package-remote.sh
```

**How the core is prepared.**

- **Pinned sources.** The Eden core is pinned to `67bada77`. Its other
  dependencies are pinned in `eden/tools/deps.json`.
- **Patch layers.** `eden/tools/eden-patches/*.diff` apply on top, in order. Any
  change to a layer re-extracts the core and reapplies the whole series.
- **New changes.** A core change goes into a new layer, not an edit of the
  unpacked tree.

---

## Repository layout

| Path | What it holds |
|------|---------------|
| `eden/` | The PS5 port: frontend and launcher (`headless/`), build tools (`tools/`), core patch layers (`tools/eden-patches/`), tests (`tests-nx2/`) and docs (`docs/`). |
| `milestones/` | Notes, analyses and patches for each integration batch. |
| `experiments/` | Investigations kept apart from the build, such as sparse textures. |
| `prototype.json` | Exact revisions, pinned hashes and integration records. |
| `TEST-REPORT.md` | Every build's tests, console results and measurements, newest first. |
| `HISTORY.md` | Earlier milestone notes (00.003 to 00.040). |

Packages, dumps, games, keys, SDKs and reference checkouts stay local and are
never committed.

---

## Contributing

Code, measurements, debugging findings and console tests all help. Useful areas:

- **CPU draw preparation:** descriptor setup, shader-resource lookup and SSBO
  binding.
- **Graphics memory:** where the memory that is not images goes (issue #20), and
  staging and readback sizes.
- **GPU transfers and synchronization:** fewer redundant copies and readbacks,
  while keeping dirty-range tracking, ownership and ordering.
- **GPU split stability:** why progress stops once splitting is on.
- **Rendering:** small reproductions of texture and shader bugs, with tests on the
  production code path.

**Reporting a problem.** Open an issue with:

- the build version, settings, game and scene;
- the steps to reproduce it;
- the FPS or frame times you measured;
- logs, cleaned of personal data.

For a performance change, compare the same scene and settings before and after.
Never attach games, keys, proprietary SDKs or personal data.

**Pull requests.**

- Explain the problem, the change and how you checked it.
- Keep each one focused, link the upstream commit you adapted, and keep its
  license notices.
- Run the tests for the code you touched.
- Say plainly what was not tried on a real PS5: a host test passing is not a
  console result.

---

## Credits

EdGlantine-PS5 stands on the work of these projects and their contributors:

- [**ProsperoEden**](https://github.com/blackbearreloaded/ProsperoEden): the PS5 port, native app, launcher, build system and platform work this project starts from.
- [**Eden NX2**](https://git.eden-emu.dev/Takoroka/eden-nx2): the NX2 engine behind the first prototype.
- [**Eden-NS2**](https://github.com/0x2593/Eden-NS2): native shaders, GPU descriptors and buffers, texture streaming and NX2 services.
- [**Eglantine (Djihads80)**](https://github.com/Djihads80/Eglantine): GPU page tracking, ASTC layer uploads, cache validation, shader fixes, sparse texture research and the NUP format.
- [**Eglantine (zortos293)**](https://github.com/zortos293/Eglantine): partial-page batching, memory-owner tracking and texture stride fixes.
- [**EglantinePS5 (heydemoura)**](https://github.com/heydemoura/EglantinePS5): staging buffer sizing and reuse, service-command reporting and fragmented heap commitment.
- [**EglantinePS5 NUP build (viejunerd)**](https://github.com/viejunerd/Eglantine-PS5-): NUP DLC through the content provider.
- [**EVO-PLAYER-PS5 (sainsaji)**](https://github.com/sainsaji/EVO-PLAYER-PS5): the `libSceVideodec2` sequence used by the hardware video decoder.
- **Mihawk's** [PS5 Mesa](https://github.com/mihawk-99/PS5_Mesa) and [PS5 Vulkan](https://github.com/mihawk-99/PS5_Vulkan): the RADV driver the Vulkan renderer runs on.

Exact revisions and how each piece was adapted are in `prototype.json` and the
milestone notes. Original copyright notices and third-party licenses are kept in
the source tree. These credits do not imply endorsement by any upstream project.

---

## Further reading

- [TEST-REPORT.md](TEST-REPORT.md): build-by-build tests and console results.
- [HISTORY.md](HISTORY.md): earlier milestones, from the MME port to the EglantinePS5 adaptations.
- [Pokopia rendering investigation](eden/docs/POKOPIA_RENDERING_INVESTIGATION.md): read it before trying another rendering experiment, so as not to repeat a negative one.
- [Bananza startup investigation](eden/docs/BANANZA_STARTUP_INVESTIGATION.md): file-open exhaustion, guest null accesses and the JIT startup crash.
- [Upstream performance adaptations](eden/docs/UPSTREAM_PERFORMANCE_ADAPTATIONS.md): what was taken from nxnative and Eden nightly, and why.
- [ProsperoEden docs](eden/docs/): install, settings, saves, mods, multiplayer and themes.
