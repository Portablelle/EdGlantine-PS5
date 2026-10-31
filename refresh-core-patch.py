from pathlib import Path
import subprocess
r=Path(__file__).parent
subprocess.run(['git','add','-N','.'],cwd=r/'core',check=True)
(r/'eden/tools/eden-patches/90-nx2-prototype.diff').write_bytes(subprocess.check_output(['git','diff','HEAD','--','src'],cwd=r/'core'))
