"""The memory reports run every 5 s, and say what images and staging buffers actually hold.

Issue #20: Mario Kart World loads at ~20 fps and the console's shared pool ran out ~100 s after
the app started. The texture and buffer cache reports ran every 600 frames (~30 s at that rate)
and never came before the crash, and the texture cache only counted an estimate of its images
from their guest size. Layer 99zh: both reports also run every 5 s; the texture cache report adds
EDEN_MEMORY_IMAGES (estimated vs allocated bytes, compute unswizzle buffers, unbacked images) and
the allocated size of its largest images; the Vulkan statistics add the staging pool's kept
buffers per kind (StagingBufferPool::LogHeld). Checks the prepared source and the generated
texture cache. Fails without layer 99zh.
"""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
if len(sys.argv) > 1:
    source = Path(sys.argv[1]).resolve()
else:
    source = Path((root / '.local/headless-cache').read_text().strip()) / 'source'
src = source / 'src'
cache = (src / 'video_core/texture_cache/texture_cache.h').read_text()
if 'EDEN_MEMORY_IMAGES' not in cache:
    print('FAIL: the texture cache report runs every 600 frames only and counts estimates (no EDEN_MEMORY_IMAGES)')
    sys.exit(1)
for needed in ('std::chrono::seconds{5}', 'image->HostImageBytes()', 'image->UnswizzleBufferBytes()',
               'ImageFlagBits::Unbacked', 'runtime.LogMemoryStatistics()'):
    assert needed in cache, 'Texture cache report lacks: ' + needed
buffers = (src / 'video_core/buffer_cache/buffer_cache.h').read_text()
assert 'std::chrono::seconds{5}' in buffers and '#include <chrono>' in buffers, 'Buffer cache report is not timed'
image = (src / 'video_core/renderer_vulkan/vk_texture_cache.h').read_text()
assert 'original_image.GetMemoryBlock().size + scaled_image.GetMemoryBlock().size' in image
runtime = (src / 'video_core/renderer_vulkan/vk_texture_cache.cpp').read_text()
assert 'staging_buffer_pool.LogHeld();' in runtime, 'Vulkan statistics do not report the staging pool'
pool = (src / 'video_core/renderer_vulkan/vk_staging_buffer_pool.cpp').read_text()
# Layer 99zj and headless/main.cpp: the most refreshed images per report, and the descriptor
# buffer A/B switch that any build reads (Pokopia's sprites swapping places for a frame).
for needed in ('EDEN_REFRESHES images=', 'EDEN_REFRESH gpu=', 'refresh_counts.clear();', 'refresh.frames +='):
    assert needed in cache, 'Texture cache report lacks: ' + needed
main = (root / 'headless/main.cpp').read_text()
switch = main.index('/descriptor-buffer-off.txt')
assert main.rfind('#ifdef EDEN_DEV_PROFILE', 0, switch) < main.rfind('#endif', 0, switch), \
    'The descriptor buffer switch is read in development builds only'
assert 'void StagingBufferPool::LogHeld() const {' in pool

with tempfile.TemporaryDirectory(prefix='eden-memory-breakdown-') as temp:
    temp = Path(temp)
    tools = temp / 'bin'
    tools.mkdir()
    (tools / 'glslangValidator').write_text(
        '#!/bin/sh\nwhile [ $# -gt 0 ]; do [ "$1" = -o ] && printf \'\\003\\002\\043\\007\' > "$2"; shift; done\n')
    (tools / 'spirv-val').write_text('#!/bin/sh\nexit 0\n')
    for tool in tools.iterdir():
        tool.chmod(0o755)
    env = dict(os.environ, PATH=f'{tools}:{os.environ.get("PATH", "/usr/bin:/bin")}')
    subprocess.run([sys.executable, '-B', str(root / 'tools/prepare-vulkan-port.py'), str(source), str(temp / 'out')],
                   env=env, check=True, capture_output=True)
    generated = (temp / 'out/vulkan-cache/video_core/texture_cache/texture_cache.h').read_text()
    assert 'EDEN_MEMORY_IMAGES' in generated and 'std::chrono::seconds{5}' in generated
    assert 'LogHeld' in (temp / 'out/vulkan_staging_buffer_pool.cpp').read_text()
print('PASS: texture and buffer cache reports every 5 s, with allocated image bytes and the staging pool held')
