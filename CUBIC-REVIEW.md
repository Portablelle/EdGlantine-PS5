# Publication review — November 1, 2026

The complete publication diff was reviewed against the previous GitHub main tree,
using a temporary review commit with the exact publication tree. This review-only
commit is not part of the anonymized history being published.

The initial four findings were addressed:

- Both Vulkan profiling query pools are reset after the scheduler worker joins and
  the device becomes idle, before the device is destroyed.
- Remote build and packaging scripts create the destination directory before rsync.
- Source patch and Vulkan generator fingerprints match the committed files.
- Session commands and diagnostic deadlines run in an explicit session control
  loop with a session-owned `RuntimeControl` and explicit nonce/poll state. The
  controller invokes session-supplied actions; profiling only exposes diagnostic
  operations. GPU-utilization sampling no longer consumes commands or changes
  runtime state.

Focused tests on the build server passed under ASan/UBSan: profiling-ring behavior,
pool release across two device lifetimes, failure-state reset, command consumption,
deadline expiry without HUD sampling, and fresh control state in a new session.
Tests: `eden/tests-nx2/native-gpu-profile-lifetime.cpp` and
`eden/tests-nx2/check-runtime-control.py`.

Further review findings were addressed as well:

- Texture lowering reserves R246–R254 across the whole program, so FP16 gather
  conversion cannot overwrite guest values live across the instruction. Register
  shadowing preserves those values; the non-shadowing path rejects unsafe programs.
  The native translator salt is incremented to invalidate earlier translations.
- A session-owned `ProfilingSession` holds the report budget and retires diagnostic
  deadlines and enable flags on destruction, including early session termination.

Focused ASan/UBSan regressions passed for live R246/R247 values across a captured
FP16 gather and for ending a session during an active profiling window. The shader
check uses production lowering with a small execution model for register semantics;
texture pixels and PS5 rendering are not validated by that model.
See `eden/tests-nx2/check-texture-scratch.py` and the runtime-control test above.

Additional publication checks addressed:

- All Vulkan builds retain conservative gathered-buffer reads until invalidation
  is ordered after producing draws, including overlapping pending outputs.
- Failure to open/write the observer log or create its optional thread no longer
  prevents split backend startup. Partial observer state is cleaned up independently.
- The temporary .018 MME capture/write-tracing hooks are retired. The interpreter
  exception for method 0x18f remains an explicit native execution policy, independent
  of file capture and ordinary JIT/memoization configuration.
- Deployment metadata now reflects the recorded .064 installation, retained .063
  rollback and user-confirmed 21 FPS result.

The focused edge-case harness exercises actual split startup with observer open,
write and thread-creation failures, then backend execution/shutdown/recovery. It
also tests the production gathered-cache mutation methods with and without the
PS5 build define: `eden/tests-nx2/check-publication-edge-cases.py`.

The final review also prompted submission-completion guards for timestamp reads
(including tickets spanning command buffers), atomic claiming of runtime requests,
nonblocking observer opens restricted to regular files, session-owned initial
profiling deadlines, and a dedicated native draw HLE module owning SDK validation
and draw-state restoration. Targeted regressions cover stale query availability,
pending-output invalidation, FIFO destinations, and initial deadline expiry.

Draw and resource memo tables now share one implementation with explicit hash
policies and statistics sinks. The observer regression injects ENOSPC on the first
write to an accepted regular file, independently of the nonregular-file checks.

Profiling session orchestration is now a separate translation unit and reports
through subsystem-owned functions. Resolved shadow registers use a private direct
application path, without a public observation-bypass flag. The indirect regression
invokes the production HLE function against a recording backend for 4,096 randomized
interpreter comparisons, checking command offsets, replacement attributes and state
restoration. It does not validate Vulkan driver execution or pixels. Gathered-view
reuse metadata now clearly labels its earlier measurements as historical.

These source fixes postdate the PS5-tested .064 package and have not been installed
on the console. The 21 FPS result applies to that previously installed package.

---

# Initial snapshot review

`cubic review --commit HEAD --json` reviewed the initial source snapshot locally.
The first review returned six findings (not an authentication error). Repository
settings/context were unavailable because the new remote was still empty; the
review itself returned concrete source findings.

Four applicable findings are addressed in the follow-up:

- Save archives must contain a file that will actually be extracted. JKSV-only
  metadata is excluded both with and without a title wrapper before any folder
  is created or an active save can be replaced.
- HTTP follows redirects only for bodyless GET/HEAD reads. Uploads and modifying
  methods return redirects to the caller instead of forwarding their body.
  Configure the final upload URL when a reverse proxy would redirect it.
- Device translation-cache generations are unique across manager lifetimes and
  mutations, including address reuse on a surviving worker thread.
- FFmpeg's signalled color matrix is preserved. The existing RGBA admission
  rejects unsupported matrices instead of silently converting them as BT.709;
  unspecified input retains the previous BT.709 default.

Two findings do not require a change in this prototype's execution path:

- `self_update_helper/updater.cpp` is an inherited, unused helper. The prototype's
  `update_notice.cpp` is a stub (`Begin`/`Apply` return false), packaging excludes
  the helper and no prototype build compiles it. The transactional-updater concern
  remains relevant to the upstream implementation, not this installed artifact.
- Extracting investigative draw policy is an architectural suggestion without a
  demonstrated behavior defect. Existing diagnostic helpers require explicit
  `EDEN_NATIVE_*` environment switches and are disabled in the ordinary session.
  No broad renderer refactor is included in this incremental compatibility step.

The corrections receive a local Cubic review before the first push. Native build
and installation are recorded in TEST-REPORT.md; no full desktop suite is rerun.
