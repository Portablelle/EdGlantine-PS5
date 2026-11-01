// Focused semantic comparison against the actual captured native MME program.
#include <cassert>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <random>
#include <vector>
#include "video_core/native_draw_indirect.h"
#include "video_core/macro_turing.h"
namespace Hle = Tegra::NativeDrawIndirect;
using W = std::uint32_t;
struct Draw {
    W count, first, base_vertex, base_instance, instance;
    bool operator==(const Draw&) const = default;
};
template<class T> std::vector<T> Load(const std::filesystem::path& path) {
    std::ifstream file(path, std::ios::binary | std::ios::ate); assert(file);
    const auto bytes = file.tellg(); assert(bytes >= 0 && size_t(bytes) % sizeof(T) == 0);
    std::vector<T> out(size_t(bytes) / sizeof(T)); file.seekg(0);
    file.read(reinterpret_cast<char*>(out.data()), bytes); assert(file); return out;
}
struct Machine {
    std::array<W, 0xe00> regs{};
    std::array<W, 2> constants{};
    std::vector<std::array<W, 3>> events;
    std::vector<Draw> draws;
    W instance{}, begin{}, position{};
    bool Emit(W method, W value) {
        assert(method < regs.size()); regs[method] = value;
        events.push_back({1, method, value});
        if (method == 0x8e3) position = value;
        if (method == 0x8e4 || method == 0x8e5) {
            assert(position == 0x640 || position == 0x644);
            constants[(position - 0x640) / 4] = value; position += 4;
        }
        if (method == 0x586) {
            begin = value;
            if (((value >> 26) & 3) == 0) instance = 0;
            else if (((value >> 26) & 3) == 1) ++instance;
            else assert(false);
        }
        if (method == 0x585 && regs[0x5f8]) {
            assert((begin & 0xffff) == 4 && value == 0);
            assert(constants[0] == regs[0x50d] && constants[1] == regs[0x50e]);
            assert(regs[0x446] == regs[0x50d]);
            draws.push_back({regs[0x5f8], regs[0x5f7], regs[0x50d], regs[0x50e], instance});
        }
        return true;
    }
};
#include "native-draw-recording.h"
void Compare(std::span<const W> code, std::vector<W> params,
             const std::vector<std::array<W, 3>>* captured_events = nullptr) {
    Tegra::TuringMacroInterpreter interpreter;
    Machine native;
    const auto result = interpreter.Execute(code, Hle::Entry, params,
        [](W) -> W { assert(false && "This macro must not read engine registers"); return 0; },
        [&](W method, W value) { return native.Emit(method, value); });
    assert(result.success && result.consumed == 6);
    assert(interpreter.dram == Tegra::TuringMacroInterpreter::DataRam{});
    if (captured_events) assert(native.events == *captured_events);
    const Machine hle_final=RunProduction(code,params);
    assert(native.draws==hle_final.draws);
    for (W method : {0x446, 0x50d, 0x50e}) assert(native.regs[method] == hle_final.regs[method]);
    assert(native.constants == hle_final.constants && native.position == hle_final.position);
}
int main(int argc, char** argv) {
    assert(argc <= 2);
    const std::filesystem::path dir = argc==2 ? argv[1] : ".";
    unsigned captures = 0;
    std::vector<W> code;
    if(argc==2) for (const auto& file : std::filesystem::directory_iterator(dir)) {
        const auto path = file.path();
        if (!path.string().ends_with(".code.bin")) continue;
        code = Load<W>(path);
        assert(Hle::SdkHash(code) == Hle::KnownSdkHash && Hle::Matches(code, Hle::Entry));
        auto stem = path.string(); stem.resize(stem.size() - 9);
        auto params = Load<W>(stem + ".params.bin");
        auto addresses = Load<std::uint64_t>(stem + ".addresses.bin");
        assert(Hle::ArgumentShape(params, addresses));
        const auto events = Load<std::array<W, 3>>(stem + ".events.bin");
        Compare(code, params, &events); ++captures;
    }
    if(argc==2) assert(captures);
    else {
        code.resize(Hle::Entry*3+Hle::Program.size());
        std::copy(Hle::Program.begin(),Hle::Program.end(),code.begin()+Hle::Entry*3);
    }
    // Any instruction change or entry mismatch must reject before engine side effects.
    for (size_t i = 0; i < Hle::Program.size(); ++i) {
        auto changed = code; changed[Hle::Entry * 3 + i] ^= 1;
        assert(!Hle::Matches(changed, Hle::Entry));
    }
    assert(!Hle::Matches({}, Hle::Entry) && !Hle::Matches(code, Hle::Entry + 1));
    assert(!Hle::Matches(std::span{code}.first(Hle::Entry * 3 + 1), Hle::Entry));
    std::vector<W> params{4, 0, 0, 0, 0, 0};
    std::array<std::uint64_t, 6> addresses{0x2000, 0x3000, 0x3004, 0x3008, 0x300c, 0x3010};
    assert(Hle::ArgumentShape(params, addresses));
    for (size_t i = 1; i < 6; ++i) {
        auto broken = addresses; broken[i] += 4; assert(!Hle::ArgumentShape(params, broken));
    }
    params[0] = 7; assert(!Hle::ArgumentShape(params, addresses)); params[0] = 4;
    assert(!Hle::ArgumentShape(std::span{params}.first(5), addresses));
    addresses[1] = ~std::uint64_t{3}; assert(!Hle::ArgumentShape(params, addresses));
    std::mt19937 random(0x1e7037);
    for (unsigned test = 0; test < 4096; ++test) {
        params = {4, test % 7 ? W(random()) : 0U, test % 17, W(random()), W(random()), W(random())};
        Compare(code, params);
    }
    std::printf("PASS: %u captured trace(s), 4096 randomized interpreter/production-HLE recording comparisons, code/source rejection guards\n", captures);
}
