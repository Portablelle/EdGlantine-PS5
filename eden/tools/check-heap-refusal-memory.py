#!/usr/bin/env python3
"""Check real refusal snapshots, klog/crash formatting and periodic GPU accounting without a PS5."""
from pathlib import Path
import argparse
import os
import shutil
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('engine', type=Path, help='Eden source tree with layer 99ze applied')
parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
parser.add_argument('--source-only', action='store_true')
args = parser.parse_args()
root = args.repo
memory = (root/'src/memory_pages.cpp').read_text()
heap = (root/'headless/heap_arenas.inc').read_text()
crash = (root/'headless/crash_report.cpp').read_text()
main = (root/'headless/main.cpp').read_text()
perf = (root/'headless/performance.cpp').read_text()
device = (args.engine/'src/video_core/vulkan_common/vulkan_device.cpp').read_text()


def function(source, signature):
    assert signature in source, 'Missing production diagnostic: ' + signature
    start = source.index(signature)
    at = source.index('{', start)
    depth, end = 1, at+1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]+'\n'


record = function(memory, 'extern "C" void eden_direct_memory_failure_record(')
read = function(memory, 'extern "C" void eden_direct_memory_failure_read(')
klog = function(heap, 'static void eden_heap_memory_refused(')
limiter = function(heap, 'static void eden_heap_grow_refused(const char *line) {')
assert 'eden_direct_memory_failure_record();' in klog
assert 'eden_heap_grow_refused(line);' in klog
assert 'sceKernelDebugOutText' not in klog
report = function(crash, 'void PutHeapRefusalMemory(')
pages = function(memory, 'void* AllocatePagesAt(')
assert 'fprintf' not in pages and pages.count('Note(line)') >= 3
assert pages.count('eden_direct_memory_failure_record();') == 2
assert 'eden_heap_memory_refused(' in function(heap, 'static void *eden_heap_large_allocate(')
assert 'eden_heap_memory_refused(' in function(heap, 'static int eden_heap_grow(')
assert 'PutHeapRefusalMemory();' in function(crash, 'void Compose(')
assert 'EDEN_HEAP_GROW refused: %s (free=%lldMiB largest_free=%lldMiB)' in klog
assert 'gpu_bytes=%llu' in function(perf, 'void ReportSessionMemory(')
assert 'eden_vulkan_memory_bytes ? eden_vulkan_memory_bytes() : 0' in perf
runtime = main[main.index('std::jthread runtime_control'):main.index('std::jthread input_worker')]
assert 'ReportSessionMemory("play", 0)' in runtime
assert runtime.count('std::chrono::seconds(10)') == 2
assert '.pDeviceMemoryCallbacks = &memory_callbacks' in device
# The callback definitions and atomic getter are production code; only Vulkan types are shimmed.
a = device.index('std::atomic<u64> vma_device_bytes')
b = device.index('\n}\nextern \"C\" u64 eden_vulkan_memory_bytes', a)
callbacks = device[a:b] + function(device, 'extern "C" u64 eden_vulkan_memory_bytes(')
a = memory.index('static_assert(std::atomic<std::int64_t>')
b = memory.index('\n}', a)
state = memory[a:b]
text = crash[crash.index('template <std::size_t N>'):crash.index('// One report per process:')]
if args.source_only:
    print('PASS: refusal snapshots, real formatters, malloc-safe logging, 10 s sampling and VMA callback integration (source only)')
    raise SystemExit(0)
compiler = os.environ.get('CXX') or next((c for c in ('clang++-18','clang++','g++') if shutil.which(c)), None)
assert compiler, 'No host C++ compiler; run on the build server or use --source-only for extraction only'
fixture = r'''
#include <atomic>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <string>
using u64=std::uint64_t; using u32=std::uint32_t;
using VmaAllocator=void*; using VkDeviceMemory=u64; using VkDeviceSize=u64;
#define VKAPI_PTR
using Callback=void(*)(VmaAllocator,u32,VkDeviceMemory,VkDeviceSize,void*);
struct VmaDeviceMemoryCallbacks {Callback pfnAllocate,pfnFree;void* pUserData;};
static std::int64_t live_free=std::int64_t{212}<<20;
static std::size_t live_largest=std::size_t{130}<<20;
extern "C" void eden_direct_memory_free(std::int64_t* free_bytes,std::size_t* largest) noexcept {
    *free_bytes=live_free; *largest=live_largest;
}
std::string notice;
unsigned notices=0;
int sceKernelDebugOutText(int,const char* line) {++notices;notice=line;return 0;}
using std::atomic_uint;
using std::atomic_fetch_add_explicit;
using std::memory_order_relaxed;
bool InCode(std::uint64_t){return false;}
std::uintptr_t CodeStart(){return 0;}
'''
test = r'''
int main(){
    std::int64_t free_bytes=0;std::size_t largest=0;
    eden_direct_memory_failure_read(&free_bytes,&largest);
    assert(free_bytes==-1 && largest==static_cast<std::size_t>(-1));
    eden_heap_memory_refused("the console has no memory for a new piece");
    assert(notice=="EDEN_HEAP_GROW refused: the console has no memory for a new piece (free=212MiB largest_free=130MiB)\n");
    live_free=std::int64_t{999}<<20;live_largest=std::size_t{998}<<20;
    report.Clear();PutHeapRefusalMemory();
    assert(std::string(report.data,report.size)==" (free 212 MiB, largest 130 MiB at the time)");
    // Both refusal paths share eight klog lines; snapshots continue after the limit.
    eden_heap_grow_refused("other refusal\n");
    for(int i=0;i<12;++i){
        live_free=std::int64_t{200+i}<<20;live_largest=std::size_t(100+i)<<20;
        eden_heap_memory_refused("the console has no memory for a large block");
    }
    assert(notices==8);
    eden_direct_memory_failure_read(&free_bytes,&largest);
    assert(free_bytes==(std::int64_t{211}<<20) && largest==(std::size_t{111}<<20));
    live_free=-1;live_largest=static_cast<std::size_t>(-1);
    eden_direct_memory_failure_record();report.Clear();PutHeapRefusalMemory();
    assert(std::string(report.data,report.size)==" (free unknown MiB, largest unknown MiB at the time)");
    memory_callbacks.pfnAllocate(nullptr,0,1,64u<<20,nullptr);
    memory_callbacks.pfnAllocate(nullptr,1,2,144u<<20,nullptr);
    assert(eden_vulkan_memory_bytes()==(208u<<20));
    memory_callbacks.pfnFree(nullptr,0,1,64u<<20,nullptr);
    assert(eden_vulkan_memory_bytes()==(144u<<20));
    memory_callbacks.pfnFree(nullptr,1,2,144u<<20,nullptr);
    assert(eden_vulkan_memory_bytes()==0);
    std::puts("PASS: real atomic snapshots, refusal-time crash suffix, klog and VMA allocation/free accounting");
}
'''
with tempfile.TemporaryDirectory(prefix='eden-refused-') as temp:
    cpp=Path(temp)/'check.cpp';binary=Path(temp)/'check'
    cpp.write_text(fixture+state+record+read+limiter+klog+text+'Text<1024> report;\n'+report+callbacks+test)
    subprocess.run([compiler,'-std=c++20','-O1','-g','-fsanitize=address,undefined',str(cpp),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
