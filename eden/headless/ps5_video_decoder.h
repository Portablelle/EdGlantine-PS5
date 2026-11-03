// SPDX-License-Identifier: GPL-3.0-only
// Adapted from sainsaji/EVO-PLAYER-PS5 a54dcf516e9cfda4c26d78733bf5ccb8c10e7e0b (GPL-3.0)
#pragma once
#include <memory>
namespace FFmpeg { class HardwareVideoDecoder; }

namespace Eden {
std::unique_ptr<FFmpeg::HardwareVideoDecoder> CreatePs5VideoDecoder();
void RegisterPs5VideoDecoder();
} // namespace Eden
