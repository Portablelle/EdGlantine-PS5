#!/usr/bin/env python3
"""Collect one EdGlantine run from the PS5 over FTP and summarize it.

Downloads, into a new folder:
- the core log, stderr and boot trace;
- the native shaders the translator rejected (logs/rejected-shaders/, written by default);
- the newest PPSA99862 screenshot, converted from JPEG XR to JPEG if `imagecodecs` and Pillow
  are installed.

Then it writes report.json and report.txt. They list the installed version, every rejected
native shader (address, reason, instruction words, how often), every lowered native shader with
the key that /data/eden-nx2/reject-shaders.txt takes, the last NX2_* performance lines and the
most frequent warnings.

With --scan HOST:TREE, the dumped shaders are copied to HOST (an SSH name) and run there through
tools/native-shader-scan/scan.cpp. TREE is a patched Eden source tree on HOST, such as
<build dir>/cache/ps5-eden-headless.<hash>/source. The scan lists every instruction that still
blocks, so they can all be fixed before the next console test.

    python3 eden/tools/ps5-collect.py --host 192.168.1.115 [--port 2121] [--out DIR] [--scan dedie:TREE]

Read-only on the console: it only lists and downloads.
"""
import argparse
import collections
import datetime
import ftplib
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

DATA = '/data/eden-nx2'
APP = '/data/homebrew/PPSA99862'
PHOTOS = '/user/av_contents/photo/NPXS40087/PPSA99862'
FILES = {
    'eden_log.txt': f'{DATA}/user/log/eden_log.txt',
    'stderr.log': f'{DATA}/logs/stderr.log',
    'boot-trace.txt': f'{DATA}/logs/boot-trace.txt',
}


def connect(host, port):
    ftp = ftplib.FTP()
    ftp.connect(host, port, timeout=30)
    ftp.login()
    ftp.set_pasv(True)
    return ftp


def entries(ftp, path):
    """(name, facts) of a directory; this server lists the current directory, so CWD first."""
    try:
        ftp.cwd(path)
        return [(name, facts) for name, facts in ftp.mlsd() if name not in ('.', '..')]
    except ftplib.error_perm:
        return []


def download(ftp, remote, local):
    try:
        with open(local, 'wb') as out:
            ftp.retrbinary(f'RETR {remote}', out.write)
        return True
    except ftplib.error_perm:
        Path(local).unlink(missing_ok=True)
        return False


def newest_screenshot(ftp):
    best = None
    for folder, facts in entries(ftp, PHOTOS):
        if facts.get('type') != 'dir':
            continue
        for name, file_facts in entries(ftp, f'{PHOTOS}/{folder}'):
            if name.endswith('.jxr') and (best is None or file_facts.get('modify', '') > best[0]):
                best = (file_facts.get('modify', ''), f'{PHOTOS}/{folder}/{name}')
    return best


def jxr_to_jpeg(source, target):
    try:
        import imagecodecs
        from PIL import Image
    except ImportError:
        return 'imagecodecs or Pillow missing: kept the .jxr only'
    pixels = imagecodecs.jpegxr_decode(Path(source).read_bytes())[..., :3]
    image = Image.fromarray(pixels)
    image.thumbnail((1920, 1080))
    image.save(target, quality=90)
    return None


def read_version(ftp, out):
    local = out / 'param.json'
    if download(ftp, f'{APP}/sce_sys/param.json', local):
        try:
            return json.loads(local.read_text()).get('contentVersion')
        except ValueError:
            return None
    return None


REJECTED = re.compile(r'Native shader at (0x[0-9a-f]+), instruction (0x[0-9a-f]+): (.*?)'
                      r'(?: \[([0-9a-f ]+)\])?(?: \(compute rejections so far: \d+\))?$')
LOWERED = re.compile(r'Lowered native shader at (0x[0-9a-f]+): (?:key=([0-9a-f]+), )?(\d+) source bytes, '
                     r'(\d+) instructions')
DUMPED = re.compile(r'Native shader (?:dumped \(not paused\)|paused): key=([0-9a-f]+), offset=(0x[0-9a-f]+), '
                    r'reason=(.*?), program=(0x[0-9a-f]+)')
DRAW_TRACE = re.compile(r'(NX2_(?:DRAW|DISPATCH)_TRACE) (.*)$')
LEVEL = re.compile(r'^\[\s*[\d.]+\] (\S+) <(Warning|Error|Critical)> (\S+?):\d+:\S+?: (.*)$')


TRACE_FIELD = re.compile(r'(\w+)=(\S+)')


def summarize_draw_trace(trace_lines):
    """Groups NX2_DRAW_TRACE lines by frame with one compact line per draw."""
    frames = collections.OrderedDict()
    short = gpu = 0
    for text in trace_lines:
        if text.startswith('dispatch '):
            fields = dict(TRACE_FIELD.findall(text))
            compact = (f'dispatch key={fields.get("key")} grid={fields.get("grid")} block={fields.get("block")}'
                       + (' indirect' if 'indirect=' in text else ''))
            gpu += 'gpu-modified' in text
            frames.setdefault(fields.get('frame', '?'), []).append(compact)
            continue
        head = dict(TRACE_FIELD.findall(text.split(' host=')[0].split(' indirect=')[0]))
        indexed = head.get('indexed') == 'true'
        count = head.get('index_count' if indexed else 'vertex_count')
        compact = (f'key={head.get("key")} kind={head.get("kind")} topology={head.get("topology")} '
                   f'{"indices" if indexed else "vertices"}={count} first='
                   f'{head.get("index_first" if indexed else "vertex_first")} instances={head.get("instances")}')
        if (m := re.search(r'indirect=\[address (\S+) guest (\S+) (\S+)', text)):
            compact += f' indirect={m[2]} ({m[3]})'
        streams = re.findall(r'stream(\d+)=\[gpu \S+ stride (\d+) .*?bound \S+ needs (\S+?)( SHORT)? (\S+)', text)
        for index, stride, needs, is_short, flags in streams:
            compact += f' s{index}:stride {stride} needs {needs}{" SHORT" if is_short else ""} {flags}'
        short += any(st[3] for st in streams)
        gpu += ('gpu-modified' in text) or any(st[4].startswith('G') for st in streams)
        frames.setdefault(head.get('frame', '?'), []).append(compact)
    return {'lines': len(trace_lines), 'frames': frames, 'short_streams': short, 'gpu_modified': gpu}


def summarize(out, version, screenshot, scan_output):
    log = (out / 'eden_log.txt').read_text(errors='replace') if (out / 'eden_log.txt').exists() else ''
    stderr = (out / 'stderr.log').read_text(errors='replace') if (out / 'stderr.log').exists() else ''
    rejected = {}
    lowered = {}
    keys = {}
    warnings = collections.Counter()
    draw_trace = []
    for line in log.splitlines():
        if (m := DRAW_TRACE.search(line)):
            draw_trace.append(m[2] if m[1] == 'NX2_DRAW_TRACE' else 'dispatch ' + m[2])
            continue
        if (m := REJECTED.search(line)):
            entry = rejected.setdefault(m[1], {'address': m[1], 'offset': m[2], 'reason': m[3],
                                               'words': m[4], 'count': 0})
            entry['count'] += 1
        if (m := LOWERED.search(line)):
            lowered[m[1]] = {'address': m[1], 'key': m[2], 'source_bytes': int(m[3]),
                             'instructions': int(m[4])}
        if (m := DUMPED.search(line)):
            keys[m[4]] = m[1]
        if (m := LEVEL.match(line)):
            # Numbers vary per line; count the message shape.
            warnings[f'{m[2]} {m[1]} {m[3]}: ' + re.sub(r'0x[0-9a-f]+|\d+', 'N', m[4])[:160]] += 1
    for address, key in keys.items():
        if address in rejected:
            rejected[address]['key'] = key
    perf = {}
    for line in stderr.splitlines():
        if line.startswith('NX2_') or line.startswith('EDEN_'):
            perf[line.split(' ', 1)[0]] = line
    report = {
        'collected': datetime.datetime.now().isoformat(timespec='seconds'),
        'version': version,
        'screenshot': screenshot,
        'rejected_shaders': sorted(rejected.values(), key=lambda e: -e['count']),
        'lowered_shaders': sorted(lowered.values(), key=lambda e: e['address']),
        'dumped_shaders': sorted(p.name for p in (out / 'rejected-shaders').glob('*.source.bin')),
        'last_stderr_lines': perf,
        'top_warnings': warnings.most_common(15),
        'scan': scan_output,
        'draw_trace': summarize_draw_trace(draw_trace),
    }
    if draw_trace:
        (out / 'draw-trace.txt').write_text('\n'.join(draw_trace) + '\n')
    (out / 'report.json').write_text(json.dumps(report, indent=2))
    lines = [f'EdGlantine run collected {report["collected"]}, version {version}', '']
    lines.append(f'Rejected native shaders: {len(rejected)}')
    for e in report['rejected_shaders']:
        lines.append(f'  {e["address"]} at {e["offset"]} x{e["count"]}: {e["reason"]}'
                     + (f' [{e["words"]}]' if e['words'] else '') + (f' key={e["key"]}' if e.get('key') else ''))
    lines.append(f'Lowered native shaders: {len(lowered)} (keys for reject-shaders.txt)')
    for e in report['lowered_shaders']:
        lines.append(f'  {e["address"]} key={e["key"] or "?"} {e["instructions"]} instructions')
    lines.append(f'Dumped shaders: {", ".join(report["dumped_shaders"]) or "none"}')
    lines.append(f'Screenshot: {screenshot or "none"}')
    trace = report['draw_trace']
    if trace['lines']:
        lines.append(f'Draw trace (trace-draws.txt): {trace["lines"]} draws and dispatches in {len(trace["frames"])} frames, '
                     f'full lines in draw-trace.txt')
        for frame, draws in trace['frames'].items():
            lines.append(f'  frame {frame}: {len(draws)} draws')
            lines += [f'    {d}' for d in draws[:24]]
        if trace['short_streams']:
            lines.append(f'  bound vertex streams shorter than the draw reads: {trace["short_streams"]}')
        if trace['gpu_modified']:
            lines.append(f'  draws reading GPU-modified buffers or arguments: {trace["gpu_modified"]}')
    lines.append('Most frequent warnings:')
    lines += [f'  {n:6d} {text}' for text, n in report['top_warnings']]
    if scan_output:
        lines += ['', 'Offline scan of the dumped shaders:', scan_output]
    (out / 'report.txt').write_text('\n'.join(lines) + '\n')
    return '\n'.join(lines)


def scan(out, target):
    host, _, tree = target.partition(':')
    dumps = sorted((out / 'rejected-shaders').glob('*.source.bin'))
    if not dumps:
        return 'no dumped shader to scan'
    remote = f'/tmp/edglantine-scan-{os.getpid()}'
    scanner = Path(__file__).resolve().parent / 'native-shader-scan' / 'scan.cpp'
    subprocess.run(['ssh', host, f'mkdir -p {remote}'], check=True)
    subprocess.run(['scp', '-q', str(scanner), *map(str, dumps), f'{host}:{remote}/'], check=True)
    names = ' '.join(shlex.quote(d.name) for d in dumps)
    command = (f'cd {remote} && c++ -std=c++20 -O1 -I{shlex.quote(tree)}/src scan.cpp -o scan && '
               f'./scan {names}; rm -rf {remote}')
    result = subprocess.run(['ssh', host, command], capture_output=True, text=True)
    return (result.stdout + result.stderr).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--host', default=os.environ.get('PS5_HOST'), help='PS5 address (or PS5_HOST)')
    parser.add_argument('--port', type=int, default=2121)
    parser.add_argument('--out', help='output folder (default: ps5-run-<time>)')
    parser.add_argument('--scan', metavar='HOST:TREE', help='scan dumped shaders on HOST against TREE')
    args = parser.parse_args()
    if not args.host:
        parser.error('--host or PS5_HOST is required')
    out = Path(args.out or f'ps5-run-{datetime.datetime.now():%Y%m%d-%H%M%S}')
    (out / 'rejected-shaders').mkdir(parents=True, exist_ok=True)

    ftp = connect(args.host, args.port)
    version = read_version(ftp, out)
    for name, remote in FILES.items():
        download(ftp, remote, out / name)
    for name, facts in entries(ftp, f'{DATA}/logs/rejected-shaders'):
        if facts.get('type') == 'file':
            download(ftp, f'{DATA}/logs/rejected-shaders/{name}', out / 'rejected-shaders' / name)
    screenshot = None
    if (newest := newest_screenshot(ftp)):
        local = out / Path(newest[1]).name
        if download(ftp, newest[1], local):
            screenshot = str(local)
            note = jxr_to_jpeg(local, local.with_suffix('.jpg'))
            if note is None:
                screenshot = str(local.with_suffix('.jpg'))
            else:
                print(note, file=sys.stderr)
    ftp.quit()

    scan_output = scan(out, args.scan) if args.scan else None
    print(summarize(out, version, screenshot, scan_output))
    print(f'\nWritten to {out}/ (report.json, report.txt)')


if __name__ == '__main__':
    main()
