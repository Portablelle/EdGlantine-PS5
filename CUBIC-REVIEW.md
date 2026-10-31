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
