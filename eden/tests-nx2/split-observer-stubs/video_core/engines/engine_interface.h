// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <array>
#include <span>
#include <vector>
#include <stdexcept>
#include "common/common_types.h"
#include "core/core.h"
namespace Tegra::Engines{struct EngineInterface{std::array<bool,65536>execution_mask{};std::vector<std::pair<u32,u32>>method_sink;u64 current_dma_segment{},calls{},sum{},multi_sum{};std::vector<u64>segments;std::vector<u32>pending;
 EngineInterface(){execution_mask.fill(true);}
 void ConsumeSink(Core::System&){for(auto [m,v]:method_sink){++calls;sum+=v;}method_sink.clear();}
 void CallMethod(Core::System&,u32 m,u32 a,bool){if(a==0xdeadbeef)throw std::runtime_error("injected backend failure");++calls;sum+=a;}
 // As production's default: the sink, then each write (method | value << 32) one by one.
 void WriteStateRegisters(Core::System& s,std::span<const u64,4>,std::span<const u64> writes){ConsumeSink(s);for(u64 w:writes)CallMethod(s,u32(w),u32(w>>32),true);}
 void CallMultiMethod(Core::System&,u32,const u32* words,u32 n,u32 left){segments.push_back(current_dma_segment);pending.push_back(left);for(u32 i=0;i<n;++i)multi_sum+=words[i];}
};}
