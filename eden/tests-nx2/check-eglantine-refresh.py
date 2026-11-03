"""Production paging/fence regressions; run and compile only on dedie."""
from pathlib import Path
import platform, subprocess, sys, tempfile

assert platform.system() == 'Linux', 'Compile on dedie'
root = Path(__file__).resolve().parents[1]
scratch = Path((root / '.local/headless-cache').read_text().strip())
source = scratch / 'source/src'
boost_dirs = list((scratch / 'source/.cache/cpm/boost').glob('*/libs/*/include'))
assert boost_dirs, 'Pinned Boost headers are required'
if '--generated' in sys.argv:
    subprocess.run(['python3', 'tests-nx2/check-eglantine-performance.py', '--generated'], cwd=root, check=True)
    generated = (scratch / 'native-local/headless/vulkan_rasterizer.cpp').read_text()
    assert 'pipeline_cache.InvalidateRegions(sequences)' in generated
    # Even the optional write-coalescing path must cancel old copies before a CPU store.
    body = generated[generated.index('bool RasterizerVulkan::OnCPUWrite'):]
    body = body[:body.index('\nvoid RasterizerVulkan::')]
    assert 'GuestCacheLockOrDefer(buffer_cache.mutex)' not in body
    assert 'ExtendDeferredWrite(addr, size' not in body
    assert 'buffer_cache.OnCPUWriteAhead(page, Core::DEVICE_PAGESIZE)' in body
    assert 'buffer_cache.OnCPUWrite(page, Core::DEVICE_PAGESIZE)' not in body
    print('PASS generated CPU-write coherence and batched shader invalidation')
    sys.exit(0)

buffer_source = (source / 'video_core/buffer_cache/buffer_cache.h').read_text()
def actual_method(name):
    start = buffer_source.index('bool BufferCache<P>::'+name+'(')
    begin = buffer_source.index('{', start)
    end, depth = begin+1, 1
    while depth:
        depth += (buffer_source[end] == '{') - (buffer_source[end] == '}')
        end += 1
    return 'template<class P>\n'+buffer_source[start:end]
write_methods = actual_method('OnCPUWrite')+'\n'+actual_method('OnCPUWriteAhead')
image_header = (source / 'video_core/renderer_vulkan/vk_texture_cache.h').read_text()
a = image_header.index('    [[nodiscard]] auto MemoryBlock()')
b = image_header.index('\n    }', a) + len('\n    }')
image_memory_block = image_header[a:b]
cpp = r'''
#include <array>
#include <cassert>
#include <cstring>
#include <deque>
#include <iostream>
#include <vector>
#include "common/paged_scalar.h"
#include "common/range_sets.inc"
#include "video_core/buffer_cache/pending_fence_copies.h"
using namespace VideoCommon;
namespace Vulkan {
namespace vk {struct Image {
 struct MemoryBlock {u64 block{},block_size{},size{};};
 static inline unsigned queries=0;
 MemoryBlock GetMemoryBlock()const{++queries;return {123,1000,100};}
};}
struct ImageFixture {
 vk::Image original;
 vk::Image ImageFixture::*current_image{};
 // ACTUAL_IMAGE_MEMORY_BLOCK
};
}
struct Copy {u64 src_offset, dst_offset, size;};
template<class P>struct BufferCache {
 std::deque<std::vector<Copy>> pending_downloads;
 Common::OverlapRangeSet<u64> async_downloads;
 struct Tracker {bool modified=true;unsigned marked=0;bool IsRegionGpuModified(u64,u64){return modified;}
 void MarkRegionAsCpuModified(u64,u64){++marked;}}memory_tracker;
 bool registered=true;unsigned warmed=0;
 bool IsRegionRegistered(u64,u64){return registered;}
 void WriteMemory(u64,u64){++warmed;}
 bool OnCPUWrite(u64,u64);bool OnCPUWriteAhead(u64,u64);
};
// ACTUAL_WRITE_METHODS
int main() {
    BufferCache<int> probe;
    probe.pending_downloads={{{4096,0,16}}};probe.async_downloads.Add(4096,16);
    assert(probe.OnCPUWriteAhead(4096,16));
    assert(probe.pending_downloads[0].size()==1&&!probe.async_downloads.Empty()&&probe.warmed==0);
    assert(probe.OnCPUWrite(4096,16));
    assert(probe.pending_downloads[0].empty()&&probe.async_downloads.Empty());
    probe.memory_tracker.modified=false;
    assert(!probe.OnCPUWriteAhead(8192,16)&&probe.memory_tracker.marked==1&&probe.warmed==0);
    probe.registered=false;
    assert(!probe.OnCPUWriteAhead(12288,16)&&probe.memory_tracker.marked==1);
    Vulkan::ImageFixture null_image;
    assert(null_image.MemoryBlock().block==0&&Vulkan::vk::Image::queries==0);
    null_image.current_image=&Vulkan::ImageFixture::original;
    assert(null_image.MemoryBlock().block==123&&Vulkan::vk::Image::queries==1);
    // Physically unrelated backing for adjoining guest pages. A linear memcpy
    // at the first pointer would read poison, not the second page's bytes.
    std::array<u8,8192> left{}, right{};
    left.fill(0xee); right.fill(0xdd);
    unsigned translations = 0;
    const auto translate = [&](u64 a) -> u8* {
        ++translations;
        if(a < 4096) return left.data()+a;
        if(a < 8192) return right.data()+a-4096;
        return nullptr;
    };
    for(unsigned bytes=1; bytes<8; ++bytes) {
        const u64 address = 4096-bytes, value=0x123456789abcdef0ULL;
        Common::WritePagedScalar(address,value,translate);
        assert(Common::ReadPagedScalar<u64>(address,translate)==value);
        for(unsigned i=0;i<8;++i) {
            const u8 expected = u8(value>>(8*i));
            assert((i<bytes?left[address+i]:right[i-bytes])==expected);
        }
        assert(left[4096]==0xee); // untouched adjacent host page
    }
    right[4094]=right[4095]=0;
    translations=0;
    assert(Common::ReadPagedScalar<u32>(8190,translate)==0);
    assert(translations==2); // missing second page contributes zero bytes
    unsigned wraps=0;
    const auto end=[&](u64 address)->u8* {assert(address!=0);++wraps;return right.data();};
    Common::WritePagedScalar(~u64{0}-1,u64{77},end);
    (void)Common::ReadPagedScalar<u64>(~u64{0}-1,end);
    assert(wraps==2);

    // Old fence A, CPU overwrite, new fence B at the same address. Aggregate
    // counts alone let A consume B's count and publish old data (the old bug).
    std::deque<std::vector<Copy>> fences{{{100,1000,16}}};
    Common::OverlapRangeSet<u64> counts;
    counts.Add(100,16);
    DropPendingFenceCopies(104,4,fences,counts);
    assert(fences[0].size()==2);
    assert(fences[0][0].src_offset==100 && fences[0][0].size==4);
    assert(fences[0][1].src_offset==108 && fences[0][1].dst_offset==1008 && fences[0][1].size==8);
    fences.push_back({{104,2000,4}});counts.Add(104,4);
    std::array<u8,16> guest{};guest.fill(0x22);
    for(size_t fence=0;fence<fences.size();++fence) {
        for(const auto& copy:fences[fence]) {
            counts.ForEachInRange(copy.src_offset,copy.size,[&](u64 a,u64 b,s32) {
                for(u64 i=a;i<b;++i) guest[i-100]=fence?0x33:0x11;
            });
            counts.Subtract(copy.src_offset,copy.size);
        }
        if(fence==0) for(unsigned i=4;i<8;++i) assert(guest[i]==0x22);
    }
    for(unsigned i=0;i<16;++i) assert(guest[i]==(i>=4&&i<8?0x33:0x11));
    // CPU overwrites clip all fences, including prefixes and suffixes.
    fences={{{100,0,16}},{{100,100,16}}};counts.Clear();counts.Add(100,16);counts.Add(100,16);
    DropPendingFenceCopies(100,4,fences,counts);
    DropPendingFenceCopies(112,4,fences,counts);
    for(const auto& list:fences) assert(list.size()==1&&list[0].src_offset==104&&list[0].size==8);
    DropPendingFenceCopies(104,8,fences,counts);
    for(const auto& list:fences) assert(list.empty());
    bool remaining=false;counts.ForEachInRange(100,16,[&](auto,auto,auto){remaining=true;});assert(!remaining);
    // An earlier fence still owes its staged result even if a later writable
    // binding is announced but never writes. Publishing it must not retire the
    // later selection's dirty bytes (including a strict subrange).
    Common::RangeSet<u64> later, dirty;
    std::deque<Common::RangeSet<u64>> committed;
    DownloadSelectionEpochs epochs;epochs.NoteSelection(true,true);
    const u64 earlier_epoch=epochs.OldestSelection();
    epochs.NoteSelection(true,false);later.Add(104,4);dirty.Add(100,16);counts.Add(100,16);
    std::array<u8,16> earlier;earlier.fill(0x44);
    const auto publish=[&](u64 a,const u8* data,u64 n){std::memcpy(guest.data()+a-100,data,n);};
    PublishFenceCopy(100,16,earlier.data(),counts,later,committed,dirty,
                     epochs.IsCurrent(earlier_epoch),publish);
    for(u8 byte:guest)assert(byte==0x44);
    assert(!dirty.Intersects(100,4)&&dirty.Intersects(104,4)&&!dirty.Intersects(108,8));
    assert(counts.Empty());
    // A different channel can change the all-writes/preflushable selection rule.
    // An old fence publishes but cannot clear a write omitted by the new rule.
    later.Clear();epochs.NoteSelection(false,true);assert(!epochs.IsCurrent(earlier_epoch));
    dirty.Add(100,16);counts.Add(100,16);guest.fill(0);
    PublishFenceCopy(100,16,earlier.data(),counts,later,committed,dirty,false,publish);
    for(u8 byte:guest)assert(byte==0x44);assert(dirty.Intersects(100,16));
    // A fresh fence under the current rule may finally retire those bytes.
    counts.Add(100,16);earlier.fill(0x55);
    PublishFenceCopy(100,16,earlier.data(),counts,later,committed,dirty,
                     epochs.IsCurrent(epochs.OldestSelection()),publish);
    assert(dirty.Empty());for(u8 byte:guest)assert(byte==0x55);
    std::cout<<"PASS fragmented scalar memory, sparse holes, address wrap, CPU supersession, earlier fence publication and selection epochs\n";
}
'''
cpp = cpp.replace('// ACTUAL_IMAGE_MEMORY_BLOCK', image_memory_block).replace('// ACTUAL_WRITE_METHODS', write_methods)
with tempfile.TemporaryDirectory(prefix='eglantine-refresh-') as temp:
    p=Path(temp);(p/'test.cpp').write_text(cpp)
    subprocess.run(['clang++-18','-std=c++20','-O1','-g','-fsanitize=address,undefined',
                    '-I'+str(source), *['-I'+str(p) for p in boost_dirs],
                    str(p/'test.cpp'),'-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],check=True)
subprocess.run(['python3','tests-nx2/check-eglantine-performance.py'],cwd=root,check=True)
