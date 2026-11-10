"""UB-091: the split front does not send same-value draw.end (in an instance loop) or
vertex_buffer.first/count writes, which the back ignores.

Compiles the PRODUCTION Maxwell3D::FrontTrackInstanceLoop and Maxwell3D::FrontSkipsLoopWrite
(extracted from the prepared maxwell_3d.cpp by brace matching) against a fake FrontState and
register indices. The FrontWrite / FrontCallMultiMethod call sites are modelled in the harness, and
--source-only pins their production placement. Checked:
 - same-value draw.end is skipped only after a Subsequent draw.begin (instance loop), sent after First;
 - same-value vertex_buffer.first/count are skipped, index_buffer.first/count never are;
 - a changed value, skip_same off or shadow_kept false is never skipped;
 - a multi-word draw.begin tracks EVERY word (First then Subsequent, Subsequent then First/Unchanged);
 - an inline index method clears the instance loop, Replay tracks the replayed value;
 - only methods in the execution mask on the split front are filtered (non-split CallMethod is untouched).
Negative control: on main there is no FrontSkipsLoopWrite, so the harness falls back to "never
skip" and the instance-loop draw.end expectation fails by behavior. The compiled harness is
Linux/dedie-only.

Usage: check-skip-instance-loop-writes.py [--source-only] [SOURCE_DIR]   SOURCE_DIR contains src/
(default: this checkout's prepared build cache).
"""
from pathlib import Path
import platform
import re
import subprocess
import sys

args = [a for a in sys.argv[1:] if not a.startswith('--')]
source_only = '--source-only' in sys.argv[1:]
if not source_only:
    assert platform.system() == 'Linux', 'Run on the Linux build server'
root = Path(__file__).resolve().parents[1]
if args:
    source = Path(args[0]).resolve()
else:
    source = Path((root / '.local/headless-cache').read_text().strip()) / 'source'
text = (source / 'src/video_core/engines/maxwell_3d.cpp').read_text()
header = (source / 'src/video_core/engines/maxwell_3d.h').read_text()


def body(src, signature):
    start = src.index(signature)
    i = src.index('{', start)
    depth = 0
    while True:
        depth += src[i] == '{'
        depth -= src[i] == '}'
        i += 1
        if depth == 0:
            return src[start:i]


def extract(name):
    sig = f'Maxwell3D::{name}('
    if sig not in text:
        return None
    return body(text, sig).replace('Maxwell3D::', '', 1)


track = extract('FrontTrackInstanceLoop')
skips = extract('FrontSkipsLoopWrite')
have = track is not None and skips is not None

# Call-site placement in the production text (the harness models these).
write = body(text, 'void Maxwell3D::FrontWrite(')
multi = body(text, 'void Maxwell3D::FrontCallMultiMethod(')
if have:
    assert 'bool instance_loop{};' in text[text.index('struct Maxwell3D::FrontState'):]
    assert 'FrontSkipsLoopWrite' in header and 'FrontTrackInstanceLoop' in header
    shadow_end = write.index('shadow_ram_control) && FrontVerifyEnabled')
    skip_at = write.index('if (execution_mask[method] && FrontSkipsLoopWrite(fs, method, value, shadow_kept)')
    assert shadow_end < skip_at < write.index('if (!execution_mask[method])'), 'skip must sit after shadow tracking, before the mask check'
    assert 'SameValueWrites' in write[skip_at:write.index('if (!execution_mask[method])')]
    inline = multi[multi.index('inline_index_4x8.index0'):multi.index('} else {\n        // CallMethod for each word')]
    assert 'FrontTrackInstanceLoop(fs, method, 0)' in inline, 'inline index branch must clear the loop'
    loop = multi[multi.index('for (u32 i = 0; i < amount; ++i)'):]
    track_at = loop.index('FrontTrackInstanceLoop(fs, method, value)')
    assert loop.index('fs.regs[method] = value;') < track_at < loop.index('if (!execution_mask[method])'), \
        'every word must be tracked with the resolved value before the mask check'
    # The non-split CallMethod path must not be filtered.
    assert 'FrontSkipsLoopWrite' not in text.replace(skips, '').replace(write, '')

if source_only:
    if not have:
        print('MAIN: no FrontSkipsLoopWrite / FrontTrackInstanceLoop in production text')
        sys.exit(1)
    print('skip-instance-loop-writes source checks passed')
    sys.exit(0)

prod = (track + '\n' + skips) if have else 'bool FrontSkipsLoopWrite(FrontState&, u32, u32, bool) { return false; }\nvoid FrontTrackInstanceLoop(FrontState&, u32, u32) {}\n'

harness = r'''
#include <cstdio>
#include <cstdint>
#include <array>
using u32 = std::uint32_t;
struct DrawRegs { u32 begin = 10, end = 11; };
struct BufRegs { u32 first = 20, count = 21; };
struct IBufRegs { u32 first = 30, count = 31; };
struct E16 { u32 even = 40; };
struct E8 { u32 index0 = 41; };
static constexpr DrawRegs draw; static constexpr BufRegs vertex_buffer; static constexpr IBufRegs index_buffer;
static constexpr E16 inline_index_2x16; static constexpr E8 inline_index_4x8;
static constexpr u32 draw_inline_index = 42;
#define MAXWELL3D_REG_INDEX(x) (x)
struct FrontState {
    std::array<u32, 64> regs{}, shadow{};
    bool skip_same = true;
    bool instance_loop = false;
    bool replay = false;
};
''' + prod + r'''
static int fails = 0;
#define CHECK(c) do { if (!(c)) { std::printf("FAIL line %d: %s\n", __LINE__, #c); ++fails; } } while (0)

enum { First = 0, Subsequent = 1, Unchanged = 2 };
static u32 Begin(u32 id) { return id << 26; }

// FrontWrite model: the production call order (value resolved, skip decision before regs update).
static bool Write(FrontState& fs, u32 m, u32 argument, bool shadow_kept = true, bool masked = true) {
    u32 value = fs.replay ? fs.shadow[m] : argument;
    if (masked && FrontSkipsLoopWrite(fs, m, value, shadow_kept)) return false; // not sent
    fs.regs[m] = value;
    return true; // sent
}
// FrontCallMultiMethod model: inline branch clears the loop, otherwise every word is tracked.
static void Multi(FrontState& fs, u32 m, const u32* words, u32 n) {
    if (m == draw_inline_index || m == inline_index_2x16.even || m == inline_index_4x8.index0) {
        FrontTrackInstanceLoop(fs, m, 0);
        return;
    }
    for (u32 i = 0; i < n; ++i) {
        u32 value = fs.replay ? fs.shadow[m] : words[i];
        fs.regs[m] = value;
        FrontTrackInstanceLoop(fs, m, value);
    }
}

int main() {
    {   // draw.end: only inside an instance loop
        FrontState fs; fs.regs[draw.end] = 0;
        CHECK(Write(fs, draw.end, 0));            // not in a loop: sent
        Write(fs, draw.begin, Begin(Subsequent)); // enter loop
        CHECK(!Write(fs, draw.end, 0));           // same value in loop: skipped
        CHECK(Write(fs, draw.end, 1));            // changed value: sent
        Write(fs, draw.begin, Begin(First));      // leave loop
        CHECK(Write(fs, draw.end, 1));            // draws: sent
        Write(fs, draw.begin, Begin(Unchanged));  // leaves flag as is (out)
        CHECK(Write(fs, draw.end, 1));
        Write(fs, draw.begin, Begin(Subsequent));
        Write(fs, draw.begin, Begin(Unchanged));  // as is (in)
        CHECK(!Write(fs, draw.end, 1));
    }
    {   // vertex_buffer same-value skipped, index_buffer never
        FrontState fs;
        fs.regs[vertex_buffer.first] = 5; fs.regs[vertex_buffer.count] = 6;
        fs.regs[index_buffer.first] = 7; fs.regs[index_buffer.count] = 8;
        CHECK(!Write(fs, vertex_buffer.first, 5));
        CHECK(!Write(fs, vertex_buffer.count, 6));
        CHECK(Write(fs, vertex_buffer.first, 9));
        CHECK(Write(fs, vertex_buffer.count, 9));
        CHECK(Write(fs, index_buffer.first, 7));
        CHECK(Write(fs, index_buffer.count, 8));
    }
    {   // never skipped: skip_same off, shadow_kept false
        FrontState fs; fs.instance_loop = true; fs.regs[draw.end] = 0; fs.regs[vertex_buffer.count] = 3;
        CHECK(!Write(fs, draw.end, 0));
        fs.skip_same = false;
        CHECK(Write(fs, draw.end, 0));
        CHECK(Write(fs, vertex_buffer.count, 3));
        fs.skip_same = true;
        CHECK(Write(fs, draw.end, 0, false));
        CHECK(Write(fs, vertex_buffer.count, 3, false));
        CHECK(!Write(fs, vertex_buffer.count, 3, true, true));
        // not executable methods keep the existing path, not this filter
        CHECK(Write(fs, draw.end, 0, true, false));
    }
    {   // multi-word draw.begin: every word tracked
        FrontState fs; fs.regs[draw.end] = 0;
        u32 a[] = {Begin(First), Begin(Subsequent)};
        Multi(fs, draw.begin, a, 2);
        CHECK(!Write(fs, draw.end, 0));           // ends in the loop
        u32 b[] = {Begin(Subsequent), Begin(First)};
        Multi(fs, draw.begin, b, 2);
        CHECK(Write(fs, draw.end, 0));            // ends out of the loop
        u32 c[] = {Begin(First), Begin(Unchanged)};
        Multi(fs, draw.begin, c, 2);
        CHECK(Write(fs, draw.end, 0));            // [First, Unchanged] leaves the loop
        Write(fs, draw.begin, Begin(Subsequent));
        u32 d[] = {Begin(First), Begin(Unchanged)};
        Multi(fs, draw.begin, d, 2);
        CHECK(Write(fs, draw.end, 0));
    }
    {   // inline index methods clear the loop
        const u32 methods[] = {draw_inline_index, inline_index_2x16.even, inline_index_4x8.index0};
        for (u32 m : methods) {
            FrontState fs; fs.regs[draw.end] = 0;
            Write(fs, draw.begin, Begin(Subsequent));
            CHECK(!Write(fs, draw.end, 0));
            u32 w[] = {1};
            Multi(fs, m, w, 1);
            CHECK(Write(fs, draw.end, 0));
            Write(fs, draw.begin, Begin(Subsequent));
            Write(fs, m, 1);
            CHECK(Write(fs, draw.end, 0));
        }
    }
    {   // Replay: the replayed value drives the flag, not the argument
        FrontState fs; fs.regs[draw.end] = 0; fs.replay = true;
        fs.shadow[draw.begin] = Begin(Subsequent);
        Write(fs, draw.begin, Begin(First));      // argument says First, replay says Subsequent
        CHECK(!Write(fs, draw.end, 0 /*arg*/ ));  // shadow[draw.end]==0 replayed: same value in loop
        fs.shadow[draw.begin] = Begin(First);
        u32 w[] = {Begin(Subsequent)};
        Multi(fs, draw.begin, w, 1);              // replayed First wins
        CHECK(Write(fs, draw.end, 0));
    }
    if (fails) return 1;
    std::puts("skip-instance-loop-writes behavior checks passed");
    return 0;
}
'''
out = root / 'build/nx2-tests'
out.mkdir(parents=True, exist_ok=True)
src = out / 'skip-instance-loop-writes.cpp'
src.write_text(harness)
exe = out / 'skip-instance-loop-writes'
subprocess.run(['clang++-18', '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined', str(src), '-o', str(exe)], check=True)
sys.exit(subprocess.run([str(exe)]).returncode)
