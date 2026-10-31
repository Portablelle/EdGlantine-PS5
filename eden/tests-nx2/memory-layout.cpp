#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdio>
namespace Common {
void* AllocateGuestMemoryWhereUsed(std::size_t) noexcept;
void CommitGuestMemory(std::uint64_t, std::size_t) noexcept;
void FreeGuestMemory(void*, std::size_t) noexcept;
void GuestMemoryUsage(std::size_t*, std::size_t*) noexcept;
void SetGuestMemoryService(bool, bool, bool) noexcept;
}
int main() {
    constexpr std::size_t GiB = 1ULL << 30;
    constexpr std::size_t size = 20 * GiB;
    Common::SetGuestMemoryService(false, false, false);
    auto* memory = static_cast<unsigned char*>(Common::AllocateGuestMemoryWhereUsed(size));
    assert(memory);
    std::size_t reserved{}, held{};
    Common::GuestMemoryUsage(&reserved, &held);
    assert(reserved == size && held < 16 * 1024 * 1024);
    const std::size_t offsets[] = {0, 12 * GiB, size - 1};
    for (auto offset : offsets) {
        assert(memory[offset] == 0);
        Common::CommitGuestMemory(offset, 1);
        memory[offset] = static_cast<unsigned char>(offset % 251 + 1);
    }
    for (auto offset : offsets) assert(memory[offset] == offset % 251 + 1);
    Common::GuestMemoryUsage(&reserved, &held);
    assert(reserved == size && held == 6 * 1024 * 1024);
    Common::FreeGuestMemory(memory, size);
    Common::GuestMemoryUsage(&reserved, &held);
    assert(!reserved && !held);
    std::puts("20 GiB virtual layout: three distant pages, 6 MiB committed, release PASS (Linux backing)");
}
