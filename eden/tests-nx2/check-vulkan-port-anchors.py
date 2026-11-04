"""Run the real tools/prepare-vulkan-port.py on the prepared Eden source (all layers applied).

The console build calls it at configure time (headless/vulkan.cmake); a layer that edits one of
its pinned anchors stops the build there. This runs the same script before any build: only the
HUD shader tools are replaced by stubs, every source anchor is checked as in the build.
"""
from pathlib import Path
import os
import platform
import subprocess
import sys
import tempfile

assert platform.system() == 'Linux', 'Run on the Linux build server'
root = Path(__file__).resolve().parents[1]
if len(sys.argv) > 1:
    source = Path(sys.argv[1]).resolve()
else:
    # tools/prepare-build.sh records the tree it applied every eden-patches layer to.
    source = Path((root / '.local/headless-cache').read_text().strip()) / 'source'
assert (source / 'src/video_core/renderer_vulkan/vk_staging_buffer_pool.cpp').is_file(), source
with tempfile.TemporaryDirectory(prefix='eden-vulkan-anchors-') as temp:
    tools = Path(temp) / 'bin'
    tools.mkdir()
    # glslangValidator writes one SPIR-V word to -o; spirv-val accepts it.
    (tools / 'glslangValidator').write_text(
        '#!/bin/sh\nwhile [ $# -gt 0 ]; do [ "$1" = -o ] && printf \'\\003\\002\\043\\007\' > "$2"; shift; done\n')
    (tools / 'spirv-val').write_text('#!/bin/sh\nexit 0\n')
    for tool in tools.iterdir():
        tool.chmod(0o755)
    output = Path(temp) / 'out'
    env = dict(os.environ, PATH=f'{tools}:{os.environ.get("PATH", "/usr/bin:/bin")}')
    result = subprocess.run([sys.executable, '-B', str(root / 'tools/prepare-vulkan-port.py'),
                             str(source), str(output)], env=env, capture_output=True, text=True)
    errors = [line for line in result.stderr.splitlines() if 'anchor' in line] or result.stderr.splitlines()[-3:]
    assert result.returncode == 0, 'prepare-vulkan-port.py failed:\n' + '\n'.join(errors)
    assert (output / 'vulkan_staging_buffer_pool.cpp').is_file()
    assert (output / 'vulkan_hud_shaders.h').is_file()
    adapted = sum(1 for path in output.rglob('*.cpp'))
print(f'PASS: prepare-vulkan-port.py adapts the prepared source ({adapted} Vulkan port sources, every pinned anchor found)')
