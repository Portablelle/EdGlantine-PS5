// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <atomic>
#include <cstdint>
namespace Vulkan {
class Device;
namespace vk { class CommandBuffer; }
namespace NativeGpuProfile {
inline std::atomic<bool> enabled{false};
inline std::atomic<std::uint64_t> epoch{1};
struct Label { unsigned kind{}; std::uint64_t first{}, second{}; unsigned width{}, height{}, stride{}; };
struct Ticket { int query{-1}; };
void BeginBuffer(const Device&, vk::CommandBuffer);
void EndBuffer();
void Collect(const Device&);
void Reset();
void Begin(vk::CommandBuffer, Ticket&, Label);
void End(vk::CommandBuffer, const Ticket&);
}
}
