// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
namespace Settings{enum class RendererBackend{Vulkan};inline bool safe=false,high=true;inline bool IsDMALevelDefault(){return false;}inline bool IsDMALevelSafe(){return safe;}inline bool IsGPULevelHigh(){return high;}struct Backend{RendererBackend GetValue(){return RendererBackend::Vulkan;}};inline struct{Backend renderer_backend;}values;}
