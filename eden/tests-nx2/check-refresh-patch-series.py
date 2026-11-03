"""Verify this batch reproduces the built source from the pinned archive."""
from pathlib import Path
import platform, re, subprocess, tempfile

assert platform.system() == 'Linux', 'Run on dedie'
root = Path(__file__).resolve().parents[1]
source = Path((root / '.local/headless-cache').read_text().strip()) / 'source'
patches = sorted((root / 'tools/eden-patches').glob('*.diff'))
with tempfile.TemporaryDirectory(prefix='eglantine-series-') as temporary:
    tree = Path(temporary)
    subprocess.run(['tar','-xzf',str(root/'.deps/eden-67bada77.tar.gz'),
                    '--strip-components=1','-C',str(tree)],check=True)
    for patch in patches:
        with patch.open('rb') as stream:
            subprocess.run(['patch','-p1','-N','-s','-f'],cwd=tree,stdin=stream,check=True)
    paths = re.findall(r'^\+\+\+ b/(.+)$', patches[-1].read_text(), re.M)
    assert paths and patches[-1].name == '99i-eglantine-coherence-memory.diff'
    for path in paths:
        assert (tree/path).read_bytes() == (source/path).read_bytes(), path
    print(f'PASS full ordered patch series; {len(paths)} refresh files match the build source')
