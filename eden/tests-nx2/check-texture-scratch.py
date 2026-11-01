#!/usr/bin/env python3
"""Test the patched production lowerer using unchanged headers from a prepared core."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
core = Path(sys.argv[1])
patch = (root / 'tools/eden-patches/90-nx2-prototype.diff').read_text()
relative = 'src/shader_recompiler/frontend/ampere/lower_to_maxwell.h'
section = patch.split(f'diff --git a/{relative} b/{relative}\n', 1)[1].split('\ndiff --git ', 1)[0]
body = section.split('@@\n', 1)[1]
header = ''.join(line[1:] + '\n' for line in body.splitlines() if line.startswith('+'))
with tempfile.TemporaryDirectory(prefix='nx2-texture-scratch-') as directory:
    temp = Path(directory)
    overlay = temp / relative
    overlay.parent.mkdir(parents=True)
    overlay.write_text(header)
    binary = temp / 'test'
    subprocess.run([os.environ.get('CXX', 'clang++'), '-std=c++20', '-O1', '-g',
                    '-fsanitize=address,undefined', '-I', str(temp / 'src'),
                    '-I', str(core / 'src'), str(root / 'tests-nx2/native-texture-scratch.cpp'),
                    '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
