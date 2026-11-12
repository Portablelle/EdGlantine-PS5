"""UB-178: page table caches that survive unrelated map changes, walk ahead, and a covered range
in UsageTracker.

Usage: python3 tests-nx2/check-oot-pagetable-cache.py [--source-only] [SOURCE_DIR]
SOURCE_DIR contains src/; defaults to the prepared headless cache.

Ocarina of Time maps and unmaps small ranges several times a second while native programs bind
hundreds of pointers into the same few multi-megabyte runs. Main dropped every
MaxContinuousRange answer on any map_serial bump, walked only the size asked (so a later bind of
another size or start into the same run walked again), recomputed GetMemoryLayoutSize under the
lock on every call, and tracked a sub-range of the largest bound pool page by page again.

Both modes run the same model (no compiler needed): a page table, a kind map and the map serial
are simulated in Python, and the production functions are replayed with their conditions,
declarations, stores and returns read from the production text (memory_manager.cpp/.h and
usage_tracker.h): the serial bump of PageTableOp/BigPageTableOp (NoteMapChange or a bare
fetch_add), the ops Unmap calls, MapChangedSince, the lookup / validation / hit / walk / store
of MaxContinuousRange, the cache of GetMemoryLayoutSize, and Track/Reset of UsageTracker.
Every cached answer is also compared with an uncached walk of the current table.

Main fails by behaviour: an unrelated map walks again, a larger query at the same start walks
again, GetMemoryLayoutSize walks the kind map on every call, and a sub-range of the covered
pool fills pages again.
"""
from pathlib import Path
from types import SimpleNamespace
import random
import re
import sys

args = [a for a in sys.argv[1:] if not a.startswith('--')]
root = Path(__file__).resolve().parents[1]
source = Path(args[0]).resolve() if args else Path(
    (root / '.local/headless-cache').read_text().strip()) / 'source'
src = source / 'src'


def strip_comments(text):
    return re.sub(r'//[^\n]*', '', text)


cpp = strip_comments((src / 'video_core/memory_manager.cpp').read_text())
header = strip_comments((src / 'video_core/memory_manager.h').read_text())
tracker = strip_comments((src / 'video_core/buffer_cache/usage_tracker.h').read_text())
failures = []
phase = ['static']


def check(condition, message):
    if not condition:
        failures.append(f'[{phase[0]}] {message}')
    return condition


def block_end(text, open_brace):
    depth, i = 1, open_brace + 1
    while depth:
        depth += (text[i] == '{') - (text[i] == '}')
        i += 1
    return i


def function(text, signature):
    if signature not in text:
        return None
    start = text.index(signature)
    return text[start:block_end(text, text.index('{', start))]


def body_of(fn):
    return fn[fn.index('{') + 1:-1]


def ifs(text):
    """`if (cond) { block }` statements of a block, not those nested in another if:
    (cond, block, text after the block)."""
    out, pos = [], 0
    while (m := re.compile(r'\bif \(').search(text, pos)):
        i, depth = m.end(), 1
        while depth:
            depth += (text[i] == '(') - (text[i] == ')')
            i += 1
        cond = text[m.end():i - 1]
        brace = text.index('{', i)
        end = block_end(text, brace)
        out.append((' '.join(cond.split()), text[brace + 1:end - 1], text[end:]))
        pos = end
    return out


def assignments(name, text):
    return re.findall(r'\b' + name + r'\.(\w+) = ([^;]*);', text)


MASK64 = (1 << 64) - 1


def py(expression):
    e = ' '.join(expression.split())
    e = re.sub(r'\(std::(min|max)(<[\w:]+>)?\)', r'\1', e)
    e = re.sub(r'std::(min|max)(<[\w:]+>)?', r'\1', e)
    e = re.sub(r'\b(?:size_t|u64)\{([^}]*)\}', r'(\1)', e)
    e = re.sub(r'static_cast<[\w:]+>', '', e)
    e = re.sub(r'map_serial\.load\([^)]*\)', 'map_serial_now', e)
    e = re.sub(r'\b(\w+)\.size\(\)', r'len(\1)', e)
    e = re.sub(r'\b(0x[0-9a-fA-F]+|\d+)(?:ULL|ull|UL|U|u)\b', r'\1', e)
    e = e.replace('&&', ' and ').replace('||', ' or ')
    e = re.sub(r'!(?!=)', ' not ', e)
    e = e.replace('true', 'True').replace('false', 'False')
    return e


def cval(expression, env):
    return eval(py(expression), {'min': min, 'max': max, 'len': len}, env)


def init_list(text):
    """Fields of `{a, b(c, d), e}` split at top-level commas."""
    parts, depth, cur = [], 0, ''
    for ch in text:
        depth += (ch in '([{') - (ch in ')]}')
        if ch == ',' and depth == 0:
            parts.append(cur.strip())
            cur = ''
        else:
            cur += ch
    parts.append(cur.strip())
    return parts


def struct_fields(text):
    return re.findall(r'(\w+)\s*;', re.search(r'struct \w+ \{([^}]*)\};', text).group(1))


# --------------------------------------------------------------------------------------------
# Production pieces.

log_match = re.search(r'std::array<std::pair<GPUVAddr, GPUVAddr>, (\d+)> map_log', header)
LOG = int(log_match.group(1)) if log_match else 0
note_fn = function(cpp, 'void MemoryManager::NoteMapChange(')
changed_fn = function(cpp, 'bool MemoryManager::MapChangedSince(')
mcr_fn = function(cpp, 'size_t MemoryManager::MaxContinuousRange(')
layout_fn = function(cpp, 'size_t MemoryManager::GetMemoryLayoutSize(')
unmap_fn = function(cpp, 'void MemoryManager::Unmap(')
ops = {name: function(cpp, f'GPUVAddr MemoryManager::{name}(')
       for name in ('PageTableOp', 'BigPageTableOp')}
check(LOG >= 32, 'memory_manager.h keeps a log of the last page table change ranges (map_log)')
check(note_fn is not None and changed_fn is not None,
      'NoteMapChange / MapChangedSince exist in memory_manager.cpp')
check('#include <array>' in header, 'memory_manager.h includes <array> for map_log')

# Every page table write is in PageTableOp / BigPageTableOp, and each ends with the note.
writes = [m.start() for m in re.finditer(
    r'\bSetEntry\(|\bpage_table\[[^\]]*\] = |big_page_table_dev\.Set\(|kind_map\.Map\(', cpp)]
spans = [(cpp.index(fn), cpp.index(fn) + len(fn)) for fn in ops.values() if fn]
setentry_def = cpp.index('void MemoryManager::SetEntry(')
check(all(any(b <= w < e for b, e in spans) or setentry_def <= w < setentry_def + 40
          for w in writes),
      'page table / kind map writes happen only inside PageTableOp and BigPageTableOp')
bumps = [m.start() for m in re.finditer(r'map_serial\.(fetch_add|store|exchange)\(|\+\+map_serial|map_serial\+\+|map_serial =', cpp)]
for name, fn in ops.items():
    tail = fn[fn.rindex('kind_map.Map('):]
    check('NoteMapChange(gpu_addr, size);' in tail,
          f'{name} records its range (NoteMapChange(gpu_addr, size)) after changing the table')
if note_fn:
    nb, ne = cpp.index(note_fn), cpp.index(note_fn) + len(note_fn)
    check(all(nb <= b < ne for b in bumps), 'map_serial changes only in NoteMapChange')
    check('map_log_guard' in note_fn and 'map_log_guard' in (changed_fn or ''),
          'the map log is read and written under map_log_guard')

# --------------------------------------------------------------------------------------------
# Simulated memory manager.

PAGE = 64 << 10
SPACE_BITS = 40
SPACE = 1 << SPACE_BITS


class Manager:
    def __init__(self):
        self.pages = {}      # page index -> device page index
        self.kinds = {}      # page index -> kind
        self.serial = 0
        self.log = [(0, 0)] * max(LOG, 1)
        self.walks = []      # (gpu_addr, size) of uncached walks
        self.kind_walks = 0
        self.unique_identifier = 7
        self.mcr_cache = []
        self.mcr_next = 0
        self.layout_cache = {}

    # Uncached answers (oracles).
    def uncached(self, gpu_addr, size, record=True):
        if record:
            self.walks.append((gpu_addr, size))
        got, expected = 0, None
        addr = gpu_addr
        while got < size:
            page = addr // PAGE
            if page not in self.pages:
                break
            dev = self.pages[page] * PAGE + addr % PAGE
            if expected is not None and dev != expected:
                break
            step = min(size - got, PAGE - addr % PAGE)
            got += step
            addr += step
            expected = dev + step
        return got

    def kind_size(self, gpu_addr):
        page = gpu_addr // PAGE
        kind = self.kinds.get(page)
        if kind is None:
            return 0
        end = page
        while self.kinds.get(end + 1) == kind:
            end += 1
        return (end + 1) * PAGE - gpu_addr

    # Page table changes, with the production serial bump of each op.
    def op(self, name, gpu_addr, size):
        fn = ops[name]
        tail = fn[fn.rindex('kind_map.Map('):]
        note = re.search(r'NoteMapChange\(([^;]*)\);', tail)
        if note:
            a, s = (cval(x, {'gpu_addr': gpu_addr, 'size': size}) for x in init_list(note.group(1)))
            self.note(a, s)
        elif 'map_serial.fetch_add(1' in tail:
            self.serial += 1
        else:
            check(False, f'{name} bumps the map serial')

    def note(self, gpu_addr, size):
        m = re.search(r'map_log\[([^\]]*)\] = \{([^}]*)\};', note_fn)
        nxt = self.serial + 1
        env = {'next': nxt, 'gpu_addr': gpu_addr, 'size': size, 'map_log': self.log}
        begin, end = (cval(x, env) for x in init_list(m.group(2)))
        self.log[cval(m.group(1), env)] = (begin, end)
        self.serial = nxt

    def map(self, gpu_addr, dev_addr, size, kind=1, big=True):
        for i in range(size // PAGE):
            self.pages[gpu_addr // PAGE + i] = dev_addr // PAGE + i
            self.kinds[gpu_addr // PAGE + i] = kind
        self.op('BigPageTableOp' if big else 'PageTableOp', gpu_addr, size)

    def unmap(self, gpu_addr, size):
        for i in range(size // PAGE):
            self.pages.pop(gpu_addr // PAGE + i, None)
            self.kinds.pop(gpu_addr // PAGE + i, None)
        for name in re.findall(r'\b((?:Big)?PageTableOp)\(', unmap_fn):
            self.op(name, gpu_addr, size)

    # MapChangedSince, replayed from production.
    def map_changed_since(self, since_serial, now_serial, begin, end):
        conds = ifs(body_of(changed_fn))
        overflow = [c for c, block, _ in conds if 'return true' in block and 'changed_' not in c]
        touch = [c for c, block, _ in conds if 'return true' in block and 'changed_' in c]
        env = {'since_serial': since_serial, 'now_serial': now_serial, 'begin': begin,
               'end': end, 'map_log': self.log, 'map_serial_now': self.serial}
        if any(cval(c, env) for c in overflow):
            return True
        for serial in range(since_serial + 1, now_serial + 1):
            env['changed_begin'], env['changed_end'] = self.log[serial % len(self.log)]
            if any(cval(c, env) for c in touch):
                return True
        return False

    # MaxContinuousRange, replayed from production.
    def max_continuous_range(self, gpu_addr, size):
        body = body_of(mcr_fn)
        loop_at = re.search(r'\bfor \(', body).start()
        loop_end = block_end(body, body.index('{', loop_at))
        loop, after = body[body.index('{', loop_at) + 1:loop_end - 1], body[loop_end:]
        lookup = ifs(loop)
        record_name = re.search(r'(?:Entry|Interval)& (\w+)', body[loop_at:]).group(1)
        env = {'gpu_addr': gpu_addr, 'size': size, 'serial': self.serial,
               'unique_identifier': self.unique_identifier,
               'address_space_size': SPACE, 'MapChangedSince': self.map_changed_since}
        for rec in list(self.mcr_cache):
            env[record_name] = rec
            for cond, block, _ in lookup:
                if 'MapChangedSince' in block:
                    # Serial check: drop the record when the change log says so, else renew it.
                    if cval(cond, env):
                        inner_cond, inner_block, rest = ifs(block)[0]
                        if cval(inner_cond, env):
                            for field, value in assignments(record_name, inner_block):
                                setattr(rec, field, cval(value, env))
                            break
                        for field, value in assignments(record_name, rest):
                            setattr(rec, field, cval(value, env))
                elif 'continue' in block:
                    if cval(cond, env):
                        break
                elif 'return' in block and cval(cond, env):
                    ret = re.search(r'return ([^;]*);', block).group(1)
                    local = re.search(r'const \w+ ' + re.escape(ret) + r' = ([^;]*);', block)
                    return cval(local.group(1) if local else ret, env)
        # Miss: fallback guard, declarations, store, return.
        for cond, block, _ in ifs(after):
            call = re.search(r'return MaxContinuousRangeUncached\(gpu_addr, ([^;]*)\);', block)
            if call and cval(cond, env):
                return self.uncached(gpu_addr, cval(call.group(1), env))
        for name, value in re.findall(r'(?:static constexpr |const )?\b(?:size_t|u64) (\w+) = ([^;]*);', after):
            call = re.fullmatch(r'MaxContinuousRangeUncached\(gpu_addr, (.*)\)', value)
            env[name] = self.uncached(gpu_addr, cval(call.group(1), env)) if call else cval(value, env)
        store = re.search(r'(?:set\[0\]|cache\[\w+\]) = \{([^;]*)\};', after)
        guard = [c for c, b, _ in ifs(after) if store.group(0) in b]
        if not guard or cval(guard[0], env):
            values = [cval(x, env) for x in init_list(store.group(1))]
            self.mcr_cache.append(SimpleNamespace(**dict(zip(struct_fields(body), values))))
            capacity = re.search(r'std::array<Interval, (\d+)> cache', body)
            if capacity and len(self.mcr_cache) > int(capacity.group(1)):
                self.mcr_cache.pop(0)
        return cval(re.findall(r'return ([^;]*);', after)[-1], env)

    # GetMemoryLayoutSize, replayed from production.
    def memory_layout_size(self, gpu_addr):
        body = body_of(layout_fn)
        env = {'gpu_addr': gpu_addr, 'serial': self.serial,
               'unique_identifier': self.unique_identifier, 'MapChangedSince': self.map_changed_since}
        lock_at = body.find('std::unique_lock<std::mutex> lock(guard);')
        walk_at = body.find('kind_map.GetContinuousSizeFrom(gpu_addr)')
        check(0 <= lock_at < walk_at, 'GetMemoryLayoutSize walks the kind map under guard')
        if 'thread_local' in body:
            entry = self.layout_cache.get(gpu_addr)
            if entry is not None:
                env['entry'] = entry
                cond, block, _ = ifs(body)[0]
                if cval(cond, env):
                    for field, value in re.findall(r'\bentry\.(\w+) = ([^;]*);', block):
                        setattr(entry, field, cval(value, env))
                    return cval(re.search(r'return ([^;]*);', block).group(1), env)
        self.kind_walks += 1
        result = self.kind_size(gpu_addr)
        if 'thread_local' in body:
            env['result'] = result
            store = re.search(r'\bentry = \{([^;]*)\};', body)
            self.layout_cache[gpu_addr] = SimpleNamespace(**dict(zip(
                struct_fields(body), (cval(x, env) for x in init_list(store.group(1))))))
        return result


MiB = 1 << 20


def mcr(m, gpu_addr, size, expect_walk):
    before = len(m.walks)
    got = m.max_continuous_range(gpu_addr, size)
    oracle = m.uncached(gpu_addr, size, record=False)
    check(got == oracle, f'MaxContinuousRange({gpu_addr:#x}, {size:#x}) = {got:#x}, page table says {oracle:#x}')
    walked = len(m.walks) > before
    if expect_walk is not None:
        check(walked == expect_walk,
              f'MaxContinuousRange({gpu_addr:#x}, {size:#x}) {"walked" if walked else "did not walk"} the page table')
    return got


# 1 / 2. Selective invalidation.
phase[0] = 'selective invalidation'
m = Manager()
A, B, C = 0x10_0000_0000, 0x40_0000_0000, 0x80_0000_0000
m.map(A, 0x1_0000_0000, 32 * MiB)
m.map(B, 0x2_0000_0000, 32 * MiB)
mcr(m, A, 8 * MiB, True)
mcr(m, B, 8 * MiB, True)
mcr(m, A, 8 * MiB, False)
m.map(C, 0x3_0000_0000, 1 * MiB)                 # touches neither run
mcr(m, A, 8 * MiB, False)
mcr(m, B + 4 * MiB, 8 * MiB, False)
m.unmap(C, 1 * MiB)                              # Unmap (both ops, two serials)
mcr(m, A, 8 * MiB, False)
m.map(A + 32 * MiB, 0x1_0000_0000 + 32 * MiB, 16 * MiB)  # extends A where it ended
mcr(m, A, 40 * MiB, True)
mcr(m, B, 8 * MiB, False)
m.unmap(A + 4 * MiB, 1 * MiB)                    # cuts A
mcr(m, A, 8 * MiB, True)
mcr(m, B + 1 * MiB, 8 * MiB, False)
for i in range(LOG + 1):                         # more changes than the log keeps
    m.map(C + i * 2 * MiB, 0x3_0000_0000, 1 * MiB)
mcr(m, B, 8 * MiB, True)

# 3. Walk-ahead and interval hits.
phase[0] = 'walk-ahead'
m = Manager()
R = 0x20_0000_0000
m.map(R, 0x1_0000_0000, 512 * MiB)
mcr(m, R, 1 * MiB, True)
check(m.walks[-1] == (R, 256 * MiB), f'a miss walks 256 MiB ahead, walked {m.walks[-1][1]:#x}')
mcr(m, R, 64 * MiB, False)
mcr(m, R + 8 * MiB, 4 * MiB, False)
mcr(m, R + 100 * MiB, 156 * MiB, False)
mcr(m, R + 100 * MiB, 300 * MiB, True)            # reaches past what was walked
m = Manager()
m.map(R, 0x1_0000_0000, 32 * MiB)                # the run ends before the walk does
mcr(m, R, 1 * MiB, True)
mcr(m, R + 2 * MiB, 100 * MiB, False)
m = Manager()
m.map(SPACE - 16 * MiB, 0x1_0000_0000, 16 * MiB)
mcr(m, SPACE - 16 * MiB, 1 * MiB, True)
check(m.walks[-1][1] == 16 * MiB, f'the walk stops at the end of the address space, walked {m.walks[-1][1]:#x}')
mcr(m, SPACE - 8 * MiB, 8 * MiB, False)
mcr(m, SPACE - 8 * MiB, 16 * MiB, True)           # past the end: uncached walk of the size
check(m.walks[-1] == (SPACE - 8 * MiB, 16 * MiB), 'a query past the address space walks only its size')
mcr(m, SPACE + PAGE, 1 * MiB, True)

# Random maps, unmaps and queries: every answer equals the current page table's.
phase[0] = 'random'
rng = random.Random(178)
m = Manager()
for step in range(3000):
    base = rng.randrange(64) * 4 * MiB
    r = rng.random()
    if r < 0.08:
        m.map(base, rng.randrange(1 << 12) * PAGE, rng.randrange(1, 64) * PAGE, kind=rng.randrange(1, 3))
    elif r < 0.12:
        m.unmap(base, rng.randrange(1, 64) * PAGE)
    elif r < 0.6:
        mcr(m, base + rng.randrange(64) * PAGE + rng.choice((0, 256)), rng.randrange(1, 8 * MiB), None)
    else:
        a = base + rng.randrange(64) * PAGE
        got = m.memory_layout_size(a)
        check(got == m.kind_size(a), f'GetMemoryLayoutSize({a:#x}) = {got:#x}, kind map says {m.kind_size(a):#x}')
    if len(failures) > 10:
        break

# 4. GetMemoryLayoutSize.
phase[0] = 'memory layout size'
m = Manager()
m.map(A, 0x1_0000_0000, 32 * MiB, kind=1)
check(m.memory_layout_size(A + 1 * MiB) == 31 * MiB, 'layout size of a 32 MiB kind run')
walks = m.kind_walks
m.map(C, 0x3_0000_0000, 1 * MiB, kind=1)
m.unmap(C, 1 * MiB)
check(m.memory_layout_size(A + 1 * MiB) == 31 * MiB and m.kind_walks == walks,
      'GetMemoryLayoutSize is reused across unrelated map changes')
m.map(A + 32 * MiB, 0x1_0000_0000, 8 * MiB, kind=1)
check(m.memory_layout_size(A + 1 * MiB) == 39 * MiB and m.kind_walks == walks + 1,
      'GetMemoryLayoutSize is recomputed when a map touches the cached range')
m.map(A + 4 * MiB, 0x1_0000_0000, 1 * MiB, kind=2)
check(m.memory_layout_size(A + 1 * MiB) == 3 * MiB and m.kind_walks == walks + 2,
      'GetMemoryLayoutSize is recomputed when a map overlaps the cached range')

# --------------------------------------------------------------------------------------------
# 5. UsageTracker::Track / Reset.
phase[0] = 'usage tracker'
SHIFT = cval(re.search(r'BUFFER_PAGE_SHIFT = ([^;]*);', tracker).group(1), {
    'BUFFER_BYTES_PER_BITSHIFT': int(re.search(r'BUFFER_BYTES_PER_BITSHIFT = (\d+);', tracker).group(1))})
track_fn = body_of(function(tracker, 'void Track(u64 offset, u64 size) noexcept {'))
reset_fn = body_of(function(tracker, 'void Reset() noexcept {'))


class Tracker:
    def __init__(self, size):
        self.pages = [0] * ((size >> SHIFT) + 1)
        self.fills = 0
        self.state = {'recent': [(MASK64, 0)] * 4, 'recent_cursor': 0, 'full_begin': 0,
                      'full_end': 0, 'covered_begin': 0, 'covered_end': 0}

    def reset(self):
        self.pages = [0] * len(self.pages)
        if 'recent.fill(' in reset_fn:
            self.state['recent'] = [(MASK64, 0)] * 4
        for chain in re.findall(r'((?:\w+ = )+)0;', reset_fn):
            for name in re.findall(r'(\w+) =', chain):
                self.state[name] = 0

    def track_page(self, page, offset, size):
        first = (offset % (1 << SHIFT)) >> 6
        bits = min(size, 1 << SHIFT) >> 6
        mask = (MASK64 >> (64 - bits)) if bits else MASK64
        self.pages[page] |= (mask << first) & MASK64

    def track(self, offset, size):
        st = self.state
        if (offset, size) in st['recent'] and 'recent_offset == offset' in track_fn:
            return
        env = {'offset': offset, 'size': size, **st}
        recent_at = track_fn.index('recent[recent_cursor++')
        for cond, block, _ in ifs(track_fn[:recent_at]):
            if 'covered' in cond and block.strip() == 'return;' and cval(cond, env):
                return
        st['recent'][st['recent_cursor'] % 4] = (offset, size)
        st['recent_cursor'] += 1
        page, page_end = offset >> SHIFT, (offset + size) >> SHIFT
        if page_end < page or page_end >= len(self.pages):
            return
        self.track_page(page, offset, size)
        if page == page_end:
            return
        self.fills += 1
        for p in range(page + 1, page_end):
            self.pages[p] = MASK64
        end = offset + size
        aligned = end & ~((1 << SHIFT) - 1)
        self.track_page(page_end, aligned, end - aligned)
        env['offset_end'] = end
        for cond, block, _ in ifs(track_fn[track_fn.rindex('TrackPage(page_end'):]):
            if cval(cond, env):
                for name, value in re.findall(r'(covered_\w+) = ([^;]*);', block):
                    st[name] = cval(value, env)

    def is_used(self, offset, size):
        page, page_end = offset >> SHIFT, (offset + size) >> SHIFT
        return any(self.pages[p] for p in range(page, page_end + 1))


check('FillPages(page + 1, page_end);' in track_fn and 'full_begin' in tracker,
      'Track still fills complete pages through FillPages')
t = Tracker(256 * MiB)
POOL = 16 * MiB
t.track(POOL, 4 * MiB)
check(t.fills == 1 and t.is_used(POOL + 1 * MiB, 64), 'a 4 MiB pool is tracked')
t.track(POOL, 4 * MiB)
check(t.fills == 1, 'the same range again is skipped (recent)')
t.track(POOL + 1 * MiB, 64 << 10)
check(t.fills == 1, 'a 64 KiB sub-range of the 4 MiB pool does not fill pages again (covered range)')
t.track(POOL + 2 * MiB, 64 << 10)
t.track(POOL + 3 * MiB, 64 << 10)
check(t.fills == 1, 'other sub-ranges of the pool do not fill pages again')
t.track(POOL + 3 * MiB, 2 * MiB)
check(t.fills == 2, 'a range reaching past the covered pool is tracked')
t.reset()
check(not t.is_used(POOL + 1 * MiB, 64 << 10), 'Reset clears the pages')
t.track(POOL + 1 * MiB, 64 << 10)
check(t.fills == 3 and t.is_used(POOL + 1 * MiB, 64 << 10),
      'after Reset the sub-range is tracked again (covered range cleared)')

if failures:
    print('\n'.join(failures))
    print(f'FAIL: {len(failures)} check(s)')
    sys.exit(1)
print('check-oot-pagetable-cache: OK')
