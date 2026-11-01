#!/usr/bin/env python3
"""Compare the actual HLE entry against the interpreter through a recording backend."""
from pathlib import Path
import os,subprocess,sys,tempfile
root=Path(__file__).resolve().parents[1]
core=Path(sys.argv[1])
source=(core/'src/video_core/native_draw_hle.h').read_text()
# Compile the unchanged production namespace; replace only external engine dependencies.
body=source[source.index('namespace Tegra::NativeDrawHle {'):source.rindex('#endif')]
with tempfile.TemporaryDirectory(prefix='nx2-draw-production-') as directory:
    temp=Path(directory)
    (temp/'production-native-draw-hle.inc').write_text(body)
    subprocess.run([os.environ.get('CXX','clang++'),'-std=c++20','-O1','-g','-fsanitize=address,undefined','-I',str(temp),'-I',str(core/'src'),str(root/'tests-nx2/native-draw-indirect.cpp'),'-o',str(temp/'test')],check=True)
    subprocess.run([str(temp/'test')],check=True)
