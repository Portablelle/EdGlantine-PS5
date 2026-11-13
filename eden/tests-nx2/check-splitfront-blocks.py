"""UB-175: 3D state registers written in one call, and the split front's state writes sent to
the back as register blocks.

Usage: python3 tests-nx2/check-splitfront-blocks.py [--source-only] [SOURCE_DIR]
SOURCE_DIR contains src/; defaults to the prepared headless cache.

Both modes run the same model (no compiler needed). The decisions are read from the production
text (maxwell_3d.cpp/.h, gpu_split.cpp/.h) and evaluated in Python:
 - CallMethod's guard for the in-class WriteStateRegister, FastStateWrites, and WriteStateRegister's
   same-value condition (the shadow RAM step, store and dirty flags stay in the class);
 - FrontWrite's StateWrite guard and FrontState::state_blocks;
 - which GpuSplit entry points flush the gathered writes first (Reserve, SelectEngine, Publish,
   Drain), MaxStateWrites, and Execute's Kind::State case;
 - WriteStateRegisters' "every write changes its register" guard and its CallMethod fallback.
Random front streams (pushbuffer and macro state writes, SET_SHADOW_RAM_CONTROL in every mode,
draws, an executable method that also changes a state register, deferred calls that read the
registers, publishes and drains)
run through a modelled front, ring and back, and are compared with every write run one by one:
registers, shadow RAM and dirty flags at every draw, drain and at the end.

Main fails by behaviour: CallMethod never takes the one-call state write, and the front sends
every state write as its own Method entry (no Kind::State block).
"""
from pathlib import Path
from types import SimpleNamespace
import copy
import random
import re
import sys

args = [a for a in sys.argv[1:] if not a.startswith('--')]
root = Path(__file__).resolve().parents[1]
source = Path(args[0]).resolve() if args else Path(
    (root / '.local/headless-cache').read_text().strip()) / 'source'
src = source / 'src/video_core'
cpp = (src / 'engines/maxwell_3d.cpp').read_text()
hdr = (src / 'engines/maxwell_3d.h').read_text()
split_cpp = (src / 'gpu_split.cpp').read_text()
split_h = (src / 'gpu_split.h').read_text()

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)


def strip_comments(text):
    return re.sub(r'//[^\n]*', '', text)


def non_ps5(text):
    """The build without EDEN_NX2_PS5_PROTO (the split front runs macros only there)."""
    text = re.sub(r'#ifdef EDEN_NX2_PS5_PROTO.*?#endif', '', text, flags=re.S)
    return re.sub(r'#if defined\(ARCHITECTURE_x86_64\) && !defined\(EDEN_NX2_PS5_PROTO\)\n', '', text)


def function(text, signature):
    """The body of the function whose definition starts with `signature`, or None."""
    at = text.find(signature)
    if at < 0:
        return None
    i = text.index('{', at)
    depth = 0
    while True:
        depth += (text[i] == '{') - (text[i] == '}')
        i += 1
        if depth == 0:
            return text[at:i]


def py(expression):
    e = ' '.join(strip_comments(expression).split())
    e = re.sub(r'static_cast<\s*u32\s*>', 'u32', e)
    e = e.replace('->', '.')
    e = re.sub(r'(\w+)::', r'\1_', e)
    e = e.replace('&&', ' and ').replace('||', ' or ')
    e = re.sub(r'!(?!=)', ' not ', e)
    e = re.sub(r'\btrue\b', 'True', e)
    return re.sub(r'\bfalse\b', 'False', e)


def cond_before(body, statement):
    """The condition of the `if` whose block starts with `statement`."""
    if body is None:
        return None
    m = re.search(r'if \(((?:[^{};]|\n)*?)\)\s*\{\s*' + re.escape(statement), body)
    return m.group(1) if m else None


TRACK, FILTER, PASS, REPLAY = 0, 1, 2, 3
CONTROL_NAMES = {'Regs_ShadowRamControl_Track': TRACK, 'Regs_ShadowRamControl_TrackWithFilter': FILTER,
                 'Regs_ShadowRamControl_Passthrough': PASS, 'Regs_ShadowRamControl_Replay': REPLAY}


def u32(v):
    return v & 0xffffffff


# ---- Production decisions ----
call_method = non_ps5(strip_comments(function(cpp, 'void Maxwell3D::CallMethod(') or ''))
fast_guard = cond_before(call_method, 'return WriteStateRegister(method, method_argument);')
if fast_guard is not None:
    pre = call_method[:call_method.index('return WriteStateRegister(')]
    check('RecordWrite(' not in pre and 'ProcessMacro(' not in pre,
          'CallMethod: WriteStateRegister must come before the write history and macro dispatch')
fast_writes_body = function(cpp, 'bool Maxwell3D::FastStateWrites() const')
fast_writes_expr = (re.search(r'return (.*?);', strip_comments(fast_writes_body), re.S).group(1)
                    if fast_writes_body else None)

write_state = function(hdr, 'void WriteStateRegister(u32 method, u32 method_argument) {')
in_class_ok = all(function(hdr, s) is not None for s in (
    'u32 ProcessShadowRam(u32 method, u32 argument) {',
    'void ProcessDirtyRegisters(u32 method, u32 argument) {')) and write_state is not None
same_value_expr = None
if write_state:
    ws = non_ps5(strip_comments(write_state))
    order = [ws.find('ProcessShadowRam(method, method_argument)'), ws.find('ProcessDirtyRegisters(method, argument)')]
    check(-1 not in order and order[0] < order[1],
          'WriteStateRegister: the shadow RAM step must come before the store and dirty flags')
    same_value_expr = cond_before(ws, 'ProcessDirtyRegisters(method, argument);')
    check(same_value_expr is not None and 'SkipSameValueWrites()' in same_value_expr,
          'WriteStateRegister: same-value check missing')
    check('native_draw_shadow.NeedsRead(method, false)' in write_state,
          'WriteStateRegister: the PS5 native draw shadow must still be resolved on a same-value write')
    psr = function(hdr, 'u32 ProcessShadowRam(u32 method, u32 argument) {')
    check('ResolveNativeDrawShadow()' in psr and 'NativeDrawShadowWrite(method, argument, true)' in psr,
          'ProcessShadowRam: native draw shadow handling lost')
# The previous CallMethod state branch (main), the model's fallback when there is no fast path.
old_same_value = cond_before(call_method, 'ProcessDirtyRegisters(method, argument);\n        }\n        return;')
if old_same_value is None:
    old_same_value = '!SkipSameValueWrites() || regs.reg_array[method] != argument'

front_write = non_ps5(strip_comments(function(cpp, 'void Maxwell3D::FrontWrite(') or ''))
state_guard = cond_before(front_write, 'split.StateWrite(')
state_call = re.search(r'split\.StateWrite\(this, method, (\w+), \{(.*?)\}\);', front_write)
if state_guard is not None:
    check(state_call is not None and state_call.group(1) == 'value' and
          state_call.group(2).replace(' ', '') == 'dirty.tables[0][method],dirty.tables[1][method]',
          'FrontWrite: StateWrite must carry the shadow-applied value and both dirty tables')
    check(front_write.index('split.StateWrite(') < front_write.index('} else {\n        fs.regs[method] = value;'),
          'FrontWrite: StateWrite only for state registers (not in execution_mask)')
blocks_init = re.search(r'front->state_blocks = (.*?);', cpp)
blocks_init = blocks_init.group(1) if blocks_init else None

state_write_fn = function(split_h, 'void StateWrite(')
flush_points = set()
for name, text, sig in (('Reserve', split_h, 'u64* Reserve(size_t words) {'),
                        ('SelectEngine', split_h, 'void SelectEngine(Tegra::Engines::EngineInterface* engine) {'),
                        ('Publish', split_cpp, 'void GpuSplit::Publish() {'),
                        ('Drain', split_cpp, 'void GpuSplit::Drain(')):
    body = function(text, sig)
    if body and re.match(r'[^{]*\{\s*FlushState\(\);', strip_comments(body)):
        flush_points.add(name)
max_writes = re.search(r'MaxStateWrites = (\d+);', split_h)
max_writes = int(max_writes.group(1)) if max_writes else 128
if state_write_fn:
    sw = strip_comments(state_write_fn)
    check('state_count == MaxStateWrites' in sw and 'FlushState();' in sw,
          'StateWrite: a full block or another engine must flush first')
    check(re.search(r'state_words\[StateFlagWords \+ state_count\+\+\] = u64\{method\} \| \(u64\{value\} << 32\);', sw),
          'StateWrite: writes must be appended in order')
    check(re.search(r'for \(const u8 flag : flags\) \{\s*state_words\[flag / 64\] \|= u64\{1\} << \(flag % 64\);', sw),
          'StateWrite: dirty flags must be ORed')
    check(flush_points == {'Reserve', 'SelectEngine', 'Publish', 'Drain'},
          f'GpuSplit: the gathered writes must be sent before any entry, publish or drain (flushes in {sorted(flush_points)})')
    bc = function(split_h, '[[nodiscard]] bool BackCaughtUp() const {')
    check(bc and 'state_count == 0' in bc, 'BackCaughtUp must not report caught up with writes gathered')
    ex = function(split_cpp, 'size_t GpuSplit::Execute(')
    check(ex and re.search(r'case Kind::State:.*?WriteStateRegisters\(', ex, re.S),
          'GpuSplit::Execute: Kind::State must reach Maxwell3D::WriteStateRegisters')

wsr = function(cpp, 'void Maxwell3D::WriteStateRegisters(')
block_guard = block_each = None
if wsr:
    w = non_ps5(strip_comments(wsr))
    check(re.search(r'\{\s*ConsumeSink\(system\);', w), 'WriteStateRegisters: the method sink must go first')
    block_guard = re.search(r'bool changes = (.*?);', w, re.S).group(1)
    block_each = re.search(r'for \(size_t i = 0; changes && i < writes\.size\(\); \+\+i\) \{\s*changes = (.*?);', w, re.S)
    block_each = block_each.group(1) if block_each else None
    check(block_each is not None, 'WriteStateRegisters: every write must be checked to change its register')
    check(re.search(r'if \(!changes\) \{\s*for \(const u64 write : writes\) \{\s*CallMethod\(system,', w),
          'WriteStateRegisters: CallMethod one by one when a write keeps its value')
    check('native_draw_shadow.Empty()' in wsr, 'WriteStateRegisters: PS5 native draw shadow must take CallMethod')
    store = strip_comments(function(cpp, 'void Maxwell3D::StoreStateRegisters(') or '')
    check(re.search(r'for \(const u64 write : writes\) \{.*?if \(tracked\) \{\s*shadow_state\.reg_array\[method\] = value;'
                    r'\s*\}\s*regs\.reg_array\[method\] = value;', store, re.S),
          'StoreStateRegisters: every write in order, the shadow RAM when tracking')
    check(re.search(r'tracked =\s*control == Regs::ShadowRamControl::Track \|\| control == Regs::ShadowRamControl::TrackWithFilter;', store),
          'StoreStateRegisters: tracked must be Track or TrackWithFilter')


# ---- Model ----
STATE = list(range(0x200, 0x218))   # state registers (not in execution_mask)
CTRL = 0x49                         # SET_SHADOW_RAM_CONTROL (executable)
DRAW = 0x300                        # an executable method: the draw reads the state
BACKSET = 0x301                     # executable, also changes STATE[0] (as CB data changes
                                    # const_buffer.offset; the front tracks it)
EXEC = {CTRL, DRAW, BACKSET}
MACRO_START = 0xE00
NUM = 0x400


class Mask:
    def __getitem__(self, m):
        return m >= MACRO_START or m in EXEC


class Env(dict):
    def __missing__(self, key):
        if key in CONTROL_NAMES:
            return CONTROL_NAMES[key]
        raise KeyError(key)


COMPILED = {}


def evaluate(expression, env):
    code = COMPILED.get(expression)
    if code is None:
        code = COMPILED[expression] = compile(py(expression).strip(), '<production>', 'eval')
    return bool(eval(code, {'u32': u32}, env))


class Engine:
    def __init__(self, cfg, tables):
        self.regs = [0] * NUM
        self.shadow = [0] * NUM
        self.control = TRACK
        self.dirty = set()
        self.tables = tables
        self.cfg = cfg
        self.sink = []
        self.executing_macro = 0
        self.fast_calls = 0
        self.blocks = self.one_by_one = 0

    def env(self, **extra):
        e = Env(executing_macro=self.executing_macro, MacroRegistersStart=MACRO_START,
                execution_mask=Mask(), record_write_history=self.cfg['history'],
                g_trace_first_method_writes=self.cfg['trace'],
                VideoCommon_Nx2Profile_Enabled=lambda: self.cfg['profile'],
                SkipSameValueWrites=lambda: self.cfg['skip_same'],
                regs=SimpleNamespace(reg_array=self.regs),
                shadow_state=SimpleNamespace(reg_array=self.shadow, shadow_ram_control=self.control))
        e['FastStateWrites'] = lambda: evaluate(fast_writes_expr, e) if fast_writes_expr else False
        e.update(extra)
        return e

    def shadow_step(self, m, a):
        if self.control in (TRACK, FILTER):
            self.shadow[m] = a
            return a
        return self.shadow[m] if self.control == REPLAY else a

    def store(self, m, v):
        self.regs[m] = v
        for t in self.tables:
            self.dirty.add(t[m])

    def state_write(self, m, a, condition):
        v = self.shadow_step(m, a)
        if evaluate(condition, self.env(method=m, argument=v)):
            self.store(m, v)

    def call_method(self, m, a):
        if fast_guard is not None and evaluate(fast_guard, self.env(method=m)):
            self.fast_calls += 1
            return self.state_write(m, a, same_value_expr)
        if not Mask()[m]:
            return self.state_write(m, a, old_same_value)
        v = self.shadow_step(m, a)
        self.store(m, v)
        if m == CTRL:
            self.control = a
        elif m == BACKSET:
            self.regs[STATE[0]] = a

    def consume_sink(self):
        sink, self.sink = self.sink, []
        for m, a in sink:
            self.state_write(m, a, old_same_value)

    def write_state_registers(self, flags, writes):
        self.consume_sink()
        changes = evaluate(block_guard, self.env())
        for i in range(len(writes)):
            if not changes:
                break
            changes = evaluate(block_each, self.env(writes=writes, i=i))
        if not changes:
            self.one_by_one += 1
            for w in writes:
                self.call_method(w & 0xffff, w >> 32)
            return
        self.blocks += 1
        for w in writes:
            m, v = w & 0xffff, w >> 32
            if self.control in (TRACK, FILTER):
                self.shadow[m] = v
            self.regs[m] = v
        self.dirty |= flags

    def snapshot(self):
        """Registers, shadow RAM and dirty flags with the method sink applied (on a copy)."""
        view = copy.copy(self)
        view.regs, view.shadow, view.dirty = list(self.regs), list(self.shadow), set(self.dirty)
        view.sink = list(self.sink)
        view.consume_sink()
        return view.regs, view.shadow, view.dirty

    def draw(self):
        self.consume_sink()
        shot = self.snapshot()
        self.dirty.clear()
        return shot


class Split:
    def __init__(self, back):
        self.ring, self.published, self.done = [], 0, 0
        self.pending, self.flags = [], set()
        self.back = back
        self.shots = []
        self.stats = {'state': 0, 'own_replay': 0, 'own_other': 0, 'max_block': 0}

    def flush(self, where):
        if where in flush_points and self.pending:
            self.ring.append(('state', set(self.flags), self.pending))
            self.stats['state'] += 1
            self.stats['max_block'] = max(self.stats['max_block'], len(self.pending))
            self.pending, self.flags = [], set()

    def defer(self):
        self.flush('Reserve')
        self.ring.append(('call',))

    def entry(self, e):
        self.flush('SelectEngine')
        self.flush('Reserve')
        self.ring.append(e)

    def state_write(self, m, v, flags):
        if len(self.pending) == max_writes:
            self.flush('Reserve')  # FlushState(): the entry is reserved like any other
        self.pending.append(m | (v << 32))
        self.flags |= set(flags)

    def publish(self):
        self.flush('Publish')
        self.published = len(self.ring)

    def run_back(self):
        while self.done < self.published:
            kind, *rest = self.ring[self.done]
            self.done += 1
            b = self.back
            if kind == 'state':
                b.write_state_registers(*rest)
            elif kind == 'call':
                self.shots.append(b.snapshot()[:2])
            elif kind == 'method' and not Mask()[rest[0]]:
                b.sink.append(tuple(rest))
            else:
                b.consume_sink()
                b.call_method(*rest)
                if rest[0] == DRAW:
                    self.shots.append(b.draw())

    def drain(self):
        self.flush('Drain')
        self.publish()
        self.run_back()
        return self.back.snapshot()


class Front:
    def __init__(self, cfg, engine, split):
        self.regs, self.shadow, self.control = list(engine.regs), list(engine.shadow), engine.control
        self.skip_same = cfg['skip_same'] and cfg['split_skip']
        e = engine.env(front=SimpleNamespace(skip_same=self.skip_same), FrontSkipSame=lambda: cfg['split_skip'])
        self.state_blocks = bool(blocks_init) and evaluate(blocks_init, e)
        self.split, self.tables = split, engine.tables

    def write(self, m, a, from_macro):
        value, kept = a, True
        if self.control in (TRACK, FILTER):
            kept = self.shadow[m] == a
            self.shadow[m] = a
        elif self.control == REPLAY:
            value = self.shadow[m]
        if not Mask()[m]:
            if self.regs[m] == value and kept and self.skip_same:
                return
            self.regs[m] = value
            fs = SimpleNamespace(state_blocks=self.state_blocks, control=self.control)
            if state_guard is not None and state_write_fn and evaluate(state_guard, Env(fs=fs)):
                return self.split.state_write(m, value, (self.tables[0][m], self.tables[1][m]))
        else:
            self.regs[m] = value
            if m == CTRL:
                self.control = a
                self.shadow[m] = a
            elif m == BACKSET:  # as FrontWrite tracks const_buffer.offset and shadow_scratch
                self.regs[STATE[0]] = a
        if not Mask()[m]:
            self.split.stats['own_replay' if self.control == REPLAY else 'own_other'] += 1
        self.split.entry(('direct' if from_macro else 'method', m, a))


def stream(rng, n):
    ops = []
    for _ in range(n):
        r = rng.random()
        if r < 0.62:
            ops.append(('w', rng.choice(STATE), rng.randrange(4), rng.random() < 0.5))
        elif r < 0.70:
            ops.append(('w', CTRL, rng.choice([TRACK, TRACK, FILTER, PASS, REPLAY]), rng.random() < 0.5))
        elif r < 0.82:
            ops.append(('w', DRAW, 0, False))
        elif r < 0.86:
            ops.append(('w', BACKSET, rng.randrange(4), False))
        elif r < 0.92:
            ops.append(('publish',))
        elif r < 0.94:
            ops.append(('drain',))
        elif r < 0.96:
            ops.append(('defer',))
        else:  # a long run: fills blocks
            ops += [('w', STATE[i % len(STATE)], rng.randrange(1, 1 << 16), True)
                    for i in range(max_writes + 37)]
    return ops + [('w', DRAW, 0, False)]


def run(cfg, seed):
    rng = random.Random(seed)
    tables = [[rng.randrange(1, 256) if m in STATE else 0 for m in range(NUM)] for _ in range(2)]
    ref, back = Engine(cfg, tables), Engine(cfg, tables)
    split = Split(back)
    front = Front(cfg, back, split)
    ref_shots, ok = [], True
    for op in stream(rng, 1200):
        if op[0] == 'w':
            ref.call_method(op[1], op[2])
            if op[1] == DRAW:
                ref_shots.append(ref.draw())
            front.write(op[1], op[2], op[3])
        elif op[0] == 'defer':
            ref_shots.append(ref.snapshot()[:2])
            split.defer()
        elif op[0] == 'publish':
            split.publish()
            if rng.random() < 0.5:
                split.run_back()
        else:
            ok &= split.drain()[:2] == ref.snapshot()[:2]
    ok &= split.drain()[:2] == ref.snapshot()[:2]
    ok &= split.shots == ref_shots
    return ok, split.stats, back


DEFAULT = dict(history=False, trace=False, profile=False, skip_same=True, split_skip=True)

# M: CallMethod's one-call state write, and what still takes the longer path.
probe = Engine(DEFAULT, [[1] * NUM, [2] * NUM])
taken = lambda **k: fast_guard is not None and evaluate(fast_guard, probe.env(**k))
check(taken(method=STATE[0]), 'CallMethod: an admissible 3D state write does not take WriteStateRegister')
check(not taken(method=CTRL), 'CallMethod: SET_SHADOW_RAM_CONTROL must take the executable path')
check(not taken(method=DRAW), 'CallMethod: an executable method must take the executable path')
check(not taken(method=MACRO_START + 2), 'CallMethod: a macro call must take ProcessMacro')
check(not taken(method=STATE[0], executing_macro=MACRO_START), 'CallMethod: a macro collecting parameters must not')
for key in ('history', 'trace', 'profile'):
    probe.cfg = dict(DEFAULT, **{key: True})
    check(not taken(method=STATE[0]), f'CallMethod: the one-call write must stay off with {key} on')
check(in_class_ok, 'ProcessShadowRam, ProcessDirtyRegisters and WriteStateRegister must be defined in the class')

# Same-value, shadow RAM and dirty flags of the one-call write against the previous path.
for skip in (True, False):
    for control in (TRACK, FILTER, PASS, REPLAY):
        for value in (0, 5):
            results = []
            for condition in (same_value_expr or old_same_value, old_same_value):
                e = Engine(dict(DEFAULT, skip_same=skip), [[3] * NUM, [7] * NUM])
                e.control, e.shadow[STATE[1]] = control, 5
                e.state_write(STATE[1], value, condition)
                results.append((e.regs[STATE[1]], e.shadow[STATE[1]], e.dirty))
            check(results[0] == results[1], f'WriteStateRegister differs (skip {skip}, mode {control}, value {value})')

# The back's own guard: a block arriving while the shadow RAM replays, or that keeps a register's
# value, goes through CallMethod one by one (which replays the shadow entry / skips the write).
if block_guard is not None:
    for control, keep in ((REPLAY, False), (TRACK, True)):
        e = Engine(DEFAULT, [[3] * NUM, [7] * NUM])
        e.control, e.shadow[STATE[2]], e.regs[STATE[3]] = control, 9, 4
        e.write_state_registers({3, 7}, [STATE[2] | (5 << 32), STATE[3] | ((4 if keep else 6) << 32)])
        check(e.one_by_one == 1 and e.blocks == 0,
              f'WriteStateRegisters: mode {control}, keeps value {keep} must go one by one')
        if control == REPLAY:
            check(e.regs[STATE[2]] == 9, 'WriteStateRegisters: a replayed write must store the shadow entry')

# L: blocks in order, with the same registers, shadow RAM and dirty flags as one by one.
totals = {'state': 0, 'own_replay': 0, 'own_other': 0, 'blocks': 0, 'one_by_one': 0, 'fast': 0, 'max_block': 0}
for seed in range(24):
    ok, stats, back = run(DEFAULT, seed)
    check(ok, f'seed {seed}: registers, shadow RAM or dirty flags differ from the writes one by one')
    totals['state'] += stats['state']
    totals['own_replay'] += stats['own_replay']
    totals['own_other'] += stats['own_other']
    totals['max_block'] = max(totals['max_block'], stats['max_block'])
    totals['blocks'] += back.blocks
    totals['one_by_one'] += back.one_by_one
    totals['fast'] += back.fast_calls
check(totals['state'] > 0 and totals['blocks'] > 0, 'the front sends no Kind::State register block')
check(totals['max_block'] == max_writes, f'blocks never fill to MaxStateWrites ({totals["max_block"]})')
check(totals['one_by_one'] > 0, 'a block with a write that keeps its value never goes through CallMethod')
check(totals['fast'] > 0, 'the back never writes a state register in one call')
# Replays keep their own entries; everything else a state write is goes in blocks.
check(totals['own_other'] == 0,
      f'{totals["own_other"]} state writes outside replay still sent as their own Method entries')
check(totals['own_replay'] > 0, 'replayed state writes must keep their own entries')
for off in ({'skip_same': False}, {'split_skip': False}, {'profile': True}, {'history': True}):
    cfg = dict(DEFAULT, **off)
    for seed in range(6):
        ok, stats, _ = run(cfg, 100 + seed)
        check(ok, f'{off} seed {seed}: differs from the writes one by one')
        check(stats['state'] == 0, f'{off}: state blocks must stay off')

if failures:
    print('UB-175 split front state blocks: FAIL')
    for f in failures:
        print('  ' + f)
    sys.exit(1)
print(f'UB-175 split front state blocks: PASS ({totals["state"]} blocks, {totals["blocks"]} stored at once, '
      f'{totals["one_by_one"]} one by one, {totals["fast"]} one-call writes)')
