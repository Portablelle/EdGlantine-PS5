"""Static capture inspection only. Does not execute guest macro code."""
import collections
import pathlib
import struct
import sys

root = pathlib.Path(sys.argv[1])

def words(path, fmt='I'):
    data = path.read_bytes()
    unit = struct.calcsize('<' + fmt)
    assert len(data) % unit == 0, path
    return list(struct.unpack('<' + fmt * (len(data) // unit), data))

for metadata in sorted(root.glob('*.txt')):
    if metadata.name.endswith('.status.txt'):
        continue
    stem = str(metadata)[:-4]
    if not pathlib.Path(stem + '.events.bin').exists():
        continue
    print(metadata.name, metadata.read_text().strip().replace('\n', ' '))
    params = words(pathlib.Path(stem + '.params.bin'))
    addresses = words(pathlib.Path(stem + '.addresses.bin'), 'Q')
    print('params', ' '.join(f'{p:08x}@{a:x}' for p, a in zip(params, addresses)))
    raw = words(pathlib.Path(stem + '.events.bin'))
    events = list(zip(raw[0::3], raw[1::3], raw[2::3]))
    print('writes', collections.Counter(a for kind, a, _ in events if kind == 1))
    print('register reads', [(hex(a), hex(v)) for kind, a, v in events if kind == 0])
    print('trace', ' '.join(f'{kind}:{a:x}={v:x}' for kind, a, v in events[:100]))
    code = words(pathlib.Path(stem + '.code.bin'))
    method = int(dict(line.split('=', 1) for line in metadata.read_text().splitlines())['method'])
    print('linear decode from entry (not control-flow analysis)')
    for pc in range(method, min(method + 48, len(code) // 3)):
        value = code[3*pc] << 64 | code[3*pc+1] << 32 | code[3*pc+2]
        field = lambda lo, n: (value >> lo) & ((1 << n)-1)
        print(f'{pc:03x} end={field(0,1)} pred={field(1,4)}/r{field(5,5)}',
              ' '.join(f'alu{i}=op{field(10+36*i,5)} r{field(15+36*i,5)}=r{field(20+36*i,5)},r{field(25+36*i,5)} imm{field(30+36*i,16):04x} out={field(82+7*i,3)}/{field(85+7*i,4)}' for i in range(2)))
