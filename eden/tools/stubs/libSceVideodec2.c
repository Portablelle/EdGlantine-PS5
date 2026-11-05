/* SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Link-time facade of the PS5 libSceVideodec2 module, which the Payload SDK has no import
 * library for: the functions the hardware video decoder calls (headless/ps5_video_decoder.cpp,
 * declared in headless/ps5_videodec2_abi.h). The native packaging tool turns these symbols into
 * imports of the firmware module; nothing here is linked into the application or ever runs.
 * The same list as EVO-PLAYER-PS5's tools/native-app/stubs/prx/libSceVideodec2.syms
 * (a54dcf516e9cfda4c26d78733bf5ccb8c10e7e0b).
 */
int sceVideodec2QueryComputeMemoryInfo(void) { return -1; }
int sceVideodec2AllocateComputeQueue(void) { return -1; }
int sceVideodec2ReleaseComputeQueue(void) { return -1; }
int sceVideodec2QueryDecoderMemoryInfo(void) { return -1; }
int sceVideodec2CreateDecoder(void) { return -1; }
int sceVideodec2DeleteDecoder(void) { return -1; }
int sceVideodec2MapDirectMemory(void) { return -1; }
int sceVideodec2Reset(void) { return -1; }
int sceVideodec2Decode(void) { return -1; }
int sceVideodec2Flush(void) { return -1; }
