"""Linux/build server: real guest fault handler and crash-report OOM formatting, with shims."""
from pathlib import Path
import platform
import subprocess
import tempfile

assert platform.system() == 'Linux', 'Run on the Linux build server'
root = Path(__file__).resolve().parents[1]
service = (root / 'src/guest_memory_service.inc').read_text()
memory = (root / 'src/memory_pages.cpp').read_text()
crash = (root / 'headless/crash_report.cpp').read_text()
header = (root / 'headless/crash_report.h').read_text()


def function(source, signature):
    try:
        start = source.index(signature)
        opening = source.index('{', start)
        depth = 1
        end = opening + 1
        while depth:
            depth += (source[end] == '{') - (source[end] == '}')
            end += 1
        return source[start:end] + '\n'
    except (ValueError, IndexError) as error:
        raise AssertionError('Missing real OOM-report code: ' + signature) from error


# Fail clearly on main, before attempting to build a fixture without the diagnostic.
snapshot = function(service, 'extern "C" bool eden_guest_memory_oom(')
handler = function(service, 'bool HandleGuestWriteFault(')
formatter = function(crash, 'void PutGuestMemoryOom(')
assert 'PutGuestMemoryOom();' in function(crash, 'void Compose(')
declaration_start = header.index('extern "C" bool eden_guest_memory_oom(')
declaration = header[declaration_start:header.index(';', declaration_start) + 1]
counters = service[service.index('struct Counters {'):service.index('bool LockSlot(')]
text = crash[crash.index('template <std::size_t N>'):crash.index('// One report per process:')]
region = memory[memory.index('struct DirectMemoryRegion {'):memory.index('std::int32_t sceKernelDirectMemoryQuery')]
pool = function(memory, 'extern "C" void eden_direct_memory_free(')
notice_start = service.index('struct OomNoticeLine {')
notice = service[notice_start:service.index('} // namespace', notice_start)]
assert 'eden_direct_memory_free(' in function(service, 'void FormatOomNotice(')
assert 'eden_direct_memory_free(' in formatter
assert 'ReportGuestMemoryOomGrowth(last_failures);' in function(service, 'void ScannerLoop(')

fixture = r'''
#include <atomic>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <initializer_list>
#include <string_view>
#include <string>
constexpr std::size_t SparseSlot = 2 * 1024 * 1024;
enum { SlotZero, SlotOwn, SlotShared, SlotFine };
struct SparseRange {
    std::atomic<std::uintptr_t> begin{SparseSlot};
    unsigned state = SlotZero;
    bool locked = false;
} range;
std::atomic<std::uintptr_t> probe_expected{0};
std::atomic<bool> probe_mismatch{false};
std::atomic<std::size_t> guest_committed{0};
bool fail_promote = false;
unsigned notes = 0, reports = 0, queries = 0;
std::string last_notice, last_report;
SparseRange* WriteRangeOf(std::uintptr_t address) {
    return address >= range.begin && address < range.begin + SparseSlot ? &range : nullptr;
}
bool LockSlot(SparseRange& r, std::size_t slot, bool) {
    assert(slot == 0 && !r.locked); r.locked = true; return false;
}
unsigned SlotState(SparseRange& r, std::size_t) { return r.state; }
void UnlockSlot(SparseRange& r, std::size_t, unsigned state) {
    assert(r.locked); r.state = state; r.locked = false;
}
bool PromoteZero(SparseRange&, std::size_t) { return !fail_promote; }
bool PromoteShared(SparseRange&, std::size_t) { return !fail_promote; }
bool PromoteFine(SparseRange&, std::size_t) { return !fail_promote; }
void Note(const char* text) { ++notes; last_notice = text; }
void Report(const char* text) { ++reports; last_report = text; }
bool InCode(std::uint64_t) { return false; }
std::uintptr_t CodeStart() { return 0; }
'''

kernel = r'''
int query_mode = 0;
std::int64_t sceKernelGetDirectMemorySize() { return 16 * SparseSlot; }
std::int32_t sceKernelDirectMemoryQuery(std::int64_t offset, int flag,
                                      DirectMemoryRegion* r, std::size_t size) {
    ++queries;
    assert(flag == 1 && size == sizeof(*r));
    if (query_mode == 1) return -1; // Unreadable walk.
    if (query_mode == 2) { *r = {offset, offset, 0}; return 0; } // Invalid region.
    if (query_mode == 3) { *r = {offset, offset + 1, 0}; return 0; } // Walk bound.
    // 32 MiB total, 6 MiB allocated in two regions, three separated free gaps.
    if (offset == 0) { *r = {2 * SparseSlot, 4 * SparseSlot, 0}; return 0; }
    if (offset == 4 * SparseSlot) { *r = {8 * SparseSlot, 9 * SparseSlot, 0}; return 0; }
    assert(offset == 9 * SparseSlot);
    return -1;
}
std::int32_t sceKernelAvailableDirectMemorySize(std::int64_t, std::int64_t,
    std::size_t, std::int64_t* start, std::size_t* largest) {
    ++queries; if (query_mode == 1) return -1; *start = 9 * SparseSlot; *largest = 7 * SparseSlot; return 0;
}
'''

main = r'''
int main() {
    auto* address = reinterpret_cast<void*>(SparseSlot);
    auto output = [] { return std::string_view(report.data, report.size); };
    auto check_empty = [&] {
        report.Clear(); report.Put("unchanged"); PutGuestMemoryOom();
        assert(output() == "unchanged");
    };
    check_empty(); assert(queries == 0);
    assert(!HandleGuestWriteFault(nullptr));
    assert(HandleGuestWriteFault(address));
    check_empty(); assert(notes == 0);
    guest_committed.store(3 * SparseSlot);
    counters.reserve_used.store(16);
    fail_promote = true;
    for (unsigned state : {SlotZero, SlotShared, SlotFine}) {
        range.state = state;
        assert(!HandleGuestWriteFault(address));
        assert(!range.locked && range.state == state);
    }
    assert(notes == 3); // Every refused promotion emits a kernel notice.
    assert(last_notice.find("failures=3 held=6MiB") != std::string::npos);
#ifdef PS5_NATIVE
    assert(queries == 12); // Fresh pool walk for each of the three refusals.
    assert(last_notice.find("free=26MiB largest_free=14MiB") != std::string::npos);
#else
    assert(last_notice.find("free=unknownMiB largest_free=unknownMiB") != std::string::npos);
#endif
    // Real scanner helper: report once per observed growth, never for unchanged counts.
    std::uint64_t last_failures = 0;
    ReportGuestMemoryOomGrowth(last_failures);
    assert(reports == 1 && last_failures == 3 && last_report == last_notice);
    ReportGuestMemoryOomGrowth(last_failures);
    assert(reports == 1);
    assert(!HandleGuestWriteFault(address));
    assert(notes == 4);
    ReportGuestMemoryOomGrowth(last_failures);
    assert(reports == 2 && last_failures == 4);
    assert(last_report == last_notice);
    std::uint64_t held = 0, failures = 0, reserve = 0, promotions = 0, faults = 0;
    assert(eden_guest_memory_oom(&held, &failures, &reserve, &promotions, &faults));
    assert(held == 3 * SparseSlot && failures == 4 && reserve == 16);
    assert(promotions == 1 && faults == 5);
    report.Clear(); PutGuestMemoryOom();
    assert(output().find("reason: game memory exhausted") != std::string_view::npos);
    assert(output().find("held/guest_committed 6 MiB, failures=4 reserve_used=16 promotions=1 faults=5")
           != std::string_view::npos);
#ifdef PS5_NATIVE
    assert(output().find("direct memory: total free 26 MiB, largest free block 14 MiB")
           != std::string_view::npos);
#endif
    std::int64_t free_bytes = 0;
    std::size_t largest = 0;
    eden_direct_memory_free(&free_bytes, &largest);
#ifdef PS5_NATIVE
    assert(free_bytes == 26 * 1024 * 1024 && largest == 14 * 1024 * 1024);
    for (int mode : {1, 2, 3}) {
        query_mode = mode;
        const unsigned before = queries;
        eden_direct_memory_free(&free_bytes, &largest);
        assert(free_bytes == -1 && queries - before <= 8193);
        if (mode == 1) assert(largest == static_cast<std::size_t>(-1));
    }
#else
    assert(free_bytes == -1 && largest == static_cast<std::size_t>(-1));
#endif
    ResetCounters();
    check_empty();
    ReportGuestMemoryOomGrowth(last_failures);
    assert(reports == 2 && last_failures == 0);
}
'''

with tempfile.TemporaryDirectory(prefix='guest-memory-oom-') as temporary:
    folder = Path(temporary)
    for ps5 in (False, True):
        source = folder / ('ps5.cpp' if ps5 else 'linux.cpp')
        source.write_text(fixture + declaration + '\n' + (region + kernel if ps5 else '') +
                          pool + counters + notice + snapshot + handler + text +
                          'Text<4096> report;\n' + formatter + main)
        binary = source.with_suffix('')
        subprocess.run(['clang++-18', '-std=c++20', '-O1', '-g',
                        '-fsanitize=address,undefined', *(['-DPS5_NATIVE'] if ps5 else []),
                        str(source), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)
print('PASS: real promotion failures, atomic snapshot, per-failure memory notices, scanner growth and conditional OOM report')
