"""UB-027: execute the HasTimestamp publication blocks extracted from CounterReport.

Usage: python3 tests-nx2/check-gpu-segment-timestamps.py [--source-only] [SOURCE_DIR]
Default: Linux/dedie C++ harness includes the production clock and publication blocks.
--source-only: evaluate the actual publication RHS with a faithful clock/backend model;
no compiler or Vulkan device. Main's GetTicks RHS executes and fails on VALUE first,
without reading the new header. The helper model is checked against independent numbers
from nxnative t_counter_clock.m, not used as the oracle for the C++ harness.
"""
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile

args = [a for a in sys.argv[1:] if not a.startswith('--')]
source_only = '--source-only' in sys.argv[1:]
root = Path(__file__).resolve().parents[1]
source = Path(args[0]).resolve() if args else Path(
    (root / '.local/headless-cache').read_text().strip()) / 'source'
src = source / 'src'
query = (src / 'video_core/query_cache/query_cache.h').read_text()
method = query.split('::CounterReport(', 1)[1].split('\ntemplate <typename Traits>', 1)[0]
# Keep each complete production timestamp write through its memcpy, including tracing.
blocks = re.findall(r'u64 timestamp = ([^;]+);\n(.*?std::memcpy\(pointer_timestamp, &timestamp, sizeof\(timestamp\)\);)',
                    method, re.S)
assert len(blocks) == 2, 'expected both CounterReport long-query writes'


def compile_run(harness):
    assert platform.system() == 'Linux', 'compiled check is Linux/dedie only'
    with tempfile.TemporaryDirectory(prefix='gpu-segment-clock-') as d:
        cpp = Path(d) / 'clock.cpp'; exe = Path(d) / 'clock'
        cpp.write_text(harness)
        subprocess.run(['g++', '-std=c++20', '-Wall', '-Wextra', '-Werror', '-I', str(src),
                        str(cpp), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


# On main, compile and execute the extracted GetTicks writes BEFORE looking for a
# new helper. The failure is the bytes published to guest memory, not a missing API.
if not source_only and all(rhs == 'impl->gpu.GetTicks()' for rhs, _ in blocks):
    legacy = r'''
#include <cstdint>
#include <cstring>
#include <cstdio>
using u64 = std::uint64_t;
namespace Core::HLE::DlssTrace { void WriteWatch(const char*, void*, size_t) {} }
struct GPU { u64 GetTicks() const { return 900000; } };
struct Impl { GPU gpu; } storage;
int main() {
    auto* impl = &storage;
    u64 out{}; auto* pointer_timestamp = &out;
'''
    for rhs, tail in blocks:
        legacy += '{ u64 timestamp = ' + rhs + ';\n' + tail + r'''
        if (out != 100005) {
            std::fprintf(stderr, "CounterReport published VALUE %llu, expected 100005\n",
                         static_cast<unsigned long long>(out));
            return 1;
        }
        }
'''
    compile_run(legacy + 'return 0; }\n')

class Clock:
    def __init__(self):
        self.begin, self.epoch, self.published = 100000, 7, 0
        self.segments = [(100000, 103000), (104000, 106000)]
        self.commits = [0, 1]

    def idle(self, ns, c0):
        total = 0
        for i, k in enumerate(self.commits):
            end = self.segments[k][1]
            start = self.segments[self.commits[i + 1]][0] if i + 1 < len(self.commits) else c0
            if end and start > end and ns >= end + (start - end) // 2:
                total += start - end
        return total

    def report(self, segment, top, stamp, epoch=7, c0=109000, c1=112000,
               fallback=900000, convert=lambda ns: ns):
        ns = stamp if epoch == self.epoch else 0
        if ns and self.begin > ns and self.begin - ns > 500000:
            ns = 0
        if not ns and segment < len(self.segments):
            ns = self.segments[segment][0 if top else 1]
        if not ns:
            ns = c0 if top else c1
        if ns:
            idle = self.idle(ns, c0)
            if idle < ns:
                ns -= idle
        ticks = convert(ns) if ns else fallback
        self.published = max(self.published, ticks)
        return self.published


def delta(ticks, origin, bits, period):
    if not 0 < bits <= 64 or period <= 0:
        return 0
    mask = (1 << bits) - 1
    d = (ticks - origin) & mask
    return int(d * period) if d <= mask >> 1 else 0

# The main witness runs first: no access to a new header is needed on main.
# RHSs are taken from the real deferred and immediate publication sites, not selected
# by a header's existence. A synthetic ready ticket has two distinct GPU work times.
for rhs, _ in blocks:
    published = []
    for stamp in (100005, 104010):
        c = Clock()
        value = c.report(0, False, stamp)
        expression = rhs.replace('impl->gpu.GetTicks()', 'get_ticks()').replace(
            'Tegra::PublishReportTimestamp(timestamp_ticket, impl->gpu)', 'publish_ticket()')
        actual = eval(expression, {'__builtins__': {}}, {
            'get_ticks': lambda: 900000, 'publish_ticket': lambda: value})
        published.append(actual)
    assert published == [100005, 103010], (
        'CounterReport published VALUE', published, 'expected GPU times [100005, 103010]')
    assert published[1] - published[0] == 3005

helper = (src / 'video_core/gpu_segment_clock.h').read_text()
# Pin the modeled operations to the production bodies. The compiled mode below is
# authoritative; source-only deliberately reports that it did not compile C++.
for fragment in ('ns >= e + (s - e) / 2', 'idle += s - e', 'stamp.epoch == epoch',
                 'begin - ns > 500000', 'ns = top ? c0 : c1', 'IdleBefore(ns, c0)',
                 'std::max(published, ticks)', '(ticks - origin) & mask', 'mask >> 1'):
    assert fragment in helper, ('clock model needs review for changed production code', fragment)

c = Clock()
assert [c.idle(n, 109000) for n in (103400, 103600, 109000)] == [0, 1000, 4000]
for segment, top, stamp, expected in (
        (0, True, 100005, 100005), (0, False, 104010, 103010),
        (1, False, 105990, 104990), (4, True, 0, 105000),
        (4, True, 110000, 106000), (4, False, 0, 108000)):
    # Fresh clock permits testing report order independently of the monotonic clamp.
    assert Clock().report(segment, top, stamp) == expected
assert Clock().report(4, False, 0) - Clock().report(0, True, 100005) == 7995
c.segments[1] = (0, 0)
assert c.idle(109000, 109000) == 0
# Delayed stamp: feedback first; later GPU feedback yields a real distinct value.
c = Clock()
assert c.report(0, True, 0) == 100000
assert c.report(0, False, 102000) == 102000
# Previous pool epoch and empty TOP stale stamp take feedback, never stale values.
assert Clock().report(0, False, 1, epoch=6) == 103000
c = Clock(); c.begin = 1000000
assert c.report(0, False, 1) == 103000
# Modular hardware wrap, invalid/ambiguous delta and new pool epoch.
assert delta(5, 250, 8, 2) == 22
assert delta(249, 250, 8, 2) == 0
assert delta(5, 250, 0, 2) == 0
assert Clock().report(0, False, 999999999, epoch=6) == 103000
c = Clock()
assert [c.report(0, False, n) for n in (105000, 104000, 110000)] == [104000, 104000, 106000]
for divisor in (1, 256, 512):
    assert Clock().report(0, False, 104010, convert=lambda ns: (ns * 384 // 625) // divisor) == (103010 * 384 // 625) // divisor

backend = (src / 'video_core/renderer_vulkan/vk_guest_timestamp.inc').read_text()
assert 'VK_QUERY_RESULT_WAIT_BIT' not in backend
assert not re.search(r'\b(?:Wait|Finish|WaitIdle)\s*\(', backend)
assert 'clock.commits.push_back(0)' in backend
assert '!IsFree(b->tick)' in backend and 'ticket->epoch != b->clock.epoch' in backend
assert 'VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT, *b->pool, ticket->slot' in backend
assert 'CaptureReportTimestamp(impl->runtime, impl->gpu, has_timestamp)' in method
assert 'timestamp_ticket,' in method.split('std::function<void()> operation', 1)[1].split('] {', 1)[0]
print('PASS: both extracted CounterReport VALUE writes and clock/epoch fixtures (source model)')
if source_only:
    print('source-only: C++ harness NOT compiled or run')
    sys.exit(0)

assert platform.system() == 'Linux', 'compiled check is Linux/dedie only'
# Include the production helper; compile exactly the extracted CounterReport write blocks.
# Minimal stubs supply memory, tracing, GPU unit conversion and synthetic ready tickets.
harness = r'''
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <iostream>
#include "video_core/gpu_segment_clock.h"
void check(bool ok) { if (!ok) std::abort(); }
namespace Core::HLE::DlssTrace { void WriteWatch(const char*, void*, size_t) {} }
struct GPU {
    u64 GetTicks() const { return 900000; }
    u64 GetTimestampNs() const { return 900000; }
    u64 TimestampFromNs(u64 ns) const { return ns; }
};
struct Impl { GPU gpu; } storage;
Impl* impl = &storage;
using C = Tegra::SegmentClock;
C clock_fixture() {
    C c; c.begin = 100000; c.epoch = 7;
    c.segments = {{100000, 103000}, {104000, 106000}};
    c.commits = {0, 1}; return c;
}
'''
for i, (rhs, tail) in enumerate(blocks):
    harness += f'void publish_{i}() {{\n' + r'''
    auto c = clock_fixture();
    u64 out{}; auto* pointer_timestamp = &out;
    u64 stamp = 100005;
    Tegra::ReportTimestamp timestamp_ticket = [&](u64, const Tegra::TimestampConvert& convert) {
        return c.ReportTicks(0, false, {stamp, 7}, 109000, 112000, 900000, convert);
    };
    for (const auto expected : {u64{100005}, u64{103010}}) {
''' + 'u64 timestamp = ' + rhs + ';\n' + tail + r'''
        check(out == expected); stamp = 104010;
    }
}
'''
harness += r'''
int main() {
    publish_0(); publish_1();
    auto c = clock_fixture();
    check(c.IdleBefore(103400, 109000) == 0);
    check(c.IdleBefore(103600, 109000) == 1000);
    check(c.IdleBefore(109000, 109000) == 4000);
    auto report = [](C& c, size_t seg, bool top, u64 stamp, u64 epoch = 7) {
        return c.ReportTicks(seg, top, {stamp, epoch}, 109000, 112000, 900000,
                             [](u64 n) { return n; });
    };
    check(report(c, 0, true, 100005) == 100005);
    check(report(c, 0, false, 104010) == 103010);
    check(report(c, 1, false, 105990) == 104990);
    check(report(c, 4, true, 110000) == 106000);
    check(report(c, 4, false, 0) == 108000);
    auto first = clock_fixture(); auto last = clock_fixture();
    check(report(last, 4, false, 0) - report(first, 0, true, 100005) == 7995);
    check(report(c, 0, true, 100005) == 108000); // monotonic after gap removal
    c = clock_fixture(); c.segments[1] = {};
    check(c.IdleBefore(109000, 109000) == 0);
    c = clock_fixture();
    check(report(c, 0, true, 0) == 100000); // not ready: segment feedback
    check(report(c, 0, false, 102000) == 102000); // late stamp
    c = clock_fixture();
    check(report(c, 0, false, 999999999, 6) == 103000);
    c = clock_fixture(); c.begin = 1000000;
    check(report(c, 0, false, 1) == 103000); // >0.5ms stale TOP
    c = {}; check(report(c, 4, false, 0) == 112000); // c1 fallback
    c = {}; check(c.ReportTicks(4, false, {}, 0, 0, 900000,
                                [](u64 n) { return n; }) == 900000);
    check(C::DeltaNs(5, 250, 8, 2) == 22);
    check(C::DeltaNs(249, 250, 8, 2) == 0);
    check(C::DeltaNs(5, 250, 0, 2) == 0);
    for (u64 divisor : {1, 256, 512}) {
        c = clock_fixture();
        check(c.ReportTicks(0, false, {104010, 7}, 109000, 112000, 0,
              [=](u64 ns) { return (ns * 384 / 625) / divisor; }) == (103010 * 384 / 625) / divisor);
    }
}
'''
compile_run(harness)
print('PASS: compiled production clock and both CounterReport writes')
