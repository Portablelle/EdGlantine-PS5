"""UB-186: source contract for PS5 copy-burst submissions (no build required).

Usage: check-copy-burst-split.py [--source-only] [SOURCE_DIR]
SOURCE_DIR contains src/; defaults to the prepared headless cache. Inspect production
CopyBuffer paths and instance state; comments alone cannot satisfy the control-flow checks.
"""
from pathlib import Path
import argparse
import re
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source-only', action='store_true', help='source checks only (the whole test)')
parser.add_argument('source', nargs='?', type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
source = args.source or Path((root / '.local/headless-cache').read_text().strip()) / 'source'
base = source / 'src/video_core/renderer_vulkan'
cpp = (base / 'vk_buffer_cache.cpp').read_text()
header = (base / 'vk_buffer_cache.h').read_text()
failures = []


def check(condition, message):
    if not condition:
        failures.append(message)


def code(text):
    return re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)


def compact(text):
    return re.sub(r'\s+', '', code(text))


def balanced(text, start, opening='{', closing='}'):
    depth = 0
    for i in range(start, len(text)):
        depth += (text[i] == opening) - (text[i] == closing)
        if depth == 0:
            return text[start:i + 1], i + 1
    raise ValueError('unbalanced production source')


def body(text, signature):
    start = text.find(signature)
    if start < 0:
        check(False, f'missing {signature}')
        return ''
    return balanced(text, text.index('{', start))[0]


def ps5_guarded(text, token):
    """Check every occurrence has an active positive PS5 guard."""
    guards = []
    found = 0
    for line in text.splitlines():
        if re.match(r'\s*#if', line):
            guards.append(bool(re.fullmatch(r'\s*#ifdef EDEN_NX2_PS5_PROTO\s*', line)))
        elif re.match(r'\s*#else|\s*#elif', line) and guards:
            guards[-1] = False
        elif re.match(r'\s*#endif', line) and guards:
            guards.pop()
        elif token in line:
            found += 1
            check(any(guards), f'{token} must be PS5-only: {line.strip()}')
    return found


production = code(cpp)
copy = body(production, 'void BufferCacheRuntime::CopyBuffer(')
helper = body(production, 'void BufferCacheRuntime::SubmitLongCopyRuns(size_t regions)')
runtime = body(code(header), 'class BufferCacheRuntime {')
check(bool(re.search(r'constexpr\s+size_t\s+COPIES_PER_SUBMISSION\s*=\s*8192\s*;', production)),
      'named default threshold must be 8192')
check('EDEN_NX2_COPIES_PER_SUBMISSION overrides' in cpp,
      'document the environment override next to the threshold')
check('cap is unverified' in cpp and 'single CopyBuffer' in cpp,
      'document unverified cap and oversized single-call residual')
check('staticconstsize_tlimit=[]' in compact(helper) and
      'std::getenv("EDEN_NX2_COPIES_PER_SUBMISSION")' in helper and
      'std::from_chars(value, end, parsed)' in helper and
      'result.ec==std::errc{}&&result.ptr==end&&parsed>0' in compact(helper) and
      'returnparsed;' in compact(helper) and 'returnCOPIES_PER_SUBMISSION;' in compact(helper),
      'helper must use a valid positive override or fall back to the default')
expected = '''
if (scheduler.CurrentTick() != copy_submission_tick) {
    copy_submission_tick = scheduler.CurrentTick();
    copy_submission_count = 0;
}
copy_submission_count += 1 + regions;
if (copy_submission_count >= limit) {
    scheduler.Flush();
    copy_submission_tick = scheduler.CurrentTick();
    copy_submission_count = 0;
}
'''
check(compact(expected) in compact(helper),
      'helper must reset on tick change, count 1 + regions, Flush at limit, then reset to new tick')
for ty, name in [('u64', 'copy_submission_tick'), ('size_t', 'copy_submission_count')]:
    check(bool(re.search(rf'^\s*{ty}\s+{name}\{{\}};', runtime, re.M)),
          f'{name} must be initialized instance state on BufferCacheRuntime')
    check(not re.search(rf'\bstatic\b[^;{{}}]*\b{name}\b', production + code(header)),
          f'{name} must not be static-shared')
check(not re.search(r'\bstatic\s+(?!const\b|constexpr\b)', helper),
      'helper must not contain static mutable counters')
check(ps5_guarded(production, 'SubmitLongCopyRuns') == 4,
      'expected helper definition and exactly three guarded calls')
ps5_guarded(code(header), 'copy_submission_')
ps5_guarded(code(header), 'SubmitLongCopyRuns')
ps5_guarded(production, 'constexpr size_t COPIES_PER_SUBMISSION')

call = 'SubmitLongCopyRuns(vk_copies.size());'
check(copy.count(call) == 3, 'all three CopyBuffer paths must count their recorded regions')
for name in ['RecordWithUploadBuffer', 'RecordUpload', 'Record']:
    marker = f'scheduler.{name}('
    check(copy.count(marker) == 1, f'expected one {name} path')
    if copy.count(marker) != 1:
        continue
    start = copy.index(marker) + len(marker) - 1
    recording, end = balanced(copy, start, '(', ')')
    check('SubmitLongCopyRuns' not in recording, f'helper must run after {name} returns')
    tail = compact(copy[end:])
    suffix = 'return;' if name != 'Record' else '}'
    check(tail.startswith(';#ifdefEDEN_NX2_PS5_PROTO' + compact(call) + '#endif' + suffix),
          f'{name} must be followed by guarded accounting before return')
    if name == 'Record':
        anchors = [
            '        if (barrier) {\n'
            '            cmdbuf.PipelineBarrier(vk::PIPELINE_STAGE_GRAPHICS_COMPUTE_TRANSFER,',
            '        cmdbuf.CopyBuffer(src_buffer, dst_buffer, VideoCommon::FixSmallVectorADL(vk_copies));',
        ]
        for anchor in anchors:
            check(recording.count(anchor) == 1 and cpp.count(anchor) == 1,
                  'pinned Record lambda anchor must occur exactly once, unchanged')

if failures:
    print('UB-186 copy-burst split: FAIL')
    for failure in failures:
        print('  ' + failure)
    sys.exit(1)
print('UB-186 copy-burst split: PASS (8192 default, env override, instance counters, three post-record paths, pinned anchors)')
