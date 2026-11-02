// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <atomic>
#include <cstddef>
#include <utility>
namespace Eden::HostMemory {
inline std::atomic<std::size_t> descriptor_live{}, descriptor_peak{};
inline void Peak(std::atomic<std::size_t>& peak, std::size_t value) {
    auto old = peak.load(std::memory_order_relaxed);
    while (old < value && !peak.compare_exchange_weak(old, value, std::memory_order_relaxed)) {}
}
class DescriptorAccounting {
public:
    DescriptorAccounting() = default;
    DescriptorAccounting(const DescriptorAccounting&) = delete;
    DescriptorAccounting& operator=(const DescriptorAccounting&) = delete;
    DescriptorAccounting(DescriptorAccounting&& other) noexcept : bytes(std::exchange(other.bytes, 0)) {}
    DescriptorAccounting& operator=(DescriptorAccounting&& other) noexcept {
        if (this != &other) { Update(0); bytes = std::exchange(other.bytes, 0); }
        return *this;
    }
    ~DescriptorAccounting() { Update(0); }
    void Update(std::size_t size) noexcept {
        if (size >= bytes) {
            Peak(descriptor_peak, descriptor_live.fetch_add(size - bytes, std::memory_order_relaxed) + size - bytes);
        } else descriptor_live.fetch_sub(bytes - size, std::memory_order_relaxed);
        bytes = size;
    }
private:
    std::size_t bytes{};
};
} // namespace Eden::HostMemory
