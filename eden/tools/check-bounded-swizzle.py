#!/usr/bin/env python3
"""Host check of real block-row slicing and decoders in an Eden tree with layer 99ze applied."""
from pathlib import Path
import argparse
import os
import re
import shutil
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('engine', type=Path, help='Eden source tree with all port layers applied')
parser.add_argument('--source-only', action='store_true', help='check extraction/integration without compiling')
args = parser.parse_args()
engine = args.engine.resolve()
util = (engine / 'src/video_core/texture_cache/util.cpp').read_text()
header = (engine / 'src/video_core/texture_cache/util.h').read_text()
decoder = (engine / 'src/video_core/textures/decoders.cpp').read_text()
cache = (engine / 'src/video_core/texture_cache/texture_cache.h').read_text()


def function(source, signature):
    assert signature in source, 'Missing production code: ' + signature
    start = source.index(signature)
    at = source.index('{', start)
    depth, end = 1, at + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end] + '\n'


slices = function(util, 'template <bool swizzle>\nbool SwizzleBlockLinearSlices(')
cap = re.search(r'inline constexpr size_t MaxSwizzleScratchBytes = .*?;', header)
assert cap, 'Missing named scratch cap'
assert 'SwizzleBlockLinearSlices<true>' in function(util, 'void SwizzleBlockLinearImage(')
assert 'SwizzleBlockLinearSlices<false>' in function(util, 'boost::container::small_vector<BufferImageCopy, 16> UnswizzleImage(')
assert 'image.guest_size_bytes, &swizzle_data_buffer' not in cache, 'Whole guest image still copied first'
assert cache.count('&swizzle_data_buffer)') >= 3
# Keep all decoder bit addressing, native tiling and entry points from production, not a model.
constants = (engine / 'src/video_core/textures/decoders.h').read_text()
constants = constants[constants.index('constexpr u32 GOB_SIZE_X'):constants.index('/// Unswizzles')]
core = decoder[decoder.index('constexpr u32 NativeGobOffset'):decoder.index('template <bool TO_LINEAR, u32 BYTES_PER_PIXEL>\nvoid SwizzleSubrectImpl')]
core += function(decoder, 'template <bool TO_LINEAR>\nvoid Swizzle(')
core += function(decoder, 'void SwizzleTexture(') + function(decoder, 'void UnswizzleTexture(')
if args.source_only:
    print('PASS: real slice/decoder extraction, and callers (source only)')
    raise SystemExit(0)
compiler = os.environ.get('CXX') or next((c for c in ('clang++-18', 'clang++', 'g++') if shutil.which(c)), None)
assert compiler, 'No host C++ compiler; run on the build server or use --source-only for extraction only'
fixture = r'''
#include <algorithm>
#include <bit>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <span>
#include <vector>
#include "common/scratch_buffer.h"
using u8=std::uint8_t; using u32=std::uint32_t; using u64=std::uint64_t;
using GPUVAddr=u64;
#define ASSERT_MSG(test, ...) assert(test)
namespace Common {
template<class T> T DivCeil(T a,T b) { return a/b+(a%b!=0); }
template<class T> T DivCeilLog2(T a,u32 b) { return DivCeil(a,T{1}<<b); }
template<class T> T AlignUpLog2(T a,u32 b) { return DivCeilLog2(a,b)<<b; }
}
struct Extent3D {u32 width,height,depth;};
namespace Tegra {
struct MemoryManager {
    static constexpr GPUVAddr base=0x100000;
    std::vector<u8> data;
    bool native;
    size_t peak_read=0,peak_write=0;
    bool UsesNativeTiling() const {return native;}
    void ReadBlockUnsafe(GPUVAddr a,void* p,size_t n) {
        assert(a>=base && a-base+n<=data.size());
        peak_read=std::max(peak_read,n); std::memcpy(p,data.data()+a-base,n);
    }
    void WriteBlockUnsafe(GPUVAddr a,const void* p,size_t n) {
        assert(a>=base && a-base+n<=data.size());
        peak_write=std::max(peak_write,n); std::memcpy(data.data()+a-base,p,n);
    }
};
}
'''
main = r'''
void check(u32 width,u32 height,u32 bpp,u32 bh,u32 spacing,bool native,unsigned seed) {
    const u32 align=6-std::countr_zero(bpp)+spacing;
    const u32 rows=8U<<bh;
    const size_t row=Common::AlignUpLog2(width,align)*bpp;
    const size_t bytes=Common::DivCeil(row,size_t{64})*(size_t{512}<<bh)*Common::DivCeil(height,rows);
    std::vector<u8> linear(size_t{width}*height*bpp);
    for(size_t i=0;i<linear.size();++i)linear[i]=u8((i*37+(i>>11)+seed*71)&255);
    std::vector<u8> whole(bytes,0xa5);
    SwizzleTexture(whole,linear,bpp,width,height,1,bh,0,align,native);
    Tegra::MemoryManager gpu{{},native}; gpu.data.resize(bytes+64,0xa5);
    Common::ScratchBuffer<u8> scratch;
    assert(SwizzleBlockLinearSlices<true>(gpu,gpu.base+32,{},linear,bpp,{width,height,1},{0,bh,0},align,scratch));
    assert(std::equal(whole.begin(),whole.end(),gpu.data.begin()+32));
    std::vector<u8> expected(linear.size()),actual(linear.size());
    UnswizzleTexture(expected,whole,bpp,width,height,1,bh,0,align,native);
    assert(SwizzleBlockLinearSlices<false>(gpu,gpu.base+32,actual,{},bpp,{width,height,1},{0,bh,0},align,scratch));
    assert(actual==expected && actual==linear);
    assert(scratch.capacity()<=MaxSwizzleScratchBytes);
    assert(gpu.peak_read<=MaxSwizzleScratchBytes && gpu.peak_write<=MaxSwizzleScratchBytes);
    for(size_t i=0;i<32;++i)assert(gpu.data[i]==0xa5 && gpu.data[bytes+32+i]==0xa5);
}
int main() {
    assert(MaxSwizzleScratchBytes==16*1024*1024);
    for(bool native:{false,true})for(u32 bpp:{1U,2U,4U,8U,16U})
    for(u32 bh:{0U,1U,3U,5U})for(u32 spacing:{0U,2U})
    for(u32 level=0;level<6;++level)for(u32 layer=0;layer<3;++layer) {
        const u32 w=std::max(1U,531U>>level), h=std::max(1U,283U>>level);
        check(w,h,bpp,bh,spacing,native,level+layer*7);
        // BC1 and BC3: dimensions passed to the real slicer/decoder are 4x4 blocks.
        if(bpp==8 || bpp==16)check(Common::DivCeil(w,4U),Common::DivCeil(h,4U),bpp,bh,spacing,native,layer+level);
    }
    for(bool native:{false,true})check(6144,6144,4,4,0,native,19);
    Tegra::MemoryManager gpu{{},false}; Common::ScratchBuffer<u8> scratch;
    assert(!SwizzleBlockLinearSlices<true>(gpu,gpu.base,{},{},4,{8,8,2},{0,0,1},4,scratch));
    assert(!SwizzleBlockLinearSlices<false>(gpu,gpu.base,{},{},16,{1U<<22,8,1},{0,5,0},2,scratch));
    assert(scratch.capacity()==0 && gpu.peak_read==0);
    std::puts("PASS: real slice vs whole swizzle/unswizzle, 1/2/4/8/16-byte blocks, BC1/BC3, mips/layers, odd sizes, native tiling, 6144 squared scratch <=16 MiB");
}
'''
with tempfile.TemporaryDirectory(prefix='eden-swizzle-') as temp:
    cpp=Path(temp)/'check.cpp'; binary=Path(temp)/'check'
    cpp.write_text(fixture+constants+core+cap.group(0)+'\n'+slices+main)
    subprocess.run([compiler,'-std=c++20','-O1','-g','-fsanitize=address,undefined',
                    '-I'+str(engine/'src'),str(cpp),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
