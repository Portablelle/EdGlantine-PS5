// SPDX-License-Identifier: GPL-3.0-or-later
#include <atomic>
#include <cassert>
#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <pthread.h>
#include <sys/stat.h>
#include "core/core.h"
#include "video_core/gpu_split.h"

static std::atomic<unsigned> creates{};
static unsigned fail_create{};
extern "C" int __real_pthread_create(pthread_t*,const pthread_attr_t*,void*(*)(void*),void*);
extern "C" int __wrap_pthread_create(pthread_t* thread,const pthread_attr_t* attr,void*(*fn)(void*),void* arg) {
    if(++creates==fail_create) return EAGAIN;
    return __real_pthread_create(thread,attr,fn,arg);
}
int main(int argc,char**argv) {
    assert(argc==2);
    setenv("EDEN_NX2_SPLIT","1",1);
    Core::System system;
    auto& split=VideoCommon::GpuSplit::Get();
    const std::string good=std::string(argv[1])+"/observer.log";
    const std::string missing=std::string(argv[1])+"/missing/observer.log";
    const auto run=[&](const char* path,unsigned failure) {
        split.Stop();split.SetIdleHook(nullptr,nullptr);creates=0;fail_create=failure;
        setenv("EDEN_NX2_SPLIT_OBSERVER_LOG",path,1);
        split.MaybeStart(system);assert(!split.Active());
        split.RequestEnable();split.MaybeStart(system);assert(split.Active());
        unsigned executed=0;
        split.Defer([&]{executed=42;});split.Drain();assert(executed==42);
        split.Stop();assert(!split.Active());
    };
    const std::string fifo=std::string(argv[1])+"/observer.fifo";
    assert(mkfifo(fifo.c_str(),0600)==0);
    run(fifo.c_str(),0); // Must not block waiting for a reader.
    run(missing.c_str(),0); // Open failure cannot prevent rendering.
    run("/dev/full",0);   // Initial write failure cannot prevent rendering.
    run(good.c_str(),2);   // Backend starts; optional observer thread creation fails.
    run(good.c_str(),0);   // Observer and backend can restart normally after failures.
    std::puts("SPLIT_OBSERVER_OPTIONAL_OK: open/write/thread failures, execution, shutdown and recovery");
}
