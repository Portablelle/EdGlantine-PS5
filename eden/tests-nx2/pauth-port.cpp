// SPDX-License-Identifier: GPL-3.0-or-later
#include <catch2/catch_test_macros.hpp>
#include <catch2/generators/catch_generators.hpp>
#include "dynarmic/tests/A64/testenv.h"

namespace {
class PortReturnEnv final : public A64TestEnv {
public:
    Dynarmic::A64::Jit* jit{};
    std::optional<Dynarmic::A64::Exception> exception;
    void ExceptionRaised(u64, Dynarmic::A64::Exception reason) override {
        exception = reason;
        jit->HaltExecution(Dynarmic::HaltReason::UserDefined1);
    }
};
}

TEST_CASE("NX2 port executes authenticated returns through Run", "[pauth][nx2-jit]") {
    const bool enabled = GENERATE(false, true);
    const bool authenticated = GENERATE(false, true);
    const bool key_b = GENERATE(false, true);
    PortReturnEnv env;
    // PACIASP/PACIBSP, RETAA/RETAB (or legacy RET), target is an infinite branch.
    env.code_mem = {key_b ? 0xD503237FU : 0xD503233FU,
                   authenticated ? (key_b ? 0xD65F0FFFU : 0xD65F0BFFU) : 0xD65F03C0U,
                   0x14000000U};
    Dynarmic::A64::UserConfig config;
    config.callbacks = &env;
    config.enable_pauth_returns = enabled;
    config.code_cache_size = 16 * 1024 * 1024;
    Dynarmic::A64::Jit jit{config};
    env.jit = &jit;
    jit.SetPC(0);
    jit.SetRegister(30, 8);
    jit.SetSP(0x10000);
    env.ticks_left = 2;
    jit.Run();
    REQUIRE(env.exception.has_value() == (authenticated && !enabled));
    if (!env.exception) REQUIRE(jit.GetPC() == 8);
    REQUIRE(jit.GetRegister(30) == 8);
    REQUIRE(jit.GetSP() == 0x10000);
}

extern "C" void* eden_jit_list_open();
extern "C" void eden_jit_list_close(void*);
extern "C" int eden_jit_precompile(void*, unsigned long long);

TEST_CASE("NX2 port precompiles authenticated returns for shared cores", "[pauth][nx2-jit]") {
    class SharedEnv final : public A64TestEnv {
    public:
        Dynarmic::A64::Jit* jit{};
        bool exception = false;
        bool reached_target = false;
        void ExceptionRaised(u64, Dynarmic::A64::Exception) override {
            exception = true;
            jit->HaltExecution(Dynarmic::HaltReason::UserDefined1);
        }
        void CallSVC(u32) override {
            reached_target = true;
            jit->HaltExecution(Dynarmic::HaltReason::UserDefined1);
        }
    } env;
    const bool enabled = GENERATE(false, true);
    env.code_mem = {0xD65F0FFFU, 0xD4000001U}; // RETAB; SVC 0 stops the test.
    void* table[1]{}; // No data access; identifies the shared address space.
    Dynarmic::A64::UserConfig config;
    config.callbacks = &env;
    config.enable_pauth_returns = enabled;
    config.enable_cycle_counting = false;
    config.page_table = table;
    config.code_cache_size = 16 * 1024 * 1024;
    Dynarmic::A64::Jit first{config}, second{config};
    auto* group = eden_jit_list_open();
    REQUIRE(group != nullptr);
    const int compiled = eden_jit_precompile(group, 0); // PC=0, FPCR=0.
    eden_jit_list_close(group);
    REQUIRE(compiled == 1);
    env.jit = &second;
    second.SetPC(0);
    second.SetRegister(30, 4);
    second.SetSP(0x10000);
    second.Run();
    REQUIRE(env.exception == !enabled);
    REQUIRE(env.reached_target == enabled);
    REQUIRE(second.GetRegister(30) == 4);
    REQUIRE(second.GetSP() == 0x10000);
}
