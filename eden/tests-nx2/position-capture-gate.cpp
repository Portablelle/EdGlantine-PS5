// SPDX-License-Identifier: GPL-3.0-or-later
#include "video_core/position_capture_gate.h"
#include <cassert>
#include <cstdio>
int main() {
    Eden::PositionCaptureGate gate;
    gate.Reset(3);
    assert(!gate.Accept(360, -360, 1, 1, true)); // portrait target
    assert(!gate.Accept(1024, -512, 1, 1, true)); // shadow pass
    assert(!gate.Accept(960, -540, 1, 1, false)); // skipped/filter mismatch does not consume pair
    assert(gate.Accept(960, -540, 1, 1, true));
    assert(!gate.Accept(960, -540, 1, 1, true));
    assert(gate.Accept(960, -540, 1, 2, true));
    gate.Reset(3);
    assert(gate.Accept(-960, 540, 1, 1, true)); // new capture restores eligibility
    gate.Reset(2);
    assert(gate.Accept(960, -540, 1, 1, true));
    assert(gate.Accept(960, -540, 1, 1, true)); // main-view mode can keep duplicates
    gate.Reset(0);
    assert(gate.Accept(360, -360, 1, 1, true)); // legacy mode
    gate.Reset(3);
    for (int i=0; i<2048; ++i) assert(!gate.Accept(360, -360, 1, 1, true));
    assert(!gate.Exhausted());
    assert(!gate.Accept(960, -540, 1, 1, true));
    assert(gate.Exhausted()); // terminates even with no matching main-view draws
    gate.Reset(0, 2048);
    for (int i=0;i<2048;++i) assert(!gate.Accept(960,-540,1,1,false));
    assert(gate.Accept(960,-540,1,1,true));
    gate.Reset(0, 16384);
    for (int i=0;i<18433;++i) assert(!gate.Accept(960,-540,1,1,false));
    assert(gate.Exhausted());
    std::puts("PASS main-view filtering, pair deduplication, capture reset and bounded completion");
}
