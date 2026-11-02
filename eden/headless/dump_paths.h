// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <string_view>
namespace Eden::DumpPaths {
// Exactly one visible game folder followed by the fixed ExeFS entry.
inline bool ValidEntry(std::string_view path) {
    const auto slash=path.find('/');
    if(slash==std::string_view::npos || slash==0 || slash>255 || path.front()=='.' ||
       path.substr(slash)!="/exefs/main") return false;
    for(unsigned char c:path) if(c<32 || c==127 || c=='\\') return false;
    return true;
}
} // namespace Eden::DumpPaths
