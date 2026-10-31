"""Compare matching output-frame intervals from bounded prototype logs."""
import json
import pathlib
import re
import sys


def sample(folder, first=90, last=570):
    folder = pathlib.Path(folder)
    frames = {}
    for line in (folder / 'eden_log.txt').read_text().splitlines():
        if 'NX2_VIDEO_PERF frames=' not in line:
            continue
        values = dict(re.findall(r'(\w+)=([^ ,]+)', line))
        values['seconds'] = float(re.match(r'\[\s*([\d.]+)\]', line)[1])
        frames[int(values['frames'])] = values
    a, b = frames[first], frames[last]
    count = last - first
    return {
        'firstFrame': first, 'lastFrame': last, 'frames': count,
        'dimensions': b['dimensions'], 'nv12': b['nv12'],
        'seconds': b['seconds'] - a['seconds'],
        'outputFps': count / (b['seconds'] - a['seconds']),
        'millisecondsPerFrame': {
            key: (int(b[key]) - int(a[key])) / count / 1e6
            for key in b if key.endswith('_ns')
        },
    }


if __name__ == '__main__':
    before, after = map(sample, sys.argv[1:3])
    print(json.dumps({
        'baseline010': before, 'optimized011': after,
        'conversionSpeedup': before['millisecondsPerFrame']['convert_ns'] / after['millisecondsPerFrame']['convert_ns'],
        'outputFpsSpeedup': after['outputFps'] / before['outputFps'],
    }, indent=2))
