// SPDX-License-Identifier: GPL-3.0-or-later
// Recording engine boundary for the production native draw HLE function.
#include <optional>
#include <cstdlib>
#include <stdexcept>
#include "common/scope_exit.h"
using u32=std::uint32_t;using u64=std::uint64_t;
#define LOG_INFO(...) ((void)0)
namespace Core {struct System{};}
namespace Settings {
enum class RendererBackend {Vulkan};
inline struct {struct {RendererBackend GetValue()const{return RendererBackend::Vulkan;}} renderer_backend;} values;
}
namespace VideoCommon {enum class CacheType {BufferCache};namespace Dirty {constexpr unsigned IndexBuffer=0;}}
namespace Tegra {
struct MacroEngine {
    unsigned native_hle_generation{},native_code_generation{};
    bool native_hle_sdk=true,native_execution_failed=false;
    std::vector<u32> native_code;
};
namespace Engines {
struct Maxwell3D {
    struct Regs {
        enum class ShadowRamControl {Track,Replay};
        enum class PrimitiveTopologyOverride {None};
        enum class PrimitiveTopology {Triangles};
        PrimitiveTopologyOverride topology_override{};
        struct {u64 Address()const{return 0x8000;}} const_buffer;
        bool IsShaderConfigEnabled(size_t)const{return false;}
    } regs;
    struct {Regs::ShadowRamControl shadow_ram_control{};} shadow_state;
    enum class EngineHint {None,OnHLEMacro};EngineHint engine_state{};
    enum class HLEReplacementAttributeType {BaseVertex,BaseInstance};
    std::vector<std::pair<u32,HLEReplacementAttributeType>> replace_table;
    struct Binding {bool enabled=true;u64 address=0x8000;u32 size=0x648;};
    struct Stage {std::array<Binding,1> const_buffers;};
    struct {std::array<Stage,5> shader_stages;} state;
    struct {std::array<bool,1> flags{};} dirty;
    std::vector<u32> params;
    Machine output;
    unsigned snapshots{},draw_calls{};
    bool throw_draw{};
    struct Memory {
        bool IsMemoryDirty(u64,u64,VideoCommon::CacheType)const{return false;}
        bool IsFullyMappedRange(u64,u64)const{return true;}
        bool IsContinuousRange(u64,u64)const{return true;}
        std::optional<u64> GpuToCpuAddress(u64 addr)const{return addr;}
    } memory;
    bool AnyParametersDirty()const{return true;}
    u64 GetMacroAddress(size_t i)const{return i ? 0x3000+(i-1)*4 : 0x2000;}
    Memory& GetMemoryManager(){return memory;}
    size_t EstimateIndexBufferSize()const{return 1024;}
    bool SnapshotNativeDrawShadow(u64 addr,u32 topology){assert(addr==0x3000 && topology==4);++snapshots;return true;}
    void CallMethod(Core::System&,u32 method,u32 value,bool){output.Emit(method,value);}
    void SetHLEReplacementAttributeType(u32 bank,u32 offset,HLEReplacementAttributeType type){assert(bank==0);replace_table.emplace_back(offset,type);}
    struct DrawManager {
        struct Indirect {
            bool is_byte_count{},is_indexed{},include_count{};
            u64 count_start_address{},indirect_start_address{},buffer_size{};
            u32 max_draw_counts{},stride{};
            bool operator==(const Indirect&)const=default;
        } indirect_state;
        enum class DrawMode {General};
        struct {DrawMode draw_mode{};u32 instance_count{};bool draw_indexed{};} draw_state;
        void DrawIndexedIndirect(Maxwell3D& m,Regs::PrimitiveTopology topology,u32 first,u32 capacity) {
            assert(topology==Regs::PrimitiveTopology::Triangles && first==0 && capacity==1024);
            assert(m.engine_state==EngineHint::OnHLEMacro && m.dirty.flags[0] && m.snapshots==1);
            assert(m.replace_table.size()==2 && m.replace_table[0].first==0x640 && m.replace_table[1].first==0x644);
            assert(m.replace_table[0].second==HLEReplacementAttributeType::BaseVertex && m.replace_table[1].second==HLEReplacementAttributeType::BaseInstance);
            const auto& s=indirect_state;
            assert(!s.is_byte_count && s.is_indexed && !s.include_count && !s.count_start_address);
            assert(s.indirect_start_address==0x3000 && s.buffer_size==20 && s.max_draw_counts==1 && s.stride==20);
            ++m.draw_calls;
            if(m.throw_draw)throw std::runtime_error("recording backend failure");
            // Decode the recorded Vulkan indexed indirect command from guest memory.
            const auto offset=(s.indirect_start_address-0x3000)/4+1;
            const auto* words=m.params.data()+offset;
            if(words[0])for(u32 i=0;i<words[1];++i)
                m.output.draws.push_back({words[0],words[2],words[3],words[4],i});
        }
    } draw_manager;
};
}
}
#include "production-native-draw-hle.inc"
Machine RunProduction(std::span<const W> code,const std::vector<W>& params) {
    Core::System system;Tegra::MacroEngine engine;engine.native_code.assign(code.begin(),code.end());
    Tegra::Engines::Maxwell3D maxwell;maxwell.params=params;
    // A successful SDK recognition is cached; the exact entry is still validated.
    const auto prior=maxwell.draw_manager.indirect_state;
    assert(Tegra::NativeDrawHle::TryExecute(system,engine,maxwell,Hle::Entry,params));
    assert(maxwell.draw_calls==1 && maxwell.replace_table.empty());
    assert(maxwell.engine_state==Tegra::Engines::Maxwell3D::EngineHint::None);
    assert(maxwell.draw_manager.indirect_state==prior);
    return maxwell.output;
}
