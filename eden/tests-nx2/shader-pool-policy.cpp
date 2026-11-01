// SPDX-License-Identifier: GPL-3.0-or-later
#include <cassert>
#include <cstdlib>
#include <memory>
#include <vector>

#include "shader_recompiler/object_pool.h"
#include "shader_recompiler/undef_policy.h"

namespace {
struct Owned {
    static inline int live = 0;
    static inline int destroyed = 0;
    std::unique_ptr<int[]> allocation = std::make_unique<int[]>(128);
    Owned() { ++live; }
    ~Owned() { --live; ++destroyed; }
};
}

int main(int argc, char** argv) {
    assert(argc == 2);
    const bool expected_zero = argv[1][0] == '1';
    assert(Shader::UndefIsZero() == expected_zero);
    assert(Shader::VulkanShaderCacheVersion() == (expected_zero ? 38U : 39U));
    // The policy and cache version stay together even if the environment changes mid-session.
    assert(setenv("EDEN_NX2_UNDEF_ZERO", expected_zero ? "0" : "1", 1) == 0);
    assert(Shader::UndefIsZero() == expected_zero);
    assert(Shader::VulkanShaderCacheVersion() == (expected_zero ? 38U : 39U));
    {
        Shader::ObjectPool<Owned> pool{2};
        pool.ReleaseContents(); // No object has been constructed.
        for (int i = 0; i < 7; ++i) (void)pool.Create(); // Move chunks during vector growth.
        assert(Owned::live == 7);
        pool.ReleaseContents(); // Full root: destroy all chunks and consolidate capacity.
        assert(Owned::live == 0 && Owned::destroyed == 7);
        (void)pool.Create();
        pool.ReleaseContents(); // Partly filled root: retain storage but destroy used slots.
        pool.ReleaseContents(); // Never destroy a slot twice.
        assert(Owned::live == 0 && Owned::destroyed == 8);
        for (int i = 0; i < 11; ++i) (void)pool.Create();
        assert(Owned::live == 11);
    } // Destroy multiple chunks without an explicit release.
    assert(Owned::live == 0 && Owned::destroyed == 19);
}
