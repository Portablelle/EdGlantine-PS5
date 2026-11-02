// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <filesystem>
namespace Eden::DumpMetadata {
inline bool IsEntry(const std::filesystem::path& entry) {
    return entry.filename()=="main" && entry.parent_path().filename()=="exefs";
}
// Implemented in metadata_bridge.cpp through the engine's canonical loader/parser.
std::uint64_t ProgramId(const std::filesystem::path& entry);
bool Ready(const std::filesystem::path& entry);
} // namespace Eden::DumpMetadata
