"""Compile real audio service ownership/cleanup with framework shims; dedie only."""
from pathlib import Path
import platform
import re
import subprocess

assert platform.system() == 'Linux', 'Run on dedie'
root = Path(__file__).resolve().parents[1]
source = Path((root / '.local/headless-cache').read_text().strip()) / 'source/src'
out = root / 'build/nx2-tests/audio-out-session-lifetime'
out.mkdir(parents=True, exist_ok=True)
audio = source / 'core/hle/service/audio'


def function(text, signature, constructor=False):
    start = text.index(signature)
    # Constructors have braced member initializers before the actual body.
    brace = (text.rfind('{', start, text.index('// clang-format off', start))
             if constructor else text.index('{', start))
    end, depth = brace + 1, 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end] + '\n'


def header(name):
    return '\n'.join(line for line in (audio / name).read_text().splitlines()
                     if not line.startswith(('#include', '#pragma once')))


manager = (audio / 'audio_out_manager.cpp').read_text()
session = (audio / 'audio_out.cpp').read_text()
# Exercise the actual OpenAudioOutAuto construction expression in the test factory.
open_out = re.search(r'auto audio_out = std::make_shared<IAudioOut>\(.*?;',
                     manager, re.S).group()
code = r'''
#include <array>
#include <cassert>
#include <cstdint>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <utility>
#include <vector>
using u32 = uint32_t; using u64 = uint64_t; using f32 = float; using Result = int;
namespace Core { struct System { int Kernel() { return 0; } }; }
namespace Kernel {
struct KEvent {}; struct KReadableEvent {};
struct KProcess {
    int refs = 0;
    void Open(int) { ++refs; }
    void Close(int) { --refs; }
};
}
namespace AudioCore::Renderer::AudioDevice { using AudioDeviceName = std::string; }
namespace AudioCore::AudioOut {
inline int live = 0, releases = 0;
struct Out;
struct Manager {
    explicit Manager(Core::System&) { ++live; }
    ~Manager() { --live; }
    std::mutex mutex;
    std::array<std::shared_ptr<Out>, 2> sessions{};
    void ReleaseSessionId(size_t id) { assert(live == 1); ++releases; sessions[id].reset(); }
};
struct AudioOutParameter {}; struct AudioOutParameterInternal {}; struct AudioOutBuffer {};
struct System {
    size_t id;
    size_t GetSessionId() { return id; }
};
struct Out {
    Manager& manager;
    std::mutex& parent_mutex;
    System system;
    Out(Core::System&, Manager& m, Kernel::KEvent*, size_t id)
        : manager(m), parent_mutex(m.mutex), system{id} {}
    void Free();
};
}
namespace Service {
constexpr int BufferAttr_HipcMapAlias = 0, BufferAttr_HipcAutoSelect = 1;
template<class T> using Out = T*;
template<class T> using SharedPointer = std::shared_ptr<T>;
template<class T, int> using InArray = std::vector<T>;
template<class T, int> using OutArray = std::vector<T>;
template<class T> using OutCopyHandle = T**;
template<class T> struct InCopyHandle { T* ptr; T* Get() { return ptr; } };
struct ClientAppletResourceUserId { u64 pid; };
namespace KernelHelpers {
struct ServiceContext {
    ServiceContext(Core::System&, const char*) {}
    Kernel::KEvent* CreateEvent(const char*) { return new Kernel::KEvent; }
    void CloseEvent(Kernel::KEvent* event) { delete event; }
};
}
template<auto> constexpr int D = 0;
template<class T> struct ServiceFramework {
    struct FunctionInfo { int id, handler; const char* name; };
    Core::System& system;
    ServiceFramework(Core::System& s, const char*) : system(s) {}
    virtual ~ServiceFramework() = default;
    template<size_t N> void RegisterHandlers(const FunctionInfo (&)[N]) {}
};
}
'''
code += header('audio_out.h')
# Expose the manager member only to the factory; storage type and order stay real.
code += header('audio_out_manager.h').replace('private:', 'public:')
code += '\nnamespace Service::Audio {\nusing namespace AudioCore::AudioOut;\n'
code += function(manager, 'IAudioOutManager::IAudioOutManager(', True)
code += 'IAudioOutManager::~IAudioOutManager() = default;\n'
code += function(session, 'IAudioOut::IAudioOut(', True)
code += function(session, 'IAudioOut::~IAudioOut(')
code += r'''
std::shared_ptr<IAudioOut> Open(IAudioOutManager& service, Kernel::KProcess* process, size_t id) {
    auto& system = service.system;
    auto& impl = service.impl;
    const auto new_session_id = id;
    const std::string device_name = "DeviceOut";
    AudioOutParameter parameter;
    InCopyHandle<Kernel::KProcess> process_handle{process};
    ClientAppletResourceUserId aruid{};
'''
code += open_out + '\n'
code += '''    impl->sessions[id] = audio_out->GetImpl();
    return audio_out;
}
}
namespace AudioCore::AudioOut {
'''
code += function((source / 'audio_core/out/audio_out.cpp').read_text(), 'void Out::Free(')
code += r'''
}
int main() {
    using namespace AudioCore::AudioOut;
    Core::System system;
    Kernel::KProcess process;
    {
        auto service = std::make_unique<Service::Audio::IAudioOutManager>(system);
        auto first = Service::Audio::Open(*service, &process, 0);
        auto last = Service::Audio::Open(*service, &process, 1);
        assert(live == 1 && process.refs == 2);
        service.reset();
        assert(live == 1 && "Manager must survive the audout:u service");
        first.reset();
        assert(live == 1 && releases == 1 && process.refs == 1);
        last.reset();
        assert(live == 0 && releases == 2 && process.refs == 0);
    }
    // Normal close order must release the Manager too (no ownership cycle).
    {
        auto service = std::make_unique<Service::Audio::IAudioOutManager>(system);
        auto session = Service::Audio::Open(*service, &process, 0);
        session.reset();
        assert(live == 1 && releases == 3 && process.refs == 0);
        service.reset();
        assert(live == 0);
    }
}
'''
path = out / 'test.cpp'
path.write_text(code)
subprocess.run(['clang++-18', '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
                str(path), '-o', str(out / 'test')], check=True)
subprocess.run([str(out / 'test')], check=True)
print('PASS: audio Manager survives audout:u until last output closes; no cycle (ASan/UBSan)')
