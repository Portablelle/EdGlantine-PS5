# Welcome Tour H.264 transfer-memory initialization

The .008 live request is command 201, codec 0, input format 3, output format 2,
output mode 1, transfer memory 0x1745b000. It was rejected before backend creation,
followed by guest result 0x4201 and PANIC at 20.317 seconds.

Static analysis of the user's SDK (bounded NSO decompression with SHA256 checks,
no guest execution) resolves InitializeH264Decoder(Pv, size, ...) to SDK offset
0x2dc810. It calls helper 0x2dcfb4. At offsets 0x2dd040..0x2dd074 that helper
constructs TIPC header 0xd9 / 0x80000006, copied transfer-memory handle, memory
size, codec 0, the unchanged input-format argument (w7 saved in w25), output
format and mode. The observed packet is therefore H.264, not the earlier
hypothesized VP8 path. Input format 3 does not uniquely identify AV1.

The existing H.264 backend already handles parameter-set extradata and Annex B
or four-byte length-prefixed input. The change admits input format 3 only for
H.264 command 201; existing format 1 admission for commands 200/201 is retained.
Decoder kind, output formats, mode, transfer-memory ownership/size and real
FFmpeg context creation remain checked. Unknown combinations still fail.
Initialization result logging is now Info, so the next console attempt can
show whether it passes this gate. Full playback is not established by admission.

Focused regression: reconstructed observed packet, legacy format 1, wrong
commands/codecs/input/output formats/modes. The new test body was compiled alone
on build-server against the prepared production header with ASan/UBSan: 20 assertions
passed. No full desktop engine rebuild was requested or run for this change.

PS5 compilation, built-in native checks and package checks passed. Installed as
00.009.000 on 2026-10-31, with 70 raw SELF file hashes verified before publication.
Full .008 rollback retained at `/data/ps5-diag/nx2-rollback-008-20261031`.
No game launch performed after installation; user testing remains necessary.

Console follow-up: user confirms Welcome Tour launches. The .009 log records
initialization result 0 at 20.242 s and no PANIC through the captured 46 s.
Presentation drops from ~60 FPS to 6.9–8.5 FPS around video startup. This timing
suggests investigating the software H.264 output path (CPU YUV conversion,
swizzle, guest-memory write), but no per-stage measurements identify the dominant
cost yet. CPUID topology readiness is 0; this indicates fallback placement, not
proof that all threads run on one core. Settings unchanged.
