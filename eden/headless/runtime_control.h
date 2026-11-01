// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <cstdio>
#include <string>
#include <utility>

namespace Eden {
// Owned by one session control thread. No renderer or profiling implementation
// dependencies: the session supplies the actions to execute for each command.
class RuntimeControl {
public:
    RuntimeControl(std::string split_path, std::string profile_path)
        : split_path{std::move(split_path)}, profile_path{std::move(profile_path)} {}

    template <class EnableSplit, class RestartProfile>
    void Poll(long long now, EnableSplit&& enable_split, RestartProfile&& restart_profile) {
        if (now < next_check) return;
        next_check = now + 1'000'000'000LL;
        if (Consume(split_path, last_split)) {
            enable_split();
            std::fprintf(stderr, "NX2_SPLIT_ENABLE_REQUEST mono_ns=%lld\n", now);
        }
        if (Consume(profile_path, last_profile)) restart_profile();
    }

private:
    static bool Consume(const std::string& path, std::string& last_nonce) {
        auto* file = std::fopen(path.c_str(), "rb");
        if (!file) return false;
        char nonce[64];
        const auto size = std::fread(nonce, 1, sizeof(nonce), file);
        const bool failed = std::ferror(file) != 0;
        std::fclose(file);
        if (failed) return false;
        std::remove(path.c_str());
        const std::string request(nonce, size);
        if (request.empty() || request == last_nonce) return false;
        last_nonce = request;
        return true;
    }

    std::string split_path, profile_path;
    std::string last_split, last_profile;
    long long next_check{};
};
} // namespace Eden
