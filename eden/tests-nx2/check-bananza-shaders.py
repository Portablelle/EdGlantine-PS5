"""Exercise real captured Bananza shaders and focused half/barrier semantics on dedie."""
from pathlib import Path
import importlib.util,platform,subprocess,sys,tempfile
assert platform.system()=='Linux','Run on dedie'
r=Path(__file__).resolve().parents[1];cache=Path((r/'.local/headless-cache').read_text().strip());source=cache/'source/src'
with tempfile.TemporaryDirectory(prefix='bananza-shaders-') as tmp:
 t=Path(tmp);rel=Path('shader_recompiler/frontend/ampere/lower_to_maxwell.h');(t/rel).parent.mkdir(parents=True)
 (t/rel).write_text((source/rel).read_text())
 subprocess.run(['c++','-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer','-I'+str(t),'-I'+str(source),str(r/'tests-nx2/bananza-shaders.cpp'),'-o',str(t/'check')],check=True)
 subprocess.run([str(t/'check'),*sys.argv[1:]],check=True)
