# Welcome Tour menu / next-screen rendering

.011 video optimization measured on PS5: 7.037 → 14.957 output FPS over matching
frames 90..570, conversion 96.176 → 21.148 ms. Menu reaches 59.94 FPS, but user
reports regular black flashes and severe black regions/misplaced sprites after
confirmation. Overall rendering is not validated by this FPS count.

At 118.297 s, the .011 log starts rejecting native texture shaders:

- `0a0d7b60 b1012400 041e41ff 00114400`: scalar array-2D depth comparison,
  source A R10/R11, source B R0/R1, output R13, descriptor bank 4/offset 0x490.
  A preceding texture instruction uses a different bank. Lowering rejects it
  instead of reading this instruction's descriptor from bank 4.
- `00007361 38000027 041e0726 002f4400`: bindless scalar 2D RGB sample,
  XY R0/R1, handle R39, outputs R0/R1/R38. The lowering only admitted one channel.
  A second observed form has XY R16/R17 and handle R35, outputs R16/R17/R36.

Both errors reproduce with production LowerToMaxwell on build-server before changes.
They prevent whole draws from executing. This establishes missing passes, not
that every reported artifact or earlier menu flash has this cause.

.012 emits an explicit bindless descriptor load for the mixed-bank array depth
sample, retaining layer/XY/depth and predication. Metadata uses scratch R248/R249;
R254 cannot be used for the last metadata operand because the Maxwell visitor's
post-increment would overflow into RZ. Split bindless 2D outputs sample into
scratch before copying selected channels, preserving aliases with coordinates
or the handle. Unknown modes remain rejected. Native translator salt increases
from 0x4f554e4345a00002 to ...00003 so old pipeline entries are not reused.

Host validation: only the two focused semantic tests, 82 assertions PASS, reusing
existing Maxwell compiler libraries on build-server. Both descriptor banks, implicit/
zero LOD, channel masks, source/output aliases and the depth reference are checked.
No full desktop suite and no repeated generic native checks for this iteration,
per user preference. Native incremental build and installation completed. Console .012 follow-up: user reports fewer but persistent defects. The two .011
rejection forms no longer appear in this capture. New errors are bindless array
depth sampling (`0c0d7361 a800001e 041e41ff`), mixed-bank explicit-LOD sampling
(`18187b60 31018820 059e0f20`) and FP16 texel fetch (`04047b66 33c0440e 059e8705`,
`02017b66 33c04401 059e8705`). Overall graphics acceptance remains incomplete.
