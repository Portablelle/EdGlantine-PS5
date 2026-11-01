#include <cassert>
#include <array>
#include <cstdio>
#include <functional>
#include <random>
#include <vector>
#include "video_core/native_snapshot_order.h"
// Model the scheduler's real two-command-buffer order: uploads execute before
// main commands at submission. Compare snapshots against logical call order.
struct Queue {
    using Fn = std::function<void()>;
    std::vector<Fn> upload, main, device_queue;
    std::uint64_t tick{1};
    unsigned submits{};
    void Submit() {
        for (auto& fn : upload) device_queue.push_back(std::move(fn));
        for (auto& fn : main) device_queue.push_back(std::move(fn));
        upload.clear(); main.clear(); ++tick; ++submits;
    }
    void ExecuteGpu() { for (auto& fn : device_queue) fn(); device_queue.clear(); }
};
struct Source { Tegra::NativeSnapshotOrder order; unsigned device{}, logical{}; bool used{}; };
struct Captured { unsigned device{}, expected{}; };
void Write(Queue& queue, Source& source, unsigned value, bool in_upload) {
    source.logical = value;
    in_upload &= !source.used;
    if (in_upload) queue.upload.push_back([&source,value]{source.device=value;});
    else {
        source.order.MainWrite();
        source.used = true;
        queue.main.push_back([&source,value]{source.device=value;});
    }
}
void Snapshot(Queue& queue, Source& source, Captured& captured) {
    captured.expected = source.logical;
    source.used = true;
    source.order.Snapshot([&]{queue.Submit();}, [&]{
        queue.upload.push_back([&source,&captured]{captured.device=source.device;});
    });
}
int main() {
    // A GPU producer in main must complete before a snapshot in a later upload CB.
    Queue queue; Source source; Captured first, second;
    Write(queue,source,11,false); Snapshot(queue,source,first);
    Write(queue,source,22,false); Snapshot(queue,source,second); queue.Submit(); queue.ExecuteGpu();
    assert(first.device==11 && second.device==22);
    // Read-only repetitions must batch, not submit per draw.
    const auto submits=queue.submits;
    std::vector<Captured> read_only(10000);
    for(auto& value:read_only) Snapshot(queue,source,value);
    assert(queue.submits==submits); queue.Submit(); queue.ExecuteGpu();
    for(const auto& value:read_only) assert(value.device==value.expected);
    // A later CPU upload to an already used source must use main (the runtime's
    // CanReorderUpload rule). An upload to an unused/different source can remain upload.
    Source another; Captured a,b,c;
    Write(queue,another,77,true); Snapshot(queue,another,a);
    Write(queue,another,88,false); Snapshot(queue,another,b);
    Write(queue,source,33,false); Snapshot(queue,source,c); queue.Submit(); queue.ExecuteGpu();
    assert(a.device==77 && b.device==88 && c.device==33);
    // Configuration can submit after a write declaration but before the draw
    // itself is recorded. A raw declaration tick would incorrectly permit reordering.
    Queue delayed; Source delayed_source; Captured delayed_copy;
    delayed_source.logical = 99;
    delayed_source.order.MainWrite();
    delayed.Submit();
    delayed.main.push_back([&]{ delayed_source.device = 99; });
    Snapshot(delayed, delayed_source, delayed_copy);
    delayed.Submit(); delayed.ExecuteGpu();
    assert(delayed_copy.device == 99);
    std::mt19937 random(0x3901e7);
    for(unsigned run=0;run<256;++run) {
        Queue mixed;
        std::array<Source,4> sources{};
        std::array<bool,4> read_in_batch{};
        std::vector<Captured> captures(2048); size_t used=0;
        for(unsigned step=0;step<2048;++step) {
            const auto index=random()%sources.size();
            if(random()%3==0) {
                Write(mixed,sources[index],random(),!read_in_batch[index] && random()%2);
            } else {
                const auto before=mixed.tick;
                Snapshot(mixed,sources[index],captures[used++]);
                if(mixed.tick!=before) read_in_batch.fill(false);
                read_in_batch[index]=true;
            }
        }
        mixed.Submit(); mixed.ExecuteGpu();
        for(size_t i=0;i<used;++i) assert(captures[i].device==captures[i].expected);
    }
    std::puts("PASS: main GPU/CPU producers, upload producers, read-only batching, interleaved source writes and 524288 ordered events (ASan/UBSan)");
}
