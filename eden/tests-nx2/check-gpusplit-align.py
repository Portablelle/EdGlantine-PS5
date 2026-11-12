"""UB-182 (partial): GpuSplit's front ring cursor and back engine pointer sit on separate lines.

Usage: python3 tests-nx2/check-gpusplit-align.py [--source-only] [SOURCE_DIR]
SOURCE_DIR contains src/; defaults to the prepared headless cache.

x86 prefetchers pull 64-byte lines in pairs. The back writes back_engine on every engine switch;
next to the front's ring cursor (write_position) it made the front miss the cache on almost
every ring write. Both members must be alignas(128), and a layout model of the private members
from write_position through back_engine must put them on different 128-byte lines.
The model is read from the production class body (no compilation, so --source-only is the
whole test).
"""
from pathlib import Path
import re
import sys

args = [a for a in sys.argv[1:] if not a.startswith('--')]
root = Path(__file__).resolve().parents[1]
source = Path(args[0]).resolve() if args else Path(
    (root / '.local/headless-cache').read_text().strip()) / 'source'
text = (source / 'src/video_core/gpu_split.h').read_text()

LINE = 128
SIZES = {'u64': 8, 'size_t': 8, 'bool': 1, 'u32': 4}
failures = []


def check(condition, message):
    if not condition:
        failures.append(message)


def block_end(text, open_brace):
    depth, i = 1, open_brace + 1
    while depth:
        depth += (text[i] == '{') - (text[i] == '}')
        i += 1
    return i


start = text.index('class GpuSplit {')
body = text[text.index('{', start):block_end(text, text.index('{', start))]
body = re.sub(r'//[^\n]*', '', body)
private = body[body.index('private:'):]

# Declarations of the private section, split on ';' outside initializer braces.
members, depth, current = [], 0, ''
for ch in private:
    current += ch
    depth += (ch == '{') - (ch == '}')
    if ch == ';' and depth == 0:
        members.append(current.strip())
        current = ''


def declaration(name):
    for m in members:
        if re.search(rf'\b{name}\s*\{{\}}\s*;$', m):
            return m
    return None


def layout(first, last):
    """Offsets of the data members from `first` through `last` (alignas honoured)."""
    offsets, offset, active = {}, 0, False
    for m in members:
        m = re.sub(r'\s+', ' ', m)
        mm = re.search(r'\(\*(\w+)\)', m) or re.search(r'(\w+)\s*(?:\{[^;]*\})?\s*;$', m)
        if not mm or 'static' in m or ('(' in re.sub(r'alignas\(\d+\)', '', m) and '(*' not in m):
            continue
        name = mm.group(1)
        if name == first:
            active = True
        if not active:
            continue
        align_match = re.search(r'alignas\((\d+)\)', m)
        if '(*' in m or '*' in m:
            size = 8
        else:
            ty = re.sub(r'alignas\(\d+\)|\{.*', '', m).strip().rsplit(' ', 1)[0].strip()
            ty = ty.replace('std::', '')
            if ty not in SIZES:
                failures.append(f'layout model: unknown type {ty!r} for {name}')
                size = 8
            else:
                size = SIZES[ty]
        align = max(size, int(align_match.group(1)) if align_match else 1)
        offset = (offset + align - 1) // align * align
        offsets[name] = (offset, align)
        offset += size
        if name == last:
            break
    return offsets


write_decl = declaration('write_position')
back_decl = declaration('back_engine')
check(write_decl is not None, 'write_position declaration not found')
check(back_decl is not None, 'back_engine declaration not found')
check(write_decl and re.match(r'alignas\(128\)\s+u64\s+write_position\b', write_decl),
      f'write_position is not declared alignas(128): {write_decl!r}')
check(back_decl and re.match(r'alignas\(128\)\s+Tegra::Engines::EngineInterface\*\s*back_engine\b',
                             back_decl),
      f'back_engine is not declared alignas(128): {back_decl!r}')

offsets = layout('write_position', 'back_engine')
if 'write_position' in offsets and 'back_engine' in offsets:
    # write_position is the first member of the model: place it at a 128-byte boundary only when
    # the declaration demands it; otherwise its address is arbitrary (modelled as 8-byte aligned).
    w, w_align = offsets['write_position']
    b, _ = offsets['back_engine']
    check(w_align >= LINE, f'write_position alignment is {w_align}, not {LINE}')
    check(w // LINE != b // LINE,
          f'write_position (offset {w}) and back_engine (offset {b}) share a {LINE}-byte line')
    check(b % LINE == 0, f'back_engine offset {b} is not {LINE}-byte aligned')
    front = [n for n, (o, _) in offsets.items() if n != 'back_engine' and o // LINE == b // LINE]
    check(not front, f'back_engine shares its {LINE}-byte line with front fields: {front}')
else:
    check(False, f'layout model incomplete: {sorted(offsets)}')

if failures:
    print('UB-182 GpuSplit cache-line alignment: FAIL')
    for f in failures:
        print('  ' + f)
    sys.exit(1)
print('UB-182 GpuSplit cache-line alignment: PASS')
