"""dedie only: verify target flags and nonzero PGO use in real native translation units."""
from pathlib import Path
import json
import platform
import re
import shlex
import subprocess
assert platform.system() == 'Linux', 'Run on dedie only'
root=Path(__file__).resolve().parents[1]
scratch=Path((root/'.local/headless-cache').read_text().strip())
build=scratch/'native-local'
commands=json.loads((build/'compile_commands.json').read_text())
out=root/'build/nx2-tests/pgo'
out.mkdir(parents=True,exist_ok=True)
profiles=set()
for entry in commands:
    command=shlex.split(entry['command'])
    flags=[a for a in command if a.startswith('-fprofile-use=')]
    # A source can belong to multiple targets; inspect the actual output target.
    target=re.search(r'CMakeFiles/([^/]+)\.dir/',entry['command'])
    expected=target and target[1] in {'video_core','shader_recompiler','dynarmic'}
    assert bool(flags)==bool(expected),(entry['file'],target[1] if target else None,flags)
    profiles.update(a.split('=',1)[1] for a in flags)
assert len(profiles)==1,profiles
profile=Path(next(iter(profiles)))
assert profile.is_file()
checks={'video_core':'/dma_pusher.cpp','shader_recompiler':'/ir_opt/constant_propagation_pass.cpp',
        'dynarmic':'/a64_emit_x64.cpp'}
results={}
for target,suffix in checks.items():
    entry=next(c for c in commands if c['file'].endswith(suffix) and f'CMakeFiles/{target}.dir/' in c['command'])
    args=shlex.split(entry['command'])
    if Path(args[0]).name=='ccache':args=args[1:]
    clean=[]
    it=iter(args)
    for arg in it:
        if arg in {'-o','-MF','-MT','-MQ'}:next(it)
        elif arg not in {'-MD','-MMD','-c','-flto=thin'}:clean.append(arg)
    output=out/(target+'.ll')
    subprocess.run(clean+['-S','-emit-llvm','-o',str(output)],cwd=entry['directory'],check=True,
                   stdout=subprocess.DEVNULL)
    ir=output.read_text()
    records={int(k):int(v) for k,v in re.findall(r'!(\d+) = !\{!"function_entry_count", i64 (\d+)',ir)}
    functions=[]
    for line in ir.splitlines():
        if line.startswith('define ') and (m:=re.search(r'!prof !(\d+)',line)):
            count=records.get(int(m[1]),0)
            if count>0:functions.append({'function':line.split('@',1)[1].split('(',1)[0],'entry_count':count})
    assert functions,f'No matching nonzero profile records were applied in {target}'
    results[target]={'functions_with_nonzero_profile':len(functions),'examples':functions[:5]}
    print(f'{target}: {len(functions)} functions with nonzero PGO entry counts',flush=True)
# Missing or invalid input must fail, and disabling PGO removes stale target flags.
fixture=out/'cmake-fixture';fixture.mkdir(exist_ok=True)
(fixture/'empty.cpp').write_text('int value;\n')
(fixture/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.22)\nproject(PGOCheck CXX)\n'
    'set(PS5_NATIVE ON)\nset(CMAKE_EXPORT_COMPILE_COMMANDS ON)\n'
    'foreach(t video_core shader_recompiler dynarmic)\nadd_library(${t} OBJECT empty.cpp)\nendforeach()\n'
    f'include("{root}/headless/pgo.cmake")\n')
cmake=['cmake','-S',str(fixture),'-B',str(fixture/'build'),'-G','Ninja','-DCMAKE_CXX_COMPILER=clang++-18']
(fixture/'bad.profdata').write_text('not a profile\n')
for path in [fixture/'missing.profdata',fixture/'bad.profdata']:
    r=subprocess.run(cmake+[f'-DEDEN_PGO_PROFILE={path}'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    assert r.returncode!=0,r.stdout
subprocess.run(cmake+[f'-DEDEN_PGO_PROFILE={profile}'],check=True,stdout=subprocess.DEVNULL)
valid=(fixture/'build/compile_commands.json').read_text();assert '-fprofile-use=' in valid
subprocess.run(cmake+['-DEDEN_PGO_PROFILE='],check=True,stdout=subprocess.DEVNULL)
assert '-fprofile-use=' not in (fixture/'build/compile_commands.json').read_text()
(out/'coverage.json').write_text(json.dumps({'profile':str(profile),'sampled_translation_units':results},indent=2)+'\n')
print('PGO flags, real native IR, invalid-input rejection and disable transition: PASS')
