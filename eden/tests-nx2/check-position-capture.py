"""Exercise the canonical core capture gate after removing the source rewriter."""
from pathlib import Path
import platform,subprocess,tempfile
assert platform.system()=='Linux','Run on dedie'
r=Path(__file__).resolve().parents[1];source=Path((r/'.local/headless-cache').read_text().strip())/'source/src'
with tempfile.TemporaryDirectory(prefix='position-gate-') as temp:
 exe=Path(temp)/'check'
 subprocess.run(['c++','-std=c++20','-O1','-g','-fsanitize=address,undefined','-I'+str(source),str(r/'tests-nx2/position-capture-gate.cpp'),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
