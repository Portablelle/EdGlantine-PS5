// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

namespace Eden::Performance {
// One owner per running session. Destruction retires all diagnostic enable flags
// even when the session ends before a requested capture's deadline.
class ProfilingSession {
public:
    ProfilingSession();
    ~ProfilingSession();
    ProfilingSession(const ProfilingSession&) = delete;
    ProfilingSession& operator=(const ProfilingSession&) = delete;
    void Restart();
    void Tick();
private:
    void Stop();
    long long initial_deadline{};
    long long next_report{};
    unsigned reports{};
};
} // namespace Eden::Performance
