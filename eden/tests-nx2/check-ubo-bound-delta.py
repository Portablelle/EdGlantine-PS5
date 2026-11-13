"""UB-010: constant buffer data through the bound buffer, uniform keeps and their invalidation.

Usage: python3 tests-nx2/check-ubo-bound-delta.py [--source-only] [SOURCE_DIR]
SOURCE_DIR contains src/; defaults to the prepared headless cache.

Ports Lichii 31ae51b (#1441) and 45d0fb6 (#1521) onto the effective tree, which streamed every
small uniform buffer again on every draw and wrote all constant buffer data through
WriteBlockCached's per-page translation. The production sources must show:
 - CB_DATA goes through WriteBoundConstantBuffer: the CB_ADDRESS/CB_SIZE selection is translated
   once per selection and memory map serial, buffers over texture/sampler headers, unmapped or
   sparse (non-contiguous) memory and writes past the end take the old path, and the device
   ranges written are merged and handed to InnerInvalidation by FlushCaching;
 - a draw binds an unwritten streamed uniform buffer from its earlier stream allocation in the
   same command buffer (tick) instead of reading guest memory again, never for native 64 KiB banks;
 - keeps end at every write that can reach the range (CPU/GPU writes, DMA copy and clear and inline
   uploads even when they take the fallback path), at sync points (fences, syncpoints, reports,
   acquires satisfied or not, frames, each submitted list in order on the split's back), and when
   the GPU address space differs at an equal map serial;
 - TakeDelta copies only the bind masks and the device write ranges in use.
Read from the production function bodies (no compilation, so --source-only is the whole test).
A live GpuSplit run is out of reach here.
"""
from pathlib import Path
import re
import sys

args = [a for a in sys.argv[1:] if not a.startswith('--')]
root = Path(__file__).resolve().parents[1]
source = Path(args[0]).resolve() if args else Path(
    (root / '.local/headless-cache').read_text().strip()) / 'source'
video = source / 'src/video_core'
failures = []


def check(condition, message):
    if not condition:
        failures.append(message)


def read(relative):
    path = video / relative
    return re.sub(r'//[^\n]*', '', path.read_text()) if path.exists() else ''


def body(text, signature):
    """Body of the first definition matching `signature` (a regex up to its parameter list)."""
    for match in re.finditer(signature, text):
        i = match.end()
        depth = 1  # the signature ends with the parameter list's '('
        while i < len(text):
            if text[i] == '(':
                depth += 1
            elif text[i] == ')':
                depth -= 1
            elif text[i] == ';' and depth == 0:
                break  # a declaration
            elif text[i] == '{' and depth == 0:
                start, depth = i, 1
                i += 1
                while depth and i < len(text):
                    depth += (text[i] == '{') - (text[i] == '}')
                    i += 1
                return text[start:i]
            i += 1
    return ''


def before(text, first, second):
    a, b = text.find(first), text.find(second)
    return a >= 0 and b >= 0 and a < b


cache = read('buffer_cache/buffer_cache.h')
tracker = read('buffer_cache/memory_tracker_base.h')
keep_header = read('buffer_cache/uniform_keep.h')
maxwell = read('engines/maxwell_3d.cpp')
memory = read('memory_manager.cpp')
puller = read('engines/puller.cpp')
thread = read('gpu_thread.cpp')
rasterizer = read('renderer_vulkan/vk_rasterizer.cpp')
runtime = read('renderer_vulkan/vk_buffer_cache.h')

# --- Constant buffer data through the bound buffer -------------------------------------------
cb = body(maxwell, r'void\s+Maxwell3D::ProcessCBMultiData\s*\(')
check(re.search(r'if\s*\(\s*!\s*WriteBoundConstantBuffer\s*\([^;]*\)\s*\)\s*\{[^}]*WriteBlockCached',
                cb, re.S),
      'CB_DATA is written through WriteBlockCached on every call: no bound constant buffer path '
      '(WriteBlockCached must be only the fallback of WriteBoundConstantBuffer)')
bound = body(maxwell, r'bool\s+Maxwell3D::WriteBoundConstantBuffer\s*\(')
check('MapSerial()' in bound and 'map_serial' in bound,
      'the bound buffer translation is not keyed by the memory map serial (a remap would write '
      'to stale device memory)')
check('IsContinuousRange' in bound and 'GpuToCpuAddress' in bound,
      'the bound buffer is not translated as one mapped device range (sparse/unmapped pages '
      'must take the general path)')
check('tex_header' in bound and 'tex_sampler' in bound and 'Intersects' in bound,
      'buffers over texture/sampler headers (at their GPU address or aliased device memory) do '
      'not fall back to the general path')
check(re.search(r'offset\s*\}?\s*\+\s*bytes\s*>\s*size', bound) is not None,
      'writes past the selected buffer end are not left to the general path')
check(before(bound, 'NoteDeviceData', 'WriteConstantBufferData'),
      'bound constant buffer data does not reach the draw delta before it is written')
write = body(memory, r'void\s+MemoryManager::WriteConstantBufferData\s*\(')
check('GpuWrittenPages::Mark' in write and 'WriteBlockUnsafe' in write,
      'WriteConstantBufferData does not write device memory as WriteBlockCached did')
check(re.search(r'constant_buffer_writes\.back\(\)', write) and 'std::max' in write
      and 'std::min' in write,
      'constant buffer data ranges are not merged with the previous one')
flush = body(memory, r'void\s+MemoryManager::FlushCaching\s*\(')
check(re.search(r'InnerInvalidation\([^;]*constant_buffer_writes', flush)
      and 'constant_buffer_writes.clear()' in flush,
      'FlushCaching does not hand the merged constant buffer ranges to InnerInvalidation')
cbbind = body(maxwell, r'void\s+Maxwell3D::ProcessCBBind\s*\(')
check('NoteBind' in cbbind, 'a CB_BIND does not end the slot\'s keep (delta bind mask)')

# --- Uniform keeps: rebind instead of streaming again ----------------------------------------
bind = body(cache, r'void\s+BufferCache<P>::BindHostGraphicsUniformBuffer\s*\(')
check(re.search(r'!\s*native_bank\s*&&\s*RebindKeptUniform\s*\(', bind) is not None,
      'graphics uniform binds never reuse an unwritten stream allocation (or native banks may)')
# The stream path's allocation is the last one (native root tables bind theirs earlier).
stream_at = bind.rfind('BindMappedUniformBuffer')
check(0 <= bind.find('RebindKeptUniform') < stream_at,
      'the keep is not tried before streaming the buffer again')
stream_tail = bind[stream_at:]
check(before(stream_tail, 'ReadBlockUnsafe', 'KeepStreamedUniform'),
      'a streamed uniform buffer is not remembered for later draws after its bytes were read')
check(re.search(r'keep_stream\s*=\s*false', bind) is not None,
      'a stream read back from GPU-modified memory may still be kept')
rebind = body(cache, r'bool\s+BufferCache<P>::RebindKeptUniform\s*\(')
check('CurrentTick()' in rebind and
      re.search(r'IsClean\(stage,\s*index,\s*device_addr,\s*device_addr\s*\+\s*size\)', rebind),
      'a keep is not limited to the same range in the same command buffer (tick)')
check(re.search(r'!\s*memory_tracker\.IsRegionGpuModified\(device_addr,\s*size\)', rebind),
      'a keep may bind over GPU-modified pages (GPU writes, cached writes to GPU pages)')
check(re.search(r'Forget\(stage,\s*index\)', rebind) is not None,
      'a slot bound another way stays marked clean')
check('RebindStreamUniform' in runtime and 'LastStreamUniformRef' in runtime
      and 'last_stream_uniform =' in runtime,
      'the Vulkan runtime cannot bind a stream allocation again')

# --- Keeps end where the bytes may have changed ----------------------------------------------
begin = body(cache, r'void\s+BufferCache<P>::BeginGraphicsUniforms\s*\(')
check('TakeDelta' in begin, 'the draw does not take the constant buffer delta')
check('SyncSerial()' in begin and 'sync_serial' in begin,
      'keeps survive points where the guest CPU synchronised (no sync serial)')
check(re.search(r'keep\.gpu_memory\s*==\s*gpu_memory', begin) is not None,
      'keeps compare the map serial only: another GPU address space with an equal serial keeps')
check('MapSerial()' in begin, 'keeps survive page table changes')
check('buffer_deletions' in begin and 'overflow' in begin,
      'keeps survive buffer deletions or a delta that lost writes')
check('UniformKeeps::ForgetAll()' in begin, 'an unknown delta does not end every keep')
check('binds' in begin and 'device_begin' in begin,
      'constant buffer binds or data since the previous draw do not end the keeps they reach')
update = body(cache, r'void\s+BufferCache<P>::UpdateGraphicsBuffers\s*\(')
check('BeginGraphicsUniforms' in update, 'no draw begins its uniform keeps')

note = body(cache, r'void\s+BufferCache<P>::NoteUniformWrite\s*\(')
check('UniformKeeps::NoteWrite(device_addr, size)' in note,
      'NoteUniformWrite does not end keeps over the written range')
note_write = body(keep_header, r'inline\s+void\s+NoteWrite\s*\(')
check(re.search(r'address\s*<\s*range_end\s*&&\s*begin\s*<\s*end', note_write)
      and re.search(r'mask\[stage\]\s*&=\s*~', note_write),
      'NoteWrite does not end the keeps overlapping the written range')


def notes_before(function, early):
    text = body(cache, rf'BufferCache<P>::{function}\s*\(')
    return before(text, 'NoteUniformWrite', early)


# Every write the caches hear of reaches WriteMemory -> MarkRegionAsCpuModified (InnerInvalidation,
# InvalidateRegion, OnCPUWrite, OnCacheInvalidation, ...); downloads unmark GPU-modified pages.
cpu_mark = body(tracker, r'void\s+MarkRegionAsCpuModified\s*\(')
check(before(cpu_mark, 'UniformKeeps::NoteWrite', 'IteratePages'),
      'CPU writes the buffer cache is told of do not end keeps')
check('memory_tracker.MarkRegionAsCpuModified' in body(cache, r'void\s+BufferCache<P>::WriteMemory\s*\('),
      'WriteMemory no longer marks pages CPU-modified')
gpu_unmark = body(tracker, r'void\s+UnmarkRegionAsGpuModified\s*\(')
check(before(gpu_unmark, 'UniformKeeps::NoteWrite', 'IteratePages'),
      'downloads of GPU data into guest memory do not end keeps')
check(notes_before('DMACopy', 'IsRegionRegistered'),
      'DMA copies do not end keeps (or only when the source held GPU data)')
check(notes_before('DMAClear', 'IsRegionRegistered'), 'DMA clears do not end keeps')
check(notes_before('InlineMemory', 'IsRegionRegistered'), 'inline uploads do not end keeps')
check('++buffer_deletions' in body(cache, r'void\s+BufferCache<P>::DeleteBuffer\s*\('),
      'buffer deletions are not counted for keeps')

acquire = puller[puller.find('void Puller::ProcessSemaphoreTriggerMethod'):]
acquire = acquire[acquire.find('} else {'):]
check(re.search(r'OnBack\(\s*\[\s*\]\s*\{\s*VideoCommon::UniformKeeps::NoteSync\(\);\s*\}\s*\)',
                acquire) is not None and before(acquire, 'NoteSync', 'return;'),
      'a satisfied semaphore acquire (fast return) does not end keeps in order on the back')
fence = body(puller, r'void\s+Puller::ProcessFenceActionMethod\s*\(')
check(before(fence, 'NoteSync', 'ReleaseFences'), 'a fence acquire does not end keeps')
split_part = thread[thread.find('if (split.Active())'):]
split_part = split_part[:split_part.find('continue;')]
check(re.search(r'split\.Defer\(\s*\[\s*\]\s*\{\s*VideoCommon::UniformKeeps::NoteSync', split_part)
      and before(split_part, 'NoteSync', 'scheduler.Push'),
      'a submitted list does not end keeps in order on the split\'s back')
direct = thread[thread.find('if (split.Active())'):]
direct = direct[direct.find('continue;'):]
check(before(direct, 'UniformKeeps::NoteSync()', 'scheduler.Push'),
      'a submitted list does not end keeps without the split')
for name in ('SignalFence', 'SyncOperation', 'SignalSyncPoint', 'SignalReference', 'Query',
             'TickFrame'):
    text = body(rasterizer, rf'void\s+RasterizerVulkan::{name}\s*\(')
    check('UniformKeeps::NoteSync()' in text, f'RasterizerVulkan::{name} does not end keeps')

# --- TakeDelta copies the ranges in use only -------------------------------------------------
take = body(keep_header, r'inline\s+void\s+TakeDelta\s*\(')
check(bool(take), 'no TakeDelta: the draw delta is not taken by its ranges in use')
copies = re.findall(r'std::copy_n\([^,]+,\s*([^,]+),', take)
check(len(copies) == 2 and all('num_device_writes' in c for c in copies),
      f'TakeDelta does not bound its range copies by the count in use: {copies}')
check(not re.search(r'\bout\s*=\s*(delta|g_delta)\b|std::exchange\s*\(\s*g_delta'
                    r'|out\.device_(begin|end)\s*=', take),
      'TakeDelta copies the whole delta (or whole range arrays)')
check(re.search(r'out\.binds\s*=\s*delta\.binds', take) and 'out.overflow' in take,
      'TakeDelta does not move the bind masks and the overflow flag')
check(re.search(r'delta\.num_device_writes\s*=\s*0', take) and 'delta.binds = {}' in take,
      'TakeDelta does not clear the taken counts')
note_data = body(keep_header, r'inline\s+void\s+NoteDeviceData\s*\(')
check('overflow = true' in note_data, 'a full delta does not mark itself lost')

if failures:
    print('UB-010 UBO bound buffer writes and uniform keeps: FAIL')
    for f in failures:
        print('  ' + f)
    sys.exit(1)
print('UB-010 UBO bound buffer writes and uniform keeps: PASS')
