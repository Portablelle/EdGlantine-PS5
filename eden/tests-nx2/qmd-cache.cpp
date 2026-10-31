#include "video_core/native_qmd.h"
#include <cassert>
int main() {
    Tegra::NativeQmdScheduler engine;
    using Descriptor = Tegra::NativeQmdScheduler::Descriptor;
    const auto read = [](uint64_t address, Descriptor& qmd) {
        qmd = {};
        qmd[18] = 0x30;
        if (address == 2) qmd[4] = 1U << 14;
        return true;
    };
    const auto release = [](uint64_t, uint32_t) { return true; };
    // Preserve signals not yet associated with a descriptor and a waiting descriptor.
    assert(engine.Signal(1, 12, read, release).empty());
    assert(engine.Signal(2, 3, read, release).empty());
    // A completed descriptor with a deferred signal must also survive collection.
    assert(engine.Signal(3, 3, read, release).empty());
    assert(engine.Signal(3, 12, read, release).empty());
    for (uint64_t address = 100; address < 12100; ++address)
        assert(engine.Signal(address, 3, read, release).empty());
    assert(engine.Inspect(100).flags == 7);
    assert(engine.Signal(100, 2, read, release).empty());
    assert(engine.Inspect(100).flags == 7);
    assert(engine.Inspect(1).deferred == 1);
    assert(engine.Inspect(2).dependencies == 1);
    assert((engine.Inspect(2).flags & 4) == 0);
    assert(engine.Inspect(3).deferred == 1);
    assert(engine.Signal(2, 7, read, release).empty());
    assert((engine.Inspect(2).flags & 4) != 0);
    // Explicit resubmission can reload a completed descriptor normally.
    assert(engine.Signal(100, 3, read, release).empty());
    assert((engine.Inspect(100).flags & 4) != 0);
}
