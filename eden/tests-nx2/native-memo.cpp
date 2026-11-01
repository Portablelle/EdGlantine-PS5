// SPDX-License-Identifier: GPL-3.0-or-later
#include <cassert>
#include <stdexcept>
#include <cstdio>
#include "video_core/native_draw_memo.h"
#include "video_core/native_resource_memo.h"

template<class Table, class Key>
void Check(const Key& first, const Key& collision) {
    unsigned loads=0;
    auto load=[&]{return ++loads;};
    Table table;
    assert(table.Get(first,load)==1);
    assert(table.Get(first,load)==1 && loads==1);
    try {
        table.Get(collision,[]{throw std::runtime_error("loader failure");return 0u;});
        assert(false);
    } catch(const std::runtime_error&) {}
    assert(table.Get(first,load)==1 && loads==1);
    assert(table.Get(collision,load)==2);
    assert(table.Get(first,load)==3);
}
int main() {
    namespace D=VideoCommon::NativeDrawMemo;
    namespace R=VideoCommon::NativeResourceMemo;
    // One-slot tables force collisions independently of hash policy.
    Check<D::Table<unsigned,0,1>>(uint64_t{4},uint64_t{8});
    Check<D::Table<unsigned,1,1>>(uint64_t{1},uint64_t{2});
    Check<R::Table<R::TableKey,unsigned,0,1>>(R::TableKey{4,8},R::TableKey{4,16});
    Check<R::Table<R::SampledKey,unsigned,1,1>>(R::SampledKey{1,2,3,4},R::SampledKey{1,2,3,5});
    for(unsigned i=0;i<2;++i) {
        assert(D::statistics[i].requests==6 && D::statistics[i].hits==2);
        assert(R::statistics[i].requests==6 && R::statistics[i].hits==2);
    }
    {D::Table<unsigned,0,1> next;assert(next.Get(4,[]{return 99u;})==99);}
    assert(D::statistics[0].requests==7 && D::statistics[0].hits==2);
    std::puts("NATIVE_MEMO_OK: full-key collisions, exception safety, independent counters, fresh lifetime");
}
