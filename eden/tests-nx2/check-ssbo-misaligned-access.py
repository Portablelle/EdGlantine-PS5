"""UB-083 / G5: misaligned 64/128-bit SSBO accesses use words; compute writes are ordered.

Usage: python3 tests-nx2/check-ssbo-misaligned-access.py [--source-only] [SOURCE_DIR]
SOURCE_DIR contains src/; defaults to the prepared headless cache.

Storage bindings start at minStorageBufferOffsetAlignment (4 on AMD), so an 8 or 16 byte guest
access can start at any word of the binding. Indexing the vector view (offset >> 3 or >> 4) then
touches the vector BEFORE the access: a sentinel word before it is read or written and the last
word is missed (Ocarina of Time: green lighting, cyan sky).

Default (Linux/dedie): the production StorageIndex/StoragePointer/LoadStorage*/WriteStorage*,
VectorViewIsExact (when present) and EmitLoadStorage64/128, EmitWriteStorage64/128 are extracted
verbatim from emit_spirv_memory.cpp, and the global helper definitions (define_body, define_load,
define_write, define) from DefineGlobalMemoryFunctions in spirv_emit_context.cpp. They are
compiled (ASan/UBSan) against an EmitContext stub that EVALUATES each instruction on a word
memory with sentinels (structured if/return for the global helpers). Every access, value and
store is checked: aliasing on/off, alignment 4/8/16, 8 and 16 bytes, immediate offsets 0..16 and
dynamic offsets, global loads and stores through two buffers (one only 4-byte aligned).
--source-only: no compiler. The vector/word decision is evaluated from the production gate
expressions (the Emit*Storage64/128 condition, VectorViewIsExact's body, the global helper split
condition) and the same memory oracle predicts the accesses.

Both modes then model compute ordering from the production DispatchCompute, NoteComputeWrites,
Scheduler::BeginRenderPassImpl and WaitForIdle: their recorded barriers are parsed (stages,
access masks, guards, the pending flag) and replayed: dispatch (direct and indirect) -> render
pass, and two wait-for-idles in a row, checking that compute writes are visible to the reads
that follow.

Main fails by behaviour: aliased misaligned 8/16-byte accesses read/write the previous vector
(sentinels touched), the indirect dispatch records no barrier, a render pass after a dispatch has
no compute->graphics dependency, and wait-for-idle is an event wait at TOP_OF_PIPE with no memory
barrier on an event that is never reset.
"""
from pathlib import Path
import os
import platform
import re
import subprocess
import sys

args = [a for a in sys.argv[1:] if not a.startswith('--')]
source_only = '--source-only' in sys.argv[1:]
root = Path(__file__).resolve().parents[1]
source = Path(args[0]).resolve() if args else Path(
    (root / '.local/headless-cache').read_text().strip()) / 'source'
src = source / 'src'
memory_cpp = (src / 'shader_recompiler/backend/spirv/emit_spirv_memory.cpp').read_text()
context_cpp = (src / 'shader_recompiler/backend/spirv/spirv_emit_context.cpp').read_text()
rasterizer = (src / 'video_core/renderer_vulkan/vk_rasterizer.cpp').read_text()
scheduler_cpp = (src / 'video_core/renderer_vulkan/vk_scheduler.cpp').read_text()
scheduler_h = (src / 'video_core/renderer_vulkan/vk_scheduler.h').read_text()
wrapper_h = (src / 'video_core/vulkan_common/vulkan_wrapper.h').read_text()
failures = []
phase = ['source model']


def check(condition, message):
    if not condition:
        failures.append(f'[{phase[0]}] {message}')


def block_end(text, open_brace):
    depth, i = 1, open_brace + 1
    while depth:
        depth += (text[i] == '{') - (text[i] == '}')
        i += 1
    return i


def function(text, signature):
    start = text.index(signature)
    return text[start:block_end(text, text.index('{', start))]


def cexpr(expression, env):
    """Evaluates the small C++ boolean/integer expressions of the gates."""
    e = re.sub(r'\b(\d+)[uU]\b', r'\1', expression)
    e = re.sub(r'sizeof\(u32\[(\d)\]\)', lambda m: str(4 * int(m[1])), e)
    e = e.replace('ctx.profile.', 'P_').replace('profile.', 'P_')
    e = e.replace('offset.IsImmediate()', 'imm').replace('offset.U32()', 'off')
    e = e.replace('&&', ' and ').replace('||', ' or ')
    e = re.sub(r'\btrue\b', 'True', re.sub(r'\bfalse\b', 'False', e))
    e = re.sub(r'!(?!=)', ' not ', e)
    return eval(e, {}, env)


# --------------------------------------------------------------------------------------------
# Memory oracle shared by the source model and the compiled stub.
# Storage: binding words hold 0xA000 + index; an access of `size` bytes at byte `off`.
# Global: guest word at address A holds A; a binding starts at base & ~(alignment - 1).
WORDS = 16
GLOBAL_BUFFERS = [(0x1000, 0x40), (0x2004, 0x40)]  # (guest base, size); the second is 4-aligned


def storage_cases():
    for aliasing in (True, False):
        for alignment in (4, 8, 16):
            for size in (8, 16):
                for write in (False, True):
                    for off in (0, 4, 8, 12, 16):
                        yield aliasing, alignment, size, write, True, off
                    # A dynamic offset is relative to a binding aligned to `alignment`, so only
                    # offsets the guest's natural alignment and the binding allow occur.
                    step = size if alignment >= size else 4
                    for off in range(0, 32 + 1, step):
                        yield aliasing, alignment, size, write, False, off


def global_cases():
    for aliasing in (True, False):
        for alignment in (4, 8, 16):
            for size in (8, 16):
                for write in (False, True):
                    for base, length in GLOBAL_BUFFERS:
                        aligned = base & ~(alignment - 1)
                        for addr in range(base + (-base) % size, base + length - size + 1, size):
                            if addr >= aligned:
                                yield aliasing, alignment, size, write, addr


def global_binding(addr, alignment):
    for index, (base, length) in enumerate(GLOBAL_BUFFERS):
        aligned = base & ~(alignment - 1)
        if aligned <= addr < aligned + length:
            return index, aligned, base + length
    raise AssertionError(hex(addr))


def check_storage(case, accesses, values):
    aliasing, alignment, size, write, imm, off = case
    words = size // 4
    first = off // 4
    name = (f'storage {"store" if write else "load"}{size * 8} align{alignment} '
            f'{"alias" if aliasing else "noalias"} {"imm" if imm else "dynamic"} offset {off}')
    touched = {(w, rw) for word, n, rw in accesses for w in range(word, word + n)}
    expected = {(first + i, write) for i in range(words)}
    check(touched == expected, f'{name}: touches words {sorted(touched)}, expected '
          f'{sorted(expected)} (sentinels at {first - 1} and {first + words} must stay untouched)')
    exact = aliasing and (off % size == 0 if imm else alignment >= size)
    shape = [(first, words, write)] if exact else [(first + i, 1, write) for i in range(words)]
    check(sorted(accesses) == sorted(shape), f'{name}: accesses {accesses}, expected {shape}')
    if write:
        after = [0xA000 + i for i in range(WORDS * 3)]
        for i in range(words):
            after[first + i] = 0x5000 + i
        check(values == after, f'{name}: memory after store {[hex(v) for v in values]}')
    else:
        check(values == [0xA000 + first + i for i in range(words)],
              f'{name}: loaded {[hex(v) for v in values]}')


def check_global(case, accesses, values):
    aliasing, alignment, size, write, addr = case
    words = size // 4
    index, aligned, end = global_binding(addr, alignment)
    first = (addr - aligned) // 4
    name = (f'global {"store" if write else "load"}{size * 8} align{alignment} '
            f'{"alias" if aliasing else "noalias"} address {addr:#x}')
    if not aliasing:
        # No descriptor aliasing: the existing helper is unchanged (one access through the
        # vector view of the matched buffer, as on main).
        vector = ((addr - aligned) >> (size.bit_length() - 1)) * words
        check(accesses == [(index, vector, words, write)],
              f'{name}: accesses {accesses}, expected the unchanged vector helper')
        return
    touched = {(space, w, rw) for space, word, n, rw in accesses for w in range(word, word + n)}
    expected = {(index, first + i, write) for i in range(words)}
    check(touched == expected, f'{name}: touches {sorted(touched)}, expected {sorted(expected)}')
    vector = alignment >= size
    shape = ([(index, first, words, write)] if vector
             else [(index, first + i, 1, write) for i in range(words)])
    check(sorted(accesses) == sorted(shape), f'{name}: accesses {accesses}, expected {shape}')
    if write:
        binding = [aligned + 4 * i for i in range((end - aligned) // 4)]
        for i in range(words):
            binding[first + i] = 0x5000 + i
        check(values == binding, f'{name}: memory after store {[hex(v) for v in values]}')
    else:
        check(values == [addr + 4 * i for i in range(words)],
              f'{name}: loaded {[hex(v) for v in values]}')


# --------------------------------------------------------------------------------------------
# Source model of the production storage and global gates.
def storage_gate(function_name, size):
    body = function(memory_cpp, function_name + '(')
    condition = re.search(r'if \((.*?)\) \{', body)[1]
    call = re.fullmatch(r'(\w+)\(ctx, offset, (.+)\)', condition)
    if not call:
        return lambda env: cexpr(condition, env)
    helper = re.search(r'bool ' + call[1] + r'\(EmitContext& ctx, const IR::Value& offset, '
                       r'u32 (\w+)\) \{', memory_cpp)
    helper_body = memory_cpp[helper.end():block_end(memory_cpp, helper.end() - 1)]
    size_name = helper[1]
    statements = list(re.finditer(
        r'if \((?P<c>.*?)\) \{\s*return (?P<r>[^;]*);\s*\}|return (?P<f>[^;]*);', helper_body))

    def gate(env):
        env = dict(env, **{size_name: cexpr(call[2], env)})
        for statement in statements:
            if statement['c'] is None:
                return cexpr(statement['f'], env)
            if cexpr(statement['c'], env):
                return cexpr(statement['r'], env)
        raise AssertionError('no return in ' + call[1])
    return gate


def model_storage(case):
    aliasing, alignment, size, write, imm, off = case
    words = size // 4
    name = ('void EmitWriteStorage' if write else 'Id EmitLoadStorage') + str(size * 8)
    env = {'P_support_descriptor_aliasing': aliasing, 'P_min_ssbo_alignment': alignment,
           'imm': imm, 'off': off}
    memory = [0xA000 + i for i in range(WORDS * 3)]
    if storage_gate(name, size)(env):
        accesses = [((off // size) * words, words, write)]  # StorageIndex: offset / element size
    else:
        accesses = [(off // 4 + i, 1, write) for i in range(words)]
    span = [w for word, n, _ in accesses for w in range(word, word + n)]
    if write:
        for i, w in enumerate(span):
            memory[w] = 0x5000 + i
        return accesses, memory
    return accesses, [memory[w] for w in span]


global_body = function(context_cpp, 'void EmitContext::DefineGlobalMemoryFunctions(')
check('ssbo_align_mask{~(profile.min_ssbo_alignment - 1U)}' in global_body,
      'global helpers no longer bind at the storage buffer alignment; the model is stale')


def global_split(kind):
    start = global_body.index(f'const auto define_{kind}{{')
    end = global_body.index('const auto define', start + 10)
    helper = global_body[start:end]
    split = re.search(r'if \((.*?)\) \{\s*define_body\(&StorageDefinitions::U32, addr, '
                      r'storage_types\.U32\.element, 2,', helper)
    if not split:
        return lambda env: False
    condition = split[1]
    call = re.fullmatch(r'(\w+)\((\w+)\)', condition)
    if call:
        lam = re.search(r'const auto ' + call[1] + r'\{\[&\]\(u32 (\w+)\) \{\s*return (.*?);\s*\}\};',
                        global_body, re.S)
        return lambda env: cexpr(' '.join(lam[2].split()), dict(env, **{lam[1]: env['shift']}))
    return lambda env: cexpr(condition, env)


def model_global(case):
    aliasing, alignment, size, write, addr = case
    words = size // 4
    index, aligned, end = global_binding(addr, alignment)
    shift = size.bit_length() - 1
    env = {'P_support_descriptor_aliasing': aliasing, 'P_min_ssbo_alignment': alignment,
           'shift': shift}
    if global_split('write' if write else 'load')(env):
        first = (addr - aligned) >> 2
        accesses = [(index, first + i, 1, write) for i in range(words)]
    else:
        accesses = [(index, ((addr - aligned) >> shift) * words, words, write)]
    binding = [aligned + 4 * i for i in range((end - aligned) // 4)]
    span = [w for _, word, n, _ in accesses for w in range(word, word + n)]
    if write:
        for i, w in enumerate(span):
            binding[w] = 0x5000 + i
        return accesses, binding
    return accesses, [binding[w] if w < len(binding) else 0xDEADDEAD for w in span]


for case in storage_cases():
    check_storage(case, *model_storage(case))
for case in global_cases():
    check_global(case, *model_global(case))


# --------------------------------------------------------------------------------------------
# Compute ordering model: the production barriers are parsed and replayed.
GRAPHICS = {'DRAW_INDIRECT', 'VERTEX_INPUT', 'VERTEX_SHADER', 'TESSELLATION_CONTROL_SHADER',
            'TESSELLATION_EVALUATION_SHADER', 'GEOMETRY_SHADER', 'FRAGMENT_SHADER',
            'EARLY_FRAGMENT_TESTS', 'LATE_FRAGMENT_TESTS', 'COLOR_ATTACHMENT_OUTPUT',
            'TRANSFORM_FEEDBACK'}
ALL = GRAPHICS | {'COMPUTE_SHADER', 'TRANSFER', 'HOST'}


def stages(expression, local=''):
    """Stage set of a stage-mask expression (VK_*_BIT, vk:: constants and local `flags`)."""
    result = set()
    for name in re.findall(r'(?:vk::)?(?:VK_)?PIPELINE_STAGE_(\w+?)(?:_BIT(?:_EXT)?)?\b',
                           expression):
        constant = re.search(r'inline constexpr VkPipelineStageFlags PIPELINE_STAGE_' + name +
                             r' =\s*(.*?);', wrapper_h, re.S)
        if constant:
            result |= stages(constant[1])
        elif name == 'ALL_GRAPHICS':
            result |= GRAPHICS
        elif name in ('ALL_COMMANDS', 'TOP_OF_PIPE'):
            result |= ALL
        else:
            result.add(name)
    if re.search(r'\bflags\b', expression) and local:
        result |= stages(re.search(r'VkPipelineStageFlags flags =(.*?);', local, re.S)[1])
        if 'flags |= VK_PIPELINE_STAGE_TRANSFORM_FEEDBACK_BIT_EXT' in local:
            result.add('TRANSFORM_FEEDBACK')
    return result


def access(expression):
    return set(re.findall(r'VK_ACCESS_(\w+?)_BIT', expression))


def split_args(text):
    out, depth, current = [], 0, ''
    for ch in text:
        if ch == ',' and depth == 0:
            out.append(current.strip())
            current = ''
            continue
        depth += (ch in '([{') - (ch in ')]}')
        current += ch
    return out + [current.strip()]


def call_args(text, at):
    open_paren = text.index('(', at)
    depth, i = 1, open_paren + 1
    while depth:
        depth += (text[i] == '(') - (text[i] == ')')
        i += 1
    return split_args(text[open_paren + 1:i - 1])


def memory_barrier(text, name):
    found = re.search(r'VkMemoryBarrier ' + name + r'\{(.*?)\};', text, re.S)
    return (access(re.search(r'\.srcAccessMask = (.*?),', found[1])[1]),
            access(re.search(r'\.dstAccessMask = (.*?),', found[1])[1]))


def barrier(text, at, local=''):
    a = call_args(text, at)
    src_access, dst_access = memory_barrier(text, a[3]) if len(a) > 3 else (set(), set())
    return {'src': stages(a[0], local), 'dst': stages(a[1], local),
            'src_access': src_access, 'dst_access': dst_access}


def makes_visible(dependencies, write_stage, write_access, read_stage, read_access):
    """Some recorded dependency orders a write before a read and makes it visible."""
    for d in dependencies:
        writes = {write_access, 'MEMORY_WRITE'}
        reads = {read_access, 'MEMORY_READ'}
        if (write_stage in d['src'] and read_stage in d['dst'] and writes & d['src_access']
                and reads & d['dst_access']):
            return True
    return False


dispatch = function(rasterizer, 'void RasterizerVulkan::DispatchCompute()')
lambdas = {m[1]: dispatch[m.end() - 1:block_end(dispatch, m.end() - 1)]
           for m in re.finditer(r'const auto (\w+) = \[this\] \{', dispatch)}
note = re.search(r'void NoteComputeWrites\(\) \{\s*(\w+) = true;\s*\}', scheduler_h)
pending_flag = note[1] if note else None


def dispatch_events(text):
    """Barriers and pending-flag effects recorded before the dispatch command, in order."""
    events = []
    pattern = (r'cmdbuf\.PipelineBarrier\(|scheduler\.NoteComputeWrites\(\)|'
               r'cmdbuf\.Dispatch(?:Indirect)?\(|\b(' + '|'.join(lambdas or ['$^']) + r')\(\);')
    for m in re.finditer(pattern, text):
        if m[1]:
            events += dispatch_events(lambdas[m[1]])
        elif m[0].startswith('cmdbuf.PipelineBarrier'):
            events.append(('barrier', barrier(text, m.start(), dispatch)))
        elif m[0].startswith('scheduler.NoteComputeWrites'):
            events.append(('note', None))
        else:
            events.append(('dispatch', None))
            break
    return events


indirect = next(dispatch[m.start():block_end(dispatch, m.end() - 1)]
                for m in re.finditer(r'if \(indirect_address\) \{', dispatch)
                if 'DispatchIndirect(' in dispatch[m.start():block_end(dispatch, m.end() - 1)])
direct = dispatch[dispatch.index(indirect) + len(indirect):]
begin_pass = function(scheduler_cpp, 'void Scheduler::BeginRenderPassImpl(')


def begin_render_pass(pending):
    """Barriers BeginRenderPassImpl records before vkCmdBeginRenderPass; returns (deps, pending)."""
    guards = {}
    if pending_flag:
        for m in re.finditer(r'const bool (\w+) = std::exchange\(' + pending_flag + r', false\);',
                             begin_pass):
            guards[m[1]] = pending
            pending = False
    deps = []
    end = begin_pass.index('cmdbuf.BeginRenderPass(')
    for m in re.finditer(r'cmdbuf\.PipelineBarrier\(', begin_pass[:end]):
        guard = [g for g in re.finditer(r'if \((\w+)\) \{', begin_pass[:m.start()])
                 if block_end(begin_pass, g.end() - 1) > m.start()]
        if all(guards.get(g[1], False) for g in guard):
            deps.append(barrier(begin_pass, m.start()))
    return deps, pending


for path_name, path in (('indirect', indirect), ('direct', direct)):
    events = dispatch_events(path)
    check(events and events[-1][0] == 'dispatch', f'{path_name} dispatch command not found')
    deps = [e[1] for e in events if e[0] == 'barrier']
    # A compute (or transfer) write recorded before the dispatch: indirect arguments and
    # storage data the dispatch reads.
    for writer in ('COMPUTE_SHADER', 'TRANSFER', 'FRAGMENT_SHADER'):
        check(makes_visible(deps, writer, 'SHADER_WRITE', 'DRAW_INDIRECT', 'INDIRECT_COMMAND_READ'),
              f'{path_name} dispatch: earlier {writer} writes are not visible to its indirect '
              f'argument read (dst stages must include DRAW_INDIRECT)')
        check(makes_visible(deps, writer, 'SHADER_WRITE', 'COMPUTE_SHADER', 'SHADER_READ'),
              f'{path_name} dispatch: earlier {writer} writes are not visible to the dispatch')
    pending = any(e[0] == 'note' for e in events)
    deps, pending = begin_render_pass(pending)
    for reader, read in (('DRAW_INDIRECT', 'INDIRECT_COMMAND_READ'),
                         ('VERTEX_INPUT', 'VERTEX_ATTRIBUTE_READ'),
                         ('VERTEX_SHADER', 'SHADER_READ'), ('FRAGMENT_SHADER', 'SHADER_READ')):
        check(makes_visible(deps, 'COMPUTE_SHADER', 'SHADER_WRITE', reader, read),
              f'{path_name} dispatch -> next render pass: compute writes are not visible to '
              f'{reader} ({read})')
    deps, pending = begin_render_pass(pending)
    check(not deps and not pending, 'a second render pass without a dispatch still waits for compute')

wait = function(rasterizer, 'void RasterizerVulkan::WaitForIdle()')
check('COMPUTE_SHADER' in stages('flags', wait), 'wait-for-idle source stages lost compute')


def wait_for_idle(event_signalled):
    """Dependencies of one recorded wait-for-idle; returns (deps, event state)."""
    record = wait[wait.index('scheduler.Record('):]
    deps = []
    for m in re.finditer(r'cmdbuf\.(SetEvent|ResetEvent|WaitEvents|PipelineBarrier)\(', record):
        a = call_args(record, m.start())
        if m[1] == 'SetEvent':
            # vkCmdSetEvent on an event already signalled adds no new signal to wait on.
            fresh = not event_signalled
            event_signalled = True
        elif m[1] == 'ResetEvent':
            event_signalled = False
        elif m[1] == 'WaitEvents':
            # TOP_OF_PIPE in the second scope: ALL_COMMANDS with no access. No memory barrier
            # (a[3] is the VkMemoryBarrier span) means no write is made visible.
            barriers = a[3] if len(a) > 3 else '{}'
            visible = memory_barrier(wait, barriers) if barriers not in ('{}', '') else (set(), set())
            if fresh:
                deps.append({'src': stages(a[1], wait), 'dst': stages(a[2], wait),
                             'src_access': visible[0], 'dst_access': visible[1]})
        else:
            deps.append(barrier(record, m.start(), wait))
    return deps, event_signalled


signalled = False
for wfi in (1, 2):
    deps, signalled = wait_for_idle(signalled)
    for writer in ('COMPUTE_SHADER', 'FRAGMENT_SHADER', 'TRANSFER'):
        for reader, read in (('DRAW_INDIRECT', 'INDIRECT_COMMAND_READ'),
                             ('VERTEX_INPUT', 'VERTEX_ATTRIBUTE_READ'),
                             ('COMPUTE_SHADER', 'SHADER_READ'), ('TRANSFER', 'TRANSFER_READ')):
            check(makes_visible(deps, writer, 'SHADER_WRITE', reader, read),
                  f'wait-for-idle #{wfi}: {writer} writes are not visible to a later {reader}')


def report(mode):
    if failures:
        unique = list(dict.fromkeys(failures))
        print(f'UB-083 {mode}: FAIL ({len(unique)} findings)')
        for name in dict.fromkeys(f[:f.index(']') + 1] for f in unique):
            group = [f[len(name) + 1:] for f in unique if f.startswith(name)]
            print(f'  {name} {len(group)} findings')
            for failure in group[:12] + group[12:][-8:]:
                print('    ' + failure)
        sys.exit(1)


if source_only:
    report('source model')
    print('UB-083 storage/global word split and compute ordering source model: PASS '
          '(C++ not run)')
    sys.exit(0)
assert platform.system() == 'Linux', 'compiled fixture is Linux/dedie-only'
phase[0] = 'compiled'

# --------------------------------------------------------------------------------------------
# Compiled: production emit code evaluated by a stub EmitContext.
emit_functions = []
for signature in ('Id StorageIndex(', 'Id StoragePointer(', '\nId LoadStorage(EmitContext',
                  'Id LoadStorage32(', '\nvoid WriteStorage(EmitContext', 'void WriteStorage32('):
    emit_functions.append(function(memory_cpp, signature).strip())
helper = re.search(r'(static )?bool VectorViewIsExact\(', memory_cpp)
if helper:
    emit_functions.append(memory_cpp[helper.start():block_end(memory_cpp, memory_cpp.index(
        '{', helper.start()))])
for signature in ('Id EmitLoadStorage64(', 'Id EmitLoadStorage128(', 'void EmitWriteStorage64(',
                  'void EmitWriteStorage128('):
    emit_functions.append(function(memory_cpp, signature))
global_start = global_body.index('    using DefPtr')
tie = global_body.index('define(&StorageDefinitions::U32x4')
global_helpers = global_body[global_start:global_body.index(';', tie) + 1]

fixture = r'''
#include <array>
#include <bit>
#include <bitset>
#include <cstdint>
#include <cstdio>
#include <map>
#include <span>
#include <stdexcept>
#include <tuple>
#include <utility>
#include <vector>
using u32 = std::uint32_t;
using u64 = std::uint64_t;
namespace spv {
enum class SelectionControlMask { MaskNone };
enum class FunctionControlMask { MaskNone };
}
struct NotImplementedException : std::runtime_error {
    using std::runtime_error::runtime_error;
};
static int next_id = 1;
// Every Id carries the value it evaluates to: a scalar, up to 4 components, or a pointer into a
// memory space (word offset and width). Types carry their component count or width.
struct Id {
    int id = 0;
    u64 value = 0;
    std::array<u64, 4> c{};
    u32 n = 0;
    int space = -1;
    u64 word = 0;
    u32 words = 0;
    u32 bits = 32;
};
static Id Fresh() { Id r; r.id = next_id++; return r; }
namespace IR {
struct Value {
    bool imm;
    u32 v;
    bool IsImmediate() const { return imm; }
    u32 U32() const { return v; }
};
}
struct StorageTypeDefinition { Id array; Id element; };
struct StorageDefinitions { Id U32, U32x2, U32x4; };
struct UniformDefinitions { Id U32, U32x2; };
struct Profile { bool support_descriptor_aliasing; u64 min_ssbo_alignment; bool support_int64; };
struct StorageBufferDescriptor { u32 cbuf_index; u32 cbuf_offset; };
struct Info {
    std::vector<StorageBufferDescriptor> storage_buffers_descriptors;
    std::bitset<32> nvn_buffer_used;
};
struct Access { int space; u64 word; u32 words; bool write; };

struct EmitContext {
    Profile profile{};
    std::map<int, std::vector<u32>> memory;
    std::vector<Access> accesses;
    bool oob = false;
    // Structured control flow of the global helpers: one function is evaluated (target), an
    // if-block runs when its condition held, code after a return does not run.
    int function = -1, target = -1;
    bool active = true, returned = false;
    std::map<int, bool> then_conditions;
    std::vector<Id> parameters;
    size_t next_parameter = 0;
    Id result{};

    Id U32[5], U64, U1, void_id, u32_zero_value;
    struct { StorageTypeDefinition U32, U32x2, U32x4; } storage_types;
    struct { Id U32, U32x2; } uniform_types;
    std::array<StorageDefinitions, 4> ssbos;
    std::array<UniformDefinitions, 4> cbufs;
    Id load_global_func_u32, write_global_func_u32, load_global_func_u32x2,
        write_global_func_u32x2, load_global_func_u32x4, write_global_func_u32x4;

    EmitContext(bool aliasing, u64 alignment) {
        profile = {aliasing, alignment, true};
        for (u32 n = 1; n <= 4; ++n) { U32[n] = Fresh(); U32[n].n = n == 1 ? 0 : n; }
        U64 = Fresh(); U64.bits = 64;
        U1 = Fresh(); U1.bits = 1;
        void_id = Fresh();
        u32_zero_value = Const(0u);
        storage_types.U32.element = Element(1);
        storage_types.U32x2.element = Element(2);
        storage_types.U32x4.element = Element(4);
        uniform_types.U32 = Element(1);
        uniform_types.U32x2 = Element(2);
        for (int i = 0; i < 4; ++i) {
            ssbos[i].U32 = ssbos[i].U32x2 = ssbos[i].U32x4 = Base(i);
            cbufs[i].U32 = cbufs[i].U32x2 = Base(100 + i);
        }
    }
    static Id Element(u32 words) { Id r = Fresh(); r.words = words; return r; }
    static Id Base(int space) { Id r = Fresh(); r.space = space; return r; }
    bool Live() const { return active && function == target; }
    Id Scalar(const Id& type, u64 v) {
        Id r = Fresh();
        r.value = type.bits == 64 ? v : type.bits == 1 ? u64{v != 0} : u64{static_cast<u32>(v)};
        return r;
    }
    Id Const(u32 v) { Id r = Fresh(); r.value = v; return r; }
    Id Constant(Id, u64 v) { Id r = Fresh(); r.value = v; return r; }
    Id ConstantNull(Id type) { Id r = Fresh(); r.n = type.n; return r; }
    Id Def(const IR::Value& v) { return Const(v.v); }
    Id OpShiftRightLogical(Id t, Id a, Id b) { return Scalar(t, a.value >> b.value); }
    Id OpIAdd(Id t, Id a, Id b) { return Scalar(t, a.value + b.value); }
    Id OpISub(Id t, Id a, Id b) { return Scalar(t, a.value - b.value); }
    Id OpUConvert(Id t, Id a) { return Scalar(t, a.value); }
    Id OpBitcast(Id t, Id a) { return Scalar(t, a.c[0] | a.c[1] << 32); }
    Id OpBitwiseAnd(Id t, Id a, Id b) { return Scalar(t, a.value & b.value); }
    Id OpUGreaterThanEqual(Id t, Id a, Id b) { return Scalar(t, a.value >= b.value); }
    Id OpULessThan(Id t, Id a, Id b) { return Scalar(t, a.value < b.value); }
    Id OpLogicalAnd(Id t, Id a, Id b) { return Scalar(t, a.value && b.value); }
    Id OpAccessChain(Id element, Id base, Id, Id index) {
        Id r = Fresh();
        r.space = base.space;
        r.words = element.words;
        r.word = index.value * element.words;
        return r;
    }
    Id OpLoad(Id type, Id pointer) {
        Id r = Fresh();
        r.n = type.n;
        if (!Live()) return r;
        if (pointer.space < 100) {  // constant buffers hold the binding addresses
            accesses.push_back({pointer.space, pointer.word, pointer.words, false});
        }
        auto& m = memory.at(pointer.space);
        for (u32 i = 0; i < pointer.words; ++i) {
            const u64 w = pointer.word + i;
            const u32 v = w < m.size() ? m[w] : (oob = true, 0xDEADDEADu);
            (pointer.words == 1 ? r.value : r.c[i]) = v;
        }
        return r;
    }
    void OpStore(Id pointer, Id value) {
        if (!Live()) return;
        accesses.push_back({pointer.space, pointer.word, pointer.words, true});
        auto& m = memory.at(pointer.space);
        for (u32 i = 0; i < pointer.words; ++i) {
            const u64 w = pointer.word + i;
            if (w >= m.size()) { oob = true; continue; }
            m[w] = static_cast<u32>(pointer.words == 1 ? value.value : value.c[i]);
        }
    }
    Id OpCompositeConstruct(Id, std::span<const Id> ids) {
        Id r = Fresh();
        r.n = static_cast<u32>(ids.size());
        for (size_t i = 0; i < ids.size(); ++i) r.c[i] = ids[i].value;
        return r;
    }
    template <typename... Ts>
    Id OpCompositeConstruct(Id type, Ts&&... ids) {
        const std::array<Id, sizeof...(Ts)> list{ids...};
        return OpCompositeConstruct(type, std::span<const Id>(list));
    }
    Id OpCompositeExtract(Id, Id v, u32 i) { return Const(static_cast<u32>(v.c[i])); }
    template <typename... Ts>
    Id TypeFunction(Ts&&...) { return Fresh(); }
    Id OpFunction(Id, spv::FunctionControlMask, Id) {
        ++function;
        active = true;
        returned = false;
        next_parameter = 0;
        return Fresh();
    }
    Id OpFunctionParameter(Id) {
        if (function == target && next_parameter < parameters.size()) {
            return parameters[next_parameter++];
        }
        return Fresh();
    }
    void OpFunctionEnd() {}
    Id OpLabel() { return Fresh(); }
    Id AddLabel(Id label = Fresh()) {
        const auto it = then_conditions.find(label.id);
        active = !returned && (it == then_conditions.end() || it->second);
        return label;
    }
    void OpSelectionMerge(Id, spv::SelectionControlMask) {}
    void OpBranchConditional(Id condition, Id then_label, Id) {
        then_conditions[then_label.id] = condition.value != 0;
    }
    void OpReturnValue(Id v) {
        if (Live()) result = v;
        if (active) returned = true;
        active = false;
    }
    void OpReturn() {
        if (active) returned = true;
        active = false;
    }

    void DefineGlobalHelpers(const Info& info) {
@GLOBAL@
    }
};

namespace Production {
@EMIT@
} // namespace Production

static void Print(const char* head, const EmitContext& ctx, const std::vector<u32>& values) {
    std::printf("%s ;", head);
    for (const auto& a : ctx.accesses) {
        std::printf(" %d:%llu:%u:%d", a.space, static_cast<unsigned long long>(a.word), a.words,
                    a.write ? 1 : 0);
    }
    std::printf(" ;");
    for (u32 v : values) std::printf(" %x", v);
    std::printf(" ;%s\n", ctx.oob ? " oob" : "");
}

int main() {
    for (const bool aliasing : {true, false})
    for (const u64 alignment : {4u, 8u, 16u})
    for (const u32 size : {8u, 16u})
    for (const bool write : {false, true}) {
        const auto storage = [&](bool imm, u32 off) {
            EmitContext ctx{aliasing, alignment};
            auto& m = ctx.memory[0];
            for (u32 i = 0; i < @WORDS@ * 3; ++i) m.push_back(0xA000 + i);
            const IR::Value binding{true, 0};
            const IR::Value offset{imm, off};
            std::vector<u32> values;
            if (write) {
                Id value = Fresh();
                value.n = size / 4;
                for (u32 i = 0; i < size / 4; ++i) value.c[i] = 0x5000 + i;
                if (size == 8) Production::EmitWriteStorage64(ctx, binding, offset, value);
                else Production::EmitWriteStorage128(ctx, binding, offset, value);
                values = m;
            } else {
                const Id r = size == 8 ? Production::EmitLoadStorage64(ctx, binding, offset)
                                       : Production::EmitLoadStorage128(ctx, binding, offset);
                for (u32 i = 0; i < size / 4; ++i) values.push_back(static_cast<u32>(r.c[i]));
            }
            char head[96];
            std::snprintf(head, sizeof(head), "S %d %llu %u %d %d %u", aliasing,
                          static_cast<unsigned long long>(alignment), size, write, imm, off);
            Print(head, ctx, values);
        };
        for (u32 off : {0u, 4u, 8u, 12u, 16u}) storage(true, off);
        const u32 step = alignment >= size ? size : 4;
        for (u32 off = 0; off <= 32; off += step) storage(false, off);

        const std::array<std::pair<u64, u32>, 2> buffers{@BUFFERS@};
        for (const auto& [base, length] : buffers) {
            const u64 aligned = base & ~(alignment - 1);
            for (u64 addr = base + (size - base % size) % size; addr + size <= base + length;
                 addr += size) {
                if (addr < aligned) continue;
                EmitContext ctx{aliasing, alignment};
                Info info;
                for (u32 i = 0; i < buffers.size(); ++i) {
                    info.storage_buffers_descriptors.push_back({0, 0x40 + i * 0x10});
                    info.nvn_buffer_used.set(i);
                    const u64 b = buffers[i].first & ~(alignment - 1);
                    for (u64 a = b; a < buffers[i].first + buffers[i].second; a += 4) {
                        ctx.memory[i].push_back(static_cast<u32>(a));
                    }
                }
                auto& cbuf = ctx.memory[100];
                cbuf.resize(0x100);
                for (u32 i = 0; i < buffers.size(); ++i) {
                    cbuf[0x10 + i * 4] = static_cast<u32>(buffers[i].first);
                    cbuf[0x11 + i * 4] = static_cast<u32>(buffers[i].first >> 32);
                    cbuf[0x12 + i * 4] = buffers[i].second;
                }
                // Functions: u32 load/store, u32x2 load/store, u32x4 load/store.
                ctx.target = (size == 8 ? 2 : 4) + (write ? 1 : 0);
                Id address = Fresh();
                address.value = addr;
                Id data = Fresh();
                data.n = size / 4;
                for (u32 i = 0; i < size / 4; ++i) data.c[i] = 0x5000 + i;
                ctx.parameters = {address, data};
                ctx.DefineGlobalHelpers(info);
                std::vector<u32> values;
                if (write) {
                    for (const auto& a : ctx.accesses) values = ctx.memory[a.space];
                } else {
                    for (u32 i = 0; i < size / 4; ++i) {
                        values.push_back(static_cast<u32>(ctx.result.c[i]));
                    }
                }
                char head[96];
                std::snprintf(head, sizeof(head), "G %d %llu %u %d %llx", aliasing,
                              static_cast<unsigned long long>(alignment), size, write,
                              static_cast<unsigned long long>(addr));
                Print(head, ctx, values);
            }
        }
    }
    return 0;
}
'''
fixture = (fixture.replace('@GLOBAL@', global_helpers)
           .replace('@EMIT@', '\n\n'.join(emit_functions))
           .replace('@WORDS@', str(WORDS))
           .replace('@BUFFERS@', ', '.join(f'std::pair<u64, u32>{{{b:#x}, {n:#x}}}'
                                           for b, n in GLOBAL_BUFFERS)))
build = root / 'build/nx2-tests'
build.mkdir(parents=True, exist_ok=True)
cpp = build / 'ssbo-misaligned-access.cpp'
exe = build / 'ssbo-misaligned-access'
cpp.write_text(fixture)
if '--emit-fixture' in sys.argv[1:]:
    print(cpp)
    sys.exit(0)
subprocess.run([os.environ.get('CXX', 'clang++-18'), '-std=c++20', '-O1', '-g',
                '-fsanitize=address,undefined', '-fno-sanitize-recover=all', str(cpp), '-o',
                str(exe)], check=True)
output = subprocess.run([str(exe)], check=True, capture_output=True, text=True).stdout
storage_seen = global_seen = 0
for line in output.splitlines():
    head, raw_accesses, raw_values, oob = line.split(' ;')
    fields = head.split()
    accesses = [tuple(int(x) for x in a.split(':')) for a in raw_accesses.split()]
    values = [int(v, 16) for v in raw_values.split()]
    if fields[0] == 'S':
        case = (fields[1] == '1', int(fields[2]), int(fields[3]), fields[4] == '1',
                fields[5] == '1', int(fields[6]))
        check_storage(case, [(w, n, rw == 1) for _, w, n, rw in accesses], values)
        storage_seen += 1
    else:
        case = (fields[1] == '1', int(fields[2]), int(fields[3]), fields[4] == '1',
                int(fields[5], 16))
        check_global(case, [(s, w, n, rw == 1) for s, w, n, rw in accesses], values)
        global_seen += 1
    check(not oob.strip(), f'{head}: access outside the binding')
check(storage_seen == len(list(storage_cases())) and global_seen == len(list(global_cases())),
      f'compiled fixture ran {storage_seen}/{global_seen} cases')
report('source model + compiled')
print(f'UB-083 production emit ({storage_seen} storage, {global_seen} global cases) and compute '
      'ordering model: PASS')
