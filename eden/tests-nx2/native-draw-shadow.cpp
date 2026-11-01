#include <cassert>
#include <cstdio>
#include <random>
#include "video_core/native_draw_shadow.h"
using Ledger = Tegra::NativeDrawShadow;
using W = Ledger::Word;
struct Harness {
    Ledger ledger;
    Ledger::Values registers{10, 20, 30, 40}, shadow{50, 60, 70, 80};
    Ledger::Values expected_registers = registers, expected_shadow = shadow;
    std::vector<Ledger::Arguments> immutable;
    unsigned reads{}, discards{};
    void Resolve() {
        if (ledger.Empty()) return;
        ledger.Resolve(immutable, registers, shadow);
        assert(registers == expected_registers && shadow == expected_shadow);
        ledger.Clear(); immutable.clear(); ++reads;
    }
    void Add(Ledger::Arguments arguments, bool track) {
        if (ledger.Full()) Resolve();
        if (ledger.Empty()) ledger.Begin(registers, shadow);
        const auto update = [&](Ledger::Values& out) {
            out[0] = arguments[2];
            if (arguments[1]) {
                out[1] = arguments[0]; out[2] = 4 | (arguments[1] > 1 ? 1U << 26 : 0); out[3] = 0;
            }
        };
        update(expected_registers); if (track) update(expected_shadow);
        ledger.AddSnapshot(immutable.size(), 4, track);
        immutable.push_back(arguments);
        // Guest arguments can be overwritten immediately: the snapshot must keep old bytes.
        arguments.fill(0xbad);
    }
    void Write(unsigned index, W value, bool to_shadow) {
        if (ledger.Full()) Resolve();
        const bool discarded = ledger.Write(Ledger::Methods[index], value, to_shadow);
        (to_shadow ? shadow : registers)[index] = value;
        (to_shadow ? expected_shadow : expected_registers)[index] = value;
        if (discarded) {
            ++discards; immutable.clear();
            assert(registers == expected_registers && shadow == expected_shadow);
        }
    }
    void Read(unsigned index, bool from_shadow) {
        if (ledger.NeedsRead(Ledger::Methods[index], from_shadow)) Resolve();
        assert((from_shadow ? shadow : registers)[index] ==
               (from_shadow ? expected_shadow : expected_registers)[index]);
    }
};
int main() {
    // All later CPU writes, including same stale values, remove waits without losing state.
    Harness overwritten;
    overwritten.Add({100, 3, 50, 7, 8}, true);
    for (unsigned i = 0; i < 4; ++i) {
        const W value = overwritten.registers[i];
        overwritten.Write(i, value, true); overwritten.Write(i, value, false);
    }
    assert(overwritten.ledger.Empty() && overwritten.reads == 0 && overwritten.discards == 1);
    // A zero-instance command changes firstIndex but preserves previous count/begin/end.
    Harness zero;
    zero.Add({100, 3, 50, 7, 8}, true); zero.Add({200, 0, 77, 9, 10}, true);
    zero.Read(1, true); assert(zero.shadow[0] == 77 && zero.shadow[1] == 100);
    assert(zero.shadow[2] == (4 | (1U << 26)) && zero.reads == 1);
    // Partial CPU overwrites and passthrough affect different destinations.
    Harness partial;
    partial.Add({100, 2, 33, 0, 0}, true);
    partial.Write(0, 123, true); partial.Add({500, 0, 444, 0, 0}, false);
    partial.Read(0, true); partial.Resolve();
    assert(partial.shadow[0] == 123 && partial.registers[0] == 444);
    // Capacity flush is bounded and does not discard unobserved values.
    Harness capacity;
    for (unsigned i = 0; i < Ledger::MaxSnapshots + 2; ++i) capacity.Add({i, i % 4, i+1, 0, 0}, true);
    assert(capacity.reads == 1); capacity.Resolve();
    std::mt19937 random(0x3801e7);
    for (unsigned run = 0; run < 128; ++run) {
        Harness mixed;
        for (unsigned step = 0; step < 4096; ++step) {
            const auto action = random() % 5;
            if (action < 2) mixed.Add({W(random()), W(random()%4), W(random()), W(random()), W(random())}, action == 0);
            else if (action < 4) mixed.Write(random()%4, W(random()), action == 2);
            else mixed.Read(random()%4, random()%2);
        }
        mixed.Resolve();
        assert(mixed.registers == mixed.expected_registers && mixed.shadow == mixed.expected_shadow);
    }
    std::puts("PASS: zero-instance history, partial writes/replay, full overwrite without waits, immutable snapshots, capacity, 524288 mixed events (ASan/UBSan)");
}
