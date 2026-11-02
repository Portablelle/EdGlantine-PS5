"""Verify layered core patches rebuild atomically and unchanged preparation is a no-op."""
from pathlib import Path
import io, platform, subprocess, tarfile, tempfile
assert platform.system() == 'Linux', 'Run on dedie'
r=Path(__file__).resolve().parents[1]
prepare=(r/'tools/prepare-build.sh').read_text().split('# Optional: seed Eden\'s package cache')[0]
with tempfile.TemporaryDirectory(prefix='eden-patch-series-') as temp:
 root=Path(temp);(root/'tools/eden-patches').mkdir(parents=True);(root/'.deps').mkdir()
 with tarfile.open(root/'.deps/eden-67bada77.tar.gz','w:gz') as archive:
  for name,data in [('CMakeLists.txt',b'fixture\n'),('src/value',b'base\n')]:
   info=tarfile.TarInfo('eden/'+name);info.size=len(data);archive.addfile(info,io.BytesIO(data))
 (root/'tools/prepare-build.sh').write_text(prepare)
 def patch(name,old,new):
  (root/'tools/eden-patches'/name).write_text('--- a/src/value\n+++ b/src/value\n@@ -1 +1 @@\n-'+old+'\n+'+new+'\n')
 patch('01-base.diff','base','first');patch('91-memory.diff','first','second')
 def run(success=True):
  p=subprocess.run(['bash','tools/prepare-build.sh'],cwd=root,env={'PATH':'/usr/bin:/bin','HOME':str(root),'XDG_CACHE_HOME':str(root/'cache')},capture_output=True,text=True)
  assert (p.returncode==0)==success,(p.returncode,p.stdout,p.stderr)
 run();source=Path((root/'.local/headless-cache').read_text().strip())/'source';value=source/'src/value'
 assert value.read_text()=='second\n';mtime=value.stat().st_mtime_ns
 run();assert value.stat().st_mtime_ns==mtime
 patch('91-memory.diff','first','updated');run();assert value.read_text()=='updated\n'
 patch('91-memory.diff','wrong','broken');run(False)
 # A failed series must not be accepted on the next preparation.
 assert not (source/'.patches-applied').exists()
 patch('91-memory.diff','first','recovered');run();assert value.read_text()=='recovered\n'
print('PASS: overlapping patch layers, unchanged-tree reuse, changed-layer rebuild, failed-series recovery.')
