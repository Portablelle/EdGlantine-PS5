#include "performance.h"
#include "core/hardware_properties.h"
#include <cassert>
#include <thread>
#include <vector>
int main() {
    using namespace Core::Hardware;
    static_assert(IsValidGuestCoreId(3, false));
    static_assert(!IsValidGuestCoreId(4, false) && !IsValidGuestCoreId(6, false));
    static_assert(IsValidGuestCoreId(5, true) && IsValidGuestCoreId(63, true));
    static_assert(!IsValidGuestCoreId(-1, true) && !IsValidGuestCoreId(64, true));
    static_assert(NUM_CPU_CORES == 6 && NUM_LEGACY_CPU_CORES == 4);
    static_assert(ConvertVirtualCoreMaskToPhysical(0x3f) == 0x3f);
    static_assert(ConvertVirtualCoreMaskToPhysical(0xf) == 0xf);
    static_assert(ConvertVirtualCoreMaskToPhysical((1ULL << 63) | 0xc0) == (1ULL << SYSTEM_CPU_CORE));
    for (unsigned core = 0; core < 6; ++core) {
        assert(ConvertVirtualCoreToPhysical(core) == core);
        assert(ConvertVirtualCoreMaskToPhysicalRuntime(1ULL << core) == (1ULL << core));
    }
    assert(ConvertVirtualCoreMaskToPhysicalRuntime((1ULL << 63) | 0xc0) == (1ULL << SYSTEM_CPU_CORE));
    using namespace Eden::Performance;
    static_assert(deferred_queues.size() == 6);
    static_assert(cpu_state.size() == 6);
    std::vector<std::jthread> writers;
    for (unsigned core = 0; core < 6; ++core) writers.emplace_back([core] {
        for (unsigned n = 0; n < 1000; ++n)
            DeferWrite(0x100000ULL * (core + 1) + n * 16, 8, core);
    });
    writers.clear();
    for (unsigned core = 0; core < 6; ++core) {
        const auto writes = TakeDeferredWrites(core);
        assert(writes.size() == 1000);
        for (unsigned n = 0; n < writes.size(); ++n) {
            assert(writes[n].address == 0x100000ULL * (core + 1) + n * 16);
            assert(writes[n].end == writes[n].address + 8);
        }
        assert(TakeDeferredWrites(core).empty());
    }
}
