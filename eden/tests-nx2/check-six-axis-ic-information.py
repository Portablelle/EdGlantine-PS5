"""Compile real six-axis IC defaults, state selection and getter; run only on dedie."""
from pathlib import Path
import platform
import subprocess
import tempfile

assert platform.system() == 'Linux', 'Compile on dedie'
root = Path(__file__).resolve().parents[1]
source = Path((root / '.local/headless-cache').read_text().strip()) / 'source/src'
header = (source / 'hid_core/resources/six_axis/six_axis.h').read_text()
implementation = (source / 'hid_core/resources/six_axis/six_axis.cpp').read_text()
types = (source / 'hid_core/hid_types.h').read_text()


def extract(text, signature):
    start = text.index(signature)
    end = text.index('{', start) + 1
    depth = 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


# Keep the production initializer as well as its helper: main must compile and
# reach the range assertions with its original zero-initialized member.
parameters_end = header.index('    struct NpadControllerData')
defaults = header[header.index('    static constexpr std::size_t NPAD_COUNT'):parameters_end]
controller = extract(header, 'struct NpadControllerData') + ';'
ic_type = extract(types, 'struct SixAxisSensorIcInformation') + ';'
cpp = r'''
#include <array>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <type_traits>
using f32 = float;
struct Result { unsigned raw{}; bool IsError() const { return raw != 0; } };
constexpr Result ResultSuccess{};
#define LOG_ERROR(...) ((void)0)
namespace Core::HID {
class EmulatedController;
enum class NpadStyleIndex { None, Fullkey, Handheld, JoyconDual, JoyconLeft, JoyconRight, Pokeball };
enum class DeviceIndex { Left, Right };
enum class GyroscopeZeroDriftMode { Standard };
struct SixAxisSensorHandle { NpadStyleIndex npad_type; unsigned npad_id; DeviceIndex device_index; };
struct SixAxisSensorFusionParameters {};
struct SixAxisSensorCalibrationParameter {};
struct SixAxisSensorState {};
''' + ic_type + r'''
static_assert(sizeof(SixAxisSensorIcInformation) == 0xC8);
static_assert(std::is_trivial_v<SixAxisSensorIcInformation>);
}
namespace Service::HID {
Result IsSixaxisHandleValid(const Core::HID::SixAxisSensorHandle& h) {
    return {h.npad_id < 10 ? 0U : 123U};
}
class SixAxis {
public:
    Result GetSixAxisSensorIcInformation(const Core::HID::SixAxisSensorHandle&,
                                       Core::HID::SixAxisSensorIcInformation&) const;
private:
''' + defaults + controller + r'''
    const SixaxisParameters& GetSixaxisState(const Core::HID::SixAxisSensorHandle&) const;
    const NpadControllerData& GetControllerFromHandle(const Core::HID::SixAxisSensorHandle& h) const {
        return controller_data.at(h.npad_id);
    }
''' + header[header.index('    std::array<NpadControllerData, NPAD_COUNT>'):header.index('\n};')] + r'''
};
''' + extract(implementation, 'const SixAxis::SixaxisParameters& SixAxis::GetSixaxisState(') + '\n'
cpp += extract(implementation, 'Result SixAxis::GetSixAxisSensorIcInformation(') + r'''
}
int main() {
    using namespace Core::HID;
    const Service::HID::SixAxis sensor;
    for (unsigned id = 0; id < 10; ++id) {
        for (auto style : {NpadStyleIndex::Fullkey, NpadStyleIndex::Handheld,
                           NpadStyleIndex::JoyconDual, NpadStyleIndex::JoyconLeft,
                           NpadStyleIndex::JoyconRight, NpadStyleIndex::Pokeball,
                           NpadStyleIndex::None}) {
            for (auto side : {DeviceIndex::Left, DeviceIndex::Right}) {
                SixAxisSensorIcInformation info{};
                info.angular_rate = -1.0f;
                info.acceleration_range = -1.0f;
                assert(!sensor.GetSixAxisSensorIcInformation({style, id, side}, info).IsError());
                assert(info.angular_rate == 2000.0f); // degrees/second, not revolutions/second
                assert(info.acceleration_range == 8.0f); // g, not m/s^2
                for (auto value : info.unknown_gyro_data1) assert(value == 0.0f);
                for (auto value : info.unknown_gyro_data2) assert(value == 0.0f);
                for (auto value : info.unknown_gyro_data3) assert(value == 0.0f);
                for (auto value : info.unknown_accel_data1) assert(value == 0.0f);
                for (auto value : info.unknown_accel_data2) assert(value == 0.0f);
                for (auto value : info.unknown_accel_data3) assert(value == 0.0f);
            }
        }
    }
    SixAxisSensorIcInformation untouched{};
    untouched.angular_rate = -1.0f;
    untouched.acceleration_range = -2.0f;
    const auto invalid = sensor.GetSixAxisSensorIcInformation(
        {NpadStyleIndex::Fullkey, 10, DeviceIndex::Left}, untouched);
    assert(invalid.raw == 123);
    assert(untouched.angular_rate == -1.0f && untouched.acceleration_range == -2.0f);
    std::puts("SIX_AXIS_IC_INFORMATION_PASS");
}
'''
with tempfile.TemporaryDirectory(prefix='six-axis-ic-information-') as td:
    temp = Path(td)
    (temp / 'check.cpp').write_text(cpp)
    subprocess.run(['clang++-18', '-std=c++20', '-O1', '-g',
                    '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                    str(temp / 'check.cpp'), '-o', str(temp / 'check')], check=True)
    subprocess.run([str(temp / 'check')], check=True)
