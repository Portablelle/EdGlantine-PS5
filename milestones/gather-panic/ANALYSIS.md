# Welcome Tour: PerPx gather and PANIC 2001-0033

## Shader

PS5 00.007.000 capture: native shader at 0x1f986ed200, instruction +0xc0,
words `040a7b63 33800408 041e2f08 100fc200`, rejected at 5.495 s.
Field 76..77 equals 2: PerPx, four signed (x,y) offsets stored in eight bytes
across two registers. Coordinates R4/R5, offsets R8/R9, outputs R10/R11 and R8/R9.
The outputs overlap the offsets.

Translation uses Maxwell TLD4.PTP, first emitting results into R250..R253, then
copying them according to the mask into the two outputs. The frontend reads
signed 8-bit offsets for native programs; legacy Maxwell 6-bit behavior is
unchanged. The native cache salt is incremented. Only 2D PerPx without depth
comparison or half-precision output is added. Other variants remain rejected.

Primary Mesa NAK references, revision b1fe47e94409d81924c8663f58fac97e66ab4527:

- [sm70_encode.rs](https://chromium.googlesource.com/external/gitlab.freedesktop.org/mesa/mesa/+/b1fe47e94409d81924c8663f58fac97e66ab4527/src/nouveau/compiler/nak/sm70_encode.rs): OpTld4, bits76..78=PerPx.
- [nak_nir_lower_tex.c](https://chromium.googlesource.com/external/gitlab.freedesktop.org/mesa/mesa/+/b1fe47e94409d81924c8663f58fac97e66ab4527/src/nouveau/compiler/nak_nir_lower_tex.c): TG4 offset packing and coordinates/src0, offsets/src1 placement.

## PANIC

Capture: SetTerminateResult(0x4201), then Break/PANIC at 20.416 s.
`svc_results.h` defines Kernel/33 as ResultNotImplemented (2001-0033).
The stack leads to main+0xaba0a0: AbortImpl is called on the nonzero result
returned by video-decoder initialization. Dynamic ELF imports in the NSO
identify InitializeH264/Av1/Vp8/Vp9Decoder branches. All 423 WebM files in the
update RomFS are tagged V_VP8.

In the dump's SDK, InitializeVp8Decoder at 0x8a94ebd0 calls helper 0x8a94f294.
At 0x8a94f320..354, this helper forms a TIPC request: header0xd8, 5 raw words,
one copied handle, memory size, codec4, input format and output format. At
0x8a94f3b0 the IPC result is retrieved and returned if nonzero. These addresses
belong to the captured load (sdk base0x8a670000).

The prototype protocol decodes this packet as InitializeByTransferMemory,
command200, codec4. Its admission accepts AV1, H.264 and a VP9 path, never
VP8/codec4, so it returns NotImplemented. This suggested missing VP8 decoding;
that specific attribution is disproved by the direct 00.008 trace below. The
Info capture does not contain the exact IPC parameters of this session; a
targeted error trace is added to confirm the rejected request directly in the
next run.

No fake success is returned and no video is removed. Adding a VP8 backend,
configuration, outputs and decoding tests remains separate work. NSO analysis
is static, following bounded decompression and SHA256 segment checks; no game
code executes on the Mac.

## Validation and installation

PS5 build on the build server passed. Gather tests: 3 cases, 5,541 assertions,
all passed. Shared targeted suite: 395 cases, 1,877,310 assertions, all passed.
The shared 00.008.000 package was installed on October 31, 2026: 70 files verified
by SHA256 in raw SELF transfer mode; the complete previous 00.007.000 version
was retained at `/data/ps5-diag/nx2-rollback-007-20261031`.
Active param.json confirms 00.008.000. No game launch was performed after
installation; console graphics validation remains pending. Game data and saves
were unchanged.

## Direct 00.008 trace: correcting the video diagnosis

The next user launch loads 00.008.000. The 44.9-second capture no longer contains
the texture-gather rejection or ExceptionRaised; this does not yet validate
rendering correctness, with a black image still reported by the user.
At 20.314502 s: command 201, decoder=true, codec=0, input_format=3,
output_format=2, output_mode=1, memory 0x1745b000, result 0x4201.
SetTerminateResult and PANIC follow at 20.317 s. This combination is rejected
by all current admission paths before creating the video backend. It is not
command 200/codec4 from the previously analyzed VP8 helper. VP8 videos in RomFS
therefore do not prove the codec of this request. The meaning of
command201/codec0/input3 in the SDK/protocol must be established before choosing
a backend or changing admission.

Frames continue to be queued after the PANIC; presentation counters do not prove
game progress. Private capture: `backups/nx2-008-live-20261031/` in the PS5
workspace. No console changes.
