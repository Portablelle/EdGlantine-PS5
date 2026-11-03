"""Exercise real BuildRandom and CMIF argument decoding; compile only on dedie."""
from pathlib import Path
import platform
import subprocess
import tempfile

assert platform.system() == 'Linux', 'Compile on dedie'
root = Path(__file__).resolve().parents[1]
source = Path((root / '.local/headless-cache').read_text().strip()) / 'source/src'


def extract(text, signature):
    start = text.index(signature)
    end = text.index('{', start) + 1
    depth = 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


mii = (source / 'core/hle/service/mii/mii.cpp').read_text()
types = (source / 'core/hle/service/mii/mii_types.h').read_text()
cmif = (source / 'core/hle/service/cmif_serialization.h').read_text()
cpp = r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <cstring>
#include <iostream>
#include <tuple>
#include <type_traits>
#include <vector>
#include "core/hle/service/cmif_types.h"
using namespace Service;
namespace Common {
constexpr size_t AlignUp(size_t value, size_t alignment) {
    return (value + alignment - 1) & ~(alignment - 1);
}
}
#define ASSERT assert
#define LOG_DEBUG(...) ((void)0)
using Result = int;
constexpr Result ResultInvalidArgument = 1;
#define R_UNLESS(condition, result) do { if (!(condition)) return result; } while (0)
#define R_SUCCEED() return 0

// Only raw inputs and Out<CharInfo> are instantiated. Other context operations
// are declarations so the complete production decoder can be parsed unchanged.
struct HLERequestContext {
    u64 GetPID();
    struct DomainHeader { unsigned input_object_count; };
    DomainHeader GetDomainMessageHeader();
    template<class T> T* GetDomainHandler(u32);
    template<class T> auto GetObjectFromHandle(u32);
    u32 GetCopyHandle(size_t);
    bool CanReadBuffer(size_t);
    std::span<const u8> ReadBuffer(size_t);
    std::span<const u8> ReadBufferA(size_t);
    std::span<const u8> ReadBufferX(size_t);
    bool CanWriteBuffer(size_t);
    size_t GetWriteBufferSize(size_t);
};
struct ScratchBuffer : std::vector<u8> {
    void resize_destructive(size_t size) { resize(size); }
};
using OutTemporaryBuffers = std::array<ScratchBuffer, 3>;
'''
for name in ('Age', 'Gender', 'Race'):
    cpp += extract(types, 'enum class ' + name + ' : u8') + ';\n'
cpp += extract(cmif, 'enum class ArgumentType') + ';\n'
cpp += 'template <typename T>\n' + extract(cmif, 'struct ArgumentTraits {') + ';\n'
cpp += 'template <typename T>\n' + extract(cmif, 'struct ArgumentTraits<Out<T>>') + ';\n'
cpp += 'template <typename T>\n' + extract(cmif, 'struct UnwrapArg {') + ';\n'
cpp += 'template <typename T>\n' + extract(cmif, 'struct UnwrapArg<Out<T>>') + ';\n'
for name in ('GetInRawDataSize', 'ReadInArgument'):
    start = cmif.rfind('template <', 0, cmif.index(name + '('))
    cpp += extract(cmif, cmif[start:cmif.index(name + '(') + len(name) + 1]) + '\n'
cpp += r'''
struct CharInfo {};
struct Manager {
    unsigned calls{};
    std::array<u32, 3> received{};
    void BuildRandom(CharInfo&, Age age, Gender gender, Race race) {
        ++calls;
        received = {static_cast<u32>(age), static_cast<u32>(gender), static_cast<u32>(race)};
    }
};
struct IDatabaseService {
    Manager* manager;
'''
cpp += extract(mii, 'Result BuildRandom(') + '\n};\n'
cpp += r'''
// Derive the decoder tuple from the real method signature, including its output.
template<class T, class... A>
Result Dispatch(T& service, Result (T::*method)(A...), const std::array<u32, 3>& words) {
    using MethodArguments = std::tuple<std::remove_cvref_t<A>...>;
    auto args = std::tuple<typename UnwrapArg<A>::Type...>();
    HLERequestContext ctx;
    OutTemporaryBuffers temp;
    ReadInArgument<MethodArguments>(false, args, reinterpret_cast<const u8*>(words.data()), ctx, temp);
    return std::apply([&](auto&... values) { return (service.*method)(values...); }, args);
}
int main() {
    Manager manager;
    IDatabaseService service{&manager};
    auto run = [&](const std::array<u32, 3>& words) {
        return Dispatch(service, &IDatabaseService::BuildRandom, words);
    };
    // Main reads {1, 0, 0} from these words, losing both gender and race.
    const std::array<u32, 3> distinct{1, 1, 2};
    assert(run(distinct) == 0);
    assert(manager.calls == 1 && manager.received == distinct);
    const std::array<u32, 3> limits{static_cast<u32>(Age::All),
                                    static_cast<u32>(Gender::All),
                                    static_cast<u32>(Race::All)};
    // Exhaust the small valid domain, including all three All sentinels.
    for (u32 age = 0; age <= limits[0]; ++age) {
        for (u32 gender = 0; gender <= limits[1]; ++gender) {
            for (u32 race = 0; race <= limits[2]; ++race) {
                const std::array<u32, 3> words{age, gender, race};
                const auto calls = manager.calls;
                assert(run(words) == 0);
                assert(manager.calls == calls + 1 && manager.received == words);
            }
        }
    }
    for (size_t field = 0; field < 3; ++field) {
        // Low bytes can look valid: reject the full word before narrowing.
        for (u32 invalid : {limits[field] + 1, 0x100u, 0x10001u,
                            0x01000000u, 0x80000000u, 0xffffffffu}) {
            std::array<u32, 3> words{};
            words[field] = invalid;
            const auto calls = manager.calls;
            const auto received = manager.received;
            assert(run(words) == ResultInvalidArgument);
            assert(manager.calls == calls && manager.received == received);
        }
    }
    std::cout << "MII_BUILDRANDOM_ARGS_PASS\n";
}
'''
with tempfile.TemporaryDirectory(prefix='mii-buildrandom-args-') as td:
    temp = Path(td)
    (temp / 'check.cpp').write_text(cpp)
    subprocess.run(['clang++-18', '-std=c++20', '-O1', '-g',
                    '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                    '-I' + str(source), str(temp / 'check.cpp'),
                    '-o', str(temp / 'check')], check=True)
    subprocess.run([str(temp / 'check')], check=True)
