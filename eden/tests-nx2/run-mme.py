from pathlib import Path
import subprocess
root=Path(__file__).resolve().parents[1]
cache=Path((root/'.local/headless-cache').read_text().strip())
source=cache/'source'
includes=[cache/'native-local/headless/include',source/'src',source/'externals/fmt/include']
includes+=list((source/'.cache/cpm/boost/1.92.0/libs').glob('*/include'))
includes+=list((source/'.cache/cpm/fmt').glob('*/include'))
out=root/'build/nx2-tests/mme-jit';out.parent.mkdir(parents=True,exist_ok=True)
subprocess.run(['clang++-18','-std=c++20','-O1','-g','-DEDEN_NX2_PS5_PROTO=1','-fsanitize=address,undefined','-fno-sanitize=function',*[f'-I{p}' for p in includes],str(root/'tests-nx2/mme-jit.cpp'),'-o',str(out)],check=True)
subprocess.run([str(out)],check=True,timeout=60)
