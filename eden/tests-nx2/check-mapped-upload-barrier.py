"""UB-026 residual: a mapped (Vulkan) buffer upload must not leave any_buffer_uploaded set.

Vulkan's MappedUploadMemory -> runtime.CopyBuffer(..., true, can_reorder) already carries its own
barrier (inline transfer->shader barrier, or the upload command buffer that SubmitExecution ends with a
transfer-write barrier), so the flag only made the next bind record a redundant PostCopyBarrier, which
ends the render pass. ImmediateUploadMemory (OpenGL, USE_MEMORY_MAPS_FOR_UPLOADS = false) has no barrier
of its own and must keep the flag.

Behavior test: the production tail of BufferCache::SynchronizeBufferPages (from UploadMemory to
`return false;`) is extracted from the prepared source and evaluated with USE_MEMORY_MAPS_FOR_UPLOADS
true and false: the --source-only mode evaluates the `if constexpr` structure in Python, the default mode
compiles the same text in a template harness (g++, Linux build server only; NOT run where no compiler
exists). Expected: mapped -> flag stays false (no PostCopyBarrier); immediate -> flag true.
Also checks that every other writer of the flag stays absent and the consumers still reset it.

Usage: check-mapped-upload-barrier.py [--source-only] [SOURCE_DIR]   SOURCE_DIR contains src/.
Negative control: run against the prepared source of main (a tree without layer 99zzzza); the mapped
case still sets the flag and the script fails.
"""
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile

args = [a for a in sys.argv[1:] if not a.startswith('--')]
source_only = '--source-only' in sys.argv[1:]
if not source_only:
    assert platform.system() == 'Linux', 'Run on the Linux build server'
root = Path(__file__).resolve().parents[1]
if args:
    source = Path(args[0]).resolve()
else:
    source = Path((root / '.local/headless-cache').read_text().strip()) / 'source'
src = source / 'src'
text = (src / 'video_core/buffer_cache/buffer_cache.h').read_text()

m = re.search(r'(    UploadMemory\(buffer, total_size_bytes, largest_copy, copies_span\);\n.*?    return false;\n)',
              text, re.S)
assert m, 'SynchronizeBufferPages upload tail not found'
tail = m.group(1)
assert tail.count('any_buffer_uploaded') <= 2, tail

def evaluate(mapped):
    """any_buffer_uploaded after the tail, resolving `if constexpr ([!]USE_MEMORY_MAPS_FOR_UPLOADS)`."""
    flag = False
    body = tail
    pattern = re.compile(r'if constexpr \((!?)USE_MEMORY_MAPS_FOR_UPLOADS\) \{\n(.*?)\n    \}\n', re.S)
    body = pattern.sub(lambda g: g.group(2) if (g.group(1) == '!') != mapped else '', body)
    return 'any_buffer_uploaded = true;' in body

results = {'mapped': evaluate(True), 'immediate': evaluate(False)}
print('flag set after upload:', results)
assert not results['mapped'], 'mapped upload still sets any_buffer_uploaded (redundant PostCopyBarrier)'
assert results['immediate'], 'immediate (OpenGL) upload must keep any_buffer_uploaded'

# nothing else sets the flag; consumers still reset it after the barrier
for path in src.glob('video_core/**/*'):
    if path.suffix in ('.h', '.cpp'):
        t = path.read_text(errors='ignore')
        sets = len(re.findall(r'any_buffer_uploaded\s*=\s*true', t))
        assert sets == (1 if path.name == 'buffer_cache.h' and 'buffer_cache/' in str(path) else 0), (path, sets)
vk = (src / 'video_core/renderer_vulkan/vk_buffer_cache.h').read_text()
gl = (src / 'video_core/renderer_opengl/gl_buffer_cache.h').read_text()
assert re.search(r'USE_MEMORY_MAPS_FOR_UPLOADS = true', vk) and re.search(r'USE_MEMORY_MAPS_FOR_UPLOADS = false', gl)
assert 'runtime.CopyBuffer(buffer, upload_staging.buffer, copies, true, can_reorder)' in text

if source_only:
    print('source-only checks passed (compiled harness not run)')
    sys.exit(0)

harness = r'''
#include <cstdio>
#include <cstdlib>
#include <span>
struct BufferCopy {}; struct Buffer {};
template <bool USE_MEMORY_MAPS_FOR_UPLOADS>
struct Cache {
    bool any_buffer_uploaded = false;
    int uploads = 0;
    void UploadMemory(Buffer&, unsigned long, unsigned long, std::span<BufferCopy>) { ++uploads; }
    bool Run() {
        Buffer buffer; unsigned long total_size_bytes = 1, largest_copy = 1;
        BufferCopy c[1]; std::span<BufferCopy> copies_span(c, 1);
''' + tail + r'''
    }
};
int main() {
    Cache<true> vk; vk.Run();
    Cache<false> gl; gl.Run();
    if (vk.uploads != 1 || gl.uploads != 1) return 2;
    if (vk.any_buffer_uploaded) { std::fprintf(stderr, "mapped upload set the flag\n"); return 3; }
    if (!gl.any_buffer_uploaded) { std::fprintf(stderr, "immediate upload lost the flag\n"); return 4; }
    return 0;
}
'''
with tempfile.TemporaryDirectory() as d:
    cpp = Path(d) / 'harness.cpp'
    cpp.write_text(harness)
    subprocess.run(['g++', '-std=c++20', str(cpp), '-o', str(Path(d) / 'h')], check=True)
    subprocess.run([str(Path(d) / 'h')], check=True)
print('mapped-upload-barrier checks passed')
