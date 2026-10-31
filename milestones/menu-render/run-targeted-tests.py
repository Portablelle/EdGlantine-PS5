"""Compile the two focused tests and reuse existing host libraries on build-server."""
import json
from pathlib import Path
import shlex
import subprocess

build = Path('/work/cache/ns2-host-tests')
folder = Path('/work/experiments/menu-render')
entry = next(x for x in json.loads((build / 'compile_commands.json').read_text())
             if x['file'].endswith('/tests/video_core/native_shader.cpp'))
args = shlex.split(entry['command'])
args[args.index('-o')+1] = str(folder / 'focused-tests.o')
args[args.index('-c')+1] = str(folder / 'focused-tests.cpp')
subprocess.run(args, cwd=entry['directory'], check=True)
link = subprocess.check_output(['ninja', '-t', 'commands', 'bin/tests'], cwd=build, text=True).splitlines()[-1]
link = link.replace('src/tests/CMakeFiles/tests.dir/video_core/native_shader.cpp.o', str(folder/'focused-tests.o'))
link = link.replace('-o bin/tests', '-o '+str(folder/'focused-tests'))
subprocess.run(link, cwd=build, shell=True, check=True)
subprocess.run([str(folder/'focused-tests'), '--reporter', 'compact', '[welcome-menu]'], check=True)
