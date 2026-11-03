"""Compile real HID command 214 with recording shims; run only on dedie."""
from pathlib import Path
import platform
import subprocess
import tempfile

assert platform.system() == 'Linux', 'Compile on dedie'
root = Path(__file__).resolve().parents[1]
source = Path((root / '.local/headless-cache').read_text().strip()) / 'source/src'
text = (source / 'core/hle/service/hid/hid_server.cpp').read_text()
header = (source / 'core/hle/service/hid/hid_server.h').read_text()


def function(name):
    start = text.index('Result IHidServer::' + name + '(')
    end = text.index('{', start) + 1
    depth = 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


def declaration(name):
    start = header.index('Result ' + name + '(')
    return header[start:header.index(';', start) + 1]


# Also compile 206 so the pre-fix 214 compiles and fails behavioral assertions.
code = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <span>
#include <string>
#include <vector>
using u16 = uint16_t;
using u32 = uint32_t;
using u64 = uint64_t;
struct Result {
    u32 raw{};
    bool IsError() const { return raw != 0; }
};
constexpr Result ResultVibrationArraySizeMismatch{2};
namespace IPC { constexpr Result ResultNotSupported{1}; }
#define R_SUCCEED() return Result{}
#define R_RETURN(value) return (value)
#define R_UNLESS(condition, error) do { if (!(condition)) return (error); } while (false)
#define R_TRY(value) do { const auto result = (value); if (result.IsError()) return result; } while (false)
struct AppletResourceUserId { u64 pid; };
struct ClientAppletResourceUserId { u64 pid; };
namespace Core::HID {
struct VibrationDeviceHandle { u32 id; };
struct VibrationValue { float amplitude; };
}
constexpr int BufferAttr_HipcPointer = 1;
template <class T, int> using InArray = std::span<const T>;
unsigned info_count{}, error_count{};
u64 logged_flags{};
void LogInfo(u64 flags, u64, size_t, size_t) { ++info_count; logged_flags = flags; }
template <class... Args> void LogDebug(const char* message, Args...) {
    if (std::string(message).find("failed to send vibration") != std::string::npos) ++error_count;
}
#define LOG_INFO(category, message, ...) LogInfo(__VA_ARGS__)
#define LOG_DEBUG(category, message, ...) LogDebug(message, __VA_ARGS__)
struct ResourceManager {
    std::vector<u32> handles;
    std::vector<float> values;
    int fail_at = -1;
    Result SendVibrationValue(u64 aruid, Core::HID::VibrationDeviceHandle handle,
                              Core::HID::VibrationValue value) {
        assert(aruid == 0x123456789abcdef0ULL);
        const int index = static_cast<int>(handles.size());
        handles.push_back(handle.id);
        values.push_back(value.amplitude);
        return Result{index == fail_at ? 99U : 0U};
    }
};
struct IHidServer {
    ResourceManager manager;
    ResourceManager* GetResourceManager() { return &manager; }
''' + declaration('SendNativeVibrationValues') + '\n' + declaration('SendVibrationValues') + r'''
};
''' + function('SendVibrationValues') + '\n' + function('SendNativeVibrationValues') + r'''
int main(int argc, char** argv) {
    assert(argc == 2);
    const std::string test = argv[1];
    u64 flags = 0;
    size_t handle_count = 3, value_count = 3;
    IHidServer server;
    if (test == "unknown-flags") flags = 1;
    if (test == "full-word") flags = 0xfedcba9876540002ULL;
    if (test == "value-error") server.manager.fail_at = 1;
    if (test == "extra-handles") { flags = 2; value_count = 1; }
    if (test == "extra-values") handle_count = 1;
    if (test == "empty-handles") handle_count = 0;
    if (test == "empty-values") value_count = 0;
    if (test == "empty-both") handle_count = value_count = 0;
    std::vector<Core::HID::VibrationDeviceHandle> handles(handle_count);
    std::vector<Core::HID::VibrationValue> values(value_count);
    for (size_t i = 0; i < handle_count; ++i) handles[i].id = 10 + i;
    for (size_t i = 0; i < value_count; ++i) values[i].amplitude = 0.25f * (i + 1);
    const auto result = server.SendNativeVibrationValues(
        flags, AppletResourceUserId{0x123456789abcdef0ULL}, handles, values);
    assert(!result.IsError() && "command 214 must always succeed");
    const auto count = (std::min)(handle_count, value_count);
    assert(server.manager.handles.size() == count && "send every available pair, even after errors");
    for (size_t i = 0; i < count; ++i) {
        assert(server.manager.handles[i] == handles[i].id);
        assert(server.manager.values[i] == values[i].amplitude);
    }
    assert(error_count == (test == "value-error" ? 1U : 0U));
    assert(info_count == 1 && logged_flags == flags);
    // Keep the existing first-eight-batches INFO diagnostic, including all 64 bits.
    for (unsigned i = 0; i < 12; ++i) {
        assert(!server.SendNativeVibrationValues(2, AppletResourceUserId{0x123456789abcdef0ULL},
                                                 {}, {}).IsError());
    }
    assert(info_count == 8);
    std::cout << test << ": PASS\n";
}
'''

with tempfile.TemporaryDirectory(prefix='nx2-vibration-best-effort-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(code)
    subprocess.run(['clang++-18', '-std=c++20', '-O1', '-g',
                    '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    failed = []
    for case in ('normal', 'unknown-flags', 'full-word', 'value-error', 'extra-handles',
                 'extra-values', 'empty-handles', 'empty-values', 'empty-both'):
        if subprocess.run([str(path / 'check'), case]).returncode:
            failed.append(case)
    assert not failed, f'Command 214 contract failures: {failed}'
print('NX2_VIBRATION_BEST_EFFORT_PASS (ASan/UBSan)')
