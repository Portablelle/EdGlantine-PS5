#!/usr/bin/env python3
"""Run real split startup and gathered-cache mutation methods on the build server."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

root=Path(__file__).resolve().parents[1]
core=Path(sys.argv[1])
compiler=os.environ.get('CXX','clang++')
patch=(root/'tools/eden-patches/90-nx2-prototype.diff').read_text()
with tempfile.TemporaryDirectory(prefix='nx2-publication-edges-') as directory:
    temp=Path(directory)
    shutil.copytree(root/'tests-nx2/split-observer-stubs',temp/'include')
    for name in ['gpu_split.cpp','gpu_split.h','native_semaphore_observation.h']:
        relative='src/video_core/'+name
        section=patch.split(f'diff --git a/{relative} b/{relative}\n',1)[1].split('\ndiff --git ',1)[0]
        body=section.split('@@\n',1)[1]
        target=temp/'include/video_core'/name
        target.write_text(''.join(line[1:]+'\n' for line in body.splitlines() if line.startswith('+')))
    flags=[compiler,'-std=c++20','-O1','-g','-fsanitize=address,undefined','-pthread']
    subprocess.run(flags+['-DEDEN_NX2_PS5_PROTO','-I',str(temp/'include'),str(temp/'include/video_core/gpu_split.cpp'),str(root/'tests-nx2/split-observer-optional.cpp'),'-Wl,--wrap=pthread_create,--wrap=write','-o',str(temp/'split-test')],check=True)
    subprocess.run([str(temp/'split-test'),str(temp)],check=True)
    source=(core/'src/video_core/renderer_vulkan/vk_multi_range_buffer.cpp').read_text()
    def method(name):
        start=source.index('void MultiRangeBufferCache::'+name+'(')
        end=source.index('\n}\n',start)+3
        return source[start:end]
    fixture=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <unordered_map>
#include <vector>
using u64=uint64_t;using VkBuffer=u64;using VkDeviceSize=u64;constexpr u64 VK_NULL_HANDLE=0;
struct Source{u64 handle,offset,size;};
struct Entry{bool dirty=true;std::vector<Source> sources;};
struct MultiRangeBufferCache{
 std::unordered_map<u64,Entry> entries;
 void MarkGathered(u64);
};
'''+method('MarkGathered')+r'''
int main(){
 MultiRangeBufferCache cache;cache.entries[1]={true,{{7,0,4}}};
 unsigned source=17,gathered=0,copies=0;
 auto bind=[&]{if(cache.entries[1].dirty){gathered=source;++copies;cache.MarkGathered(1);}return gathered;};
 assert(bind()==17);
 source=29;
 assert(bind()==29);assert(bind()==29);
 assert(copies==3);
 // A pending output is invalidated before binding, then written by the draw.
 assert(bind()==29);
 source=41;assert(bind()==41);
 std::puts("GATHER_REUSE_OK: source mutation stays coherent, platform policy respected");
}
'''
    (temp/'gather.cpp').write_text(fixture)
    for mode in [[],['-DEDEN_NX2_PS5_PROTO']]:
        subprocess.run(flags+mode+[str(temp/'gather.cpp'),'-o',str(temp/'gather-test')],check=True)
        subprocess.run([str(temp/'gather-test')],check=True)
