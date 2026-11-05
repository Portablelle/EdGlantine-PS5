// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// What each guest thread of the running game is doing, for a game that stops without an error:
// one EDEN_THREADS line per dump and one EDEN_THREAD line per thread with its state, why it
// waits, the address it waits on and where its code stopped (PC, LR, SP). For an IPC wait, the
// first words of its message buffer (TLS) say which request it sent.
//
// The thread list is read without the kernel's locks, from the frontend's control thread: the
// values are a snapshot that can be a little stale, which is enough to see threads that stay
// blocked. Only used with detailed logging on.

#include <cstdio>

#include "core/core.h"
#include "core/hle/kernel/k_process.h"
#include "core/hle/kernel/k_thread.h"

namespace Eden::ThreadDump {

inline const char* WaitName(Kernel::ThreadWaitReasonForDebugging reason) {
    using R = Kernel::ThreadWaitReasonForDebugging;
    switch (reason) {
    case R::None: return "none";
    case R::Sleep: return "sleep";
    case R::IPC: return "ipc";
    case R::Synchronization: return "sync";
    case R::ConditionVar: return "condvar";
    case R::Arbitration: return "arbitration";
    case R::Suspended: return "suspended";
    }
    return "?";
}

inline const char* StateName(Kernel::ThreadState state) {
    switch (state) {
    case Kernel::ThreadState::Initialized: return "init";
    case Kernel::ThreadState::Waiting: return "waiting";
    case Kernel::ThreadState::Runnable: return "runnable";
    case Kernel::ThreadState::Terminated: return "terminated";
    default: return "?";
    }
}

inline void Dump(Core::System& system, double seconds) {
    auto* process = system.ApplicationProcess();
    if (process == nullptr) return;
    auto& memory = process->GetMemory();
    unsigned count = 0;
    for (const auto& thread : process->GetThreadList()) {
        (void)thread;
        ++count;
    }
    std::fprintf(stderr, "EDEN_THREADS t=%.1f threads=%u code=%#llx\n", seconds, count,
                static_cast<unsigned long long>(GetInteger(process->GetEntryPoint())));
    for (const auto& thread : process->GetThreadList()) {
        const auto& context = thread.GetContext();
        const u64 tls = GetInteger(thread.GetTlsAddress());
        u32 tls_words[4]{};
        const auto reason = thread.GetWaitReasonForDebugging();
        if (reason == Kernel::ThreadWaitReasonForDebugging::IPC && tls != 0 && memory.IsValidVirtualAddress(tls))
            for (int i = 0; i < 4; ++i) tls_words[i] = memory.Read32(tls + 4 * i);
        std::fprintf(stderr, "EDEN_THREAD id=%llu state=%s susp=%#x wait=%s key=%#llx prio=%d core=%d pc=%#llx lr=%#llx "
                    "sp=%#llx x0=%#llx x1=%#llx x2=%#llx tls=[%08x %08x %08x %08x]\n",
                    static_cast<unsigned long long>(thread.GetThreadId()), StateName(thread.GetState()),
                    thread.GetSuspendFlags(), WaitName(reason),
                    static_cast<unsigned long long>(thread.GetAddressArbiterKey()), thread.GetPriority(),
                    thread.GetActiveCore(), static_cast<unsigned long long>(context.pc),
                    static_cast<unsigned long long>(context.lr), static_cast<unsigned long long>(context.sp),
                    static_cast<unsigned long long>(context.r[0]), static_cast<unsigned long long>(context.r[1]),
                    static_cast<unsigned long long>(context.r[2]), tls_words[0], tls_words[1], tls_words[2],
                    tls_words[3]);
    }
    std::fflush(stderr);
}

} // namespace Eden::ThreadDump
