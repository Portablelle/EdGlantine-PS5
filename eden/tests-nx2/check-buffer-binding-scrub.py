"""UB-081: DeleteBuffer drops a deleted id from every active channel's bindings.

Usage: python3 tests-nx2/check-buffer-binding-scrub.py [--source-only] [SOURCE_DIR]
SOURCE_DIR contains src/; defaults to the prepared headless cache. This source contract
parses production function/lambda bodies; no C++ build is needed, including by default.
"""
import argparse
from pathlib import Path
import re
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source-only', action='store_true')
parser.add_argument('source', nargs='?', type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
source = args.source or Path((root / '.local/headless-cache').read_text().strip()) / 'source'
text = (source / 'src/video_core/buffer_cache/buffer_cache.h').read_text()
# Ignore comments and literals so they cannot satisfy the source assertions or affect braces.
text = re.sub(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
              '', text, flags=re.S)


def body_after(text, marker):
    start = text.index('{', text.index(marker) + len(marker))
    depth = 1
    for end in range(start + 1, len(text)):
        depth += (text[end] == '{') - (text[end] == '}')
        if depth == 0:
            return text[start + 1:end]
    raise ValueError(f'unclosed body after {marker}')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def compact(text):
    return re.sub(r'\s+', '', text)


def verify():
    body = body_after(text, 'void BufferCache<P>::DeleteBuffer(BufferId buffer_id, bool do_not_mark)')
    code = compact(body)
    require('active_channel_ids' in body and 'channel_storage' in body,
            'DeleteBuffer omits the all-channel walk; main only scrubs channel_state')
    walk = body_after(body, 'for (const size_t channel_id : active_channel_ids)')
    require(compact(walk) == 'if(&channel_storage[channel_id]!=channel_state){'
            'scrub(channel_storage[channel_id]);}',
            'every other active channel must be scrubbed exactly once')
    require('scrub(*channel_state);' in code, 'current channel is not scrubbed')
    require(code.startswith('++buffer_deletions;nx2_synced_ranges.fill({});nx2_synced_vertex_buffers.fill({});'
                            'if(buffer_id==inline_buffer_id){inline_buffer_id=NULL_BUFFER_ID;}'),
            'synced-range / inline-buffer preface changed')
    require('#ifdefEDEN_NX2_PS5_PROTOgpu_modified_ranges.ReadbackCache().Clear();#endif' in code,
            'PS5 readback-cache clear missing')
    require('ifconstexpr(requires{runtime.OnBufferDeleted(slot_buffers[buffer_id]);})'
            '{runtime.OnBufferDeleted(slot_buffers[buffer_id]);}' in code,
            'gathered-buffer OnBufferDeleted hook missing')
    ordered = ['runtime.OnBufferDeleted(slot_buffers[buffer_id]);', 'constautoscrub=',
               'scrub(*channel_state);', 'for(constsize_tchannel_id:active_channel_ids)',
               'memory_tracker.MarkRegionAsCpuModified(buffer.CpuAddr(),buffer.SizeBytes());',
               'Unregister(buffer_id);',
               'delayed_destruction_ring.Push(std::move(slot_buffers[buffer_id]));',
               'slot_buffers.erase(buffer_id);']
    positions = [code.index(token) for token in ordered]
    require(positions == sorted(positions), 'cleanup / scrub / destruction ordering changed')
    require('if(!do_not_mark){Buffer&buffer=slot_buffers[buffer_id];'
            'memory_tracker.MarkRegionAsCpuModified(buffer.CpuAddr(),buffer.SizeBytes());}' in code,
            'CPU-write marking guard changed')
    require('#ifdefYUZU_LEGACYif(!do_not_mark||!immediately_free)#endif'
            'delayed_destruction_ring.Push(std::move(slot_buffers[buffer_id]));' in code,
            'delayed-destruction guard changed')

    scalar = body_after(body, 'const auto scalar_replace = [buffer_id](Binding& binding)')
    require(compact(scalar) == 'if(binding.buffer_id==buffer_id){binding.buffer_id=BufferId{};}',
            'scalar scrub must clear matching ids and preserve other binding metadata')
    replace = body_after(body, 'const auto replace = [scalar_replace](auto& bindings)')
    require(compact(replace) == 'std::ranges::for_each(bindings,scalar_replace);',
            'generic array scrub must also support TextureBufferBinding')
    scrub = body_after(body, 'const auto scrub = [&](BufferCacheChannelInfo& channel)')
    scrub_code = compact(scrub)
    require('auto&flags=channel.maxwell3d.dirty.flags;' in scrub_code
            and 'maxwell3d->dirty.flags' not in body,
            'dirty flags must belong to the channel being scrubbed')
    index = body_after(scrub, 'if (channel.index_buffer.buffer_id == buffer_id)')
    require(compact(index) == 'channel.index_buffer.buffer_id=BufferId{};'
            'flags[Dirty::IndexBuffer]=true;', 'index binding / dirty flag scrub missing')
    vertex = body_after(scrub, 'for (u32 index = 0; index < channel.vertex_buffers.size(); index++)')
    require(compact(vertex) == 'auto&binding=channel.vertex_buffers[index];'
            'if(binding.buffer_id!=buffer_id){continue;}binding.buffer_id=BufferId{};'
            'if(&channel==channel_state){UpdateVertexBufferSlot(index,binding);}'
            'flags[Dirty::VertexBuffers]=true;flags[Dirty::VertexBuffer0+index]=true;',
            'vertex scrub must dirty matching slots and update host slots only for current channel')
    require(body.count('UpdateVertexBufferSlot(') == 1,
            'unexpected unguarded UpdateVertexBufferSlot call')
    for field in ('uniform_buffers', 'storage_buffers', 'texture_buffers'):
        require(f'std::ranges::for_each(channel.{field},replace);' in scrub_code,
                f'missing staged binding scrub: {field}')
    for field in ('transform_feedback_buffers', 'compute_uniform_buffers',
                  'compute_storage_buffers', 'compute_texture_buffers'):
        require(f'replace(channel.{field});' in scrub_code, f'missing array scrub: {field}')
    for field in ('count_buffer_binding', 'indirect_buffer_binding'):
        require(f'scalar_replace(channel.{field});' in scrub_code, f'missing scalar scrub: {field}')
    persistent = body_after(scrub, 'if constexpr (HAS_PERSISTENT_UNIFORM_BUFFER_BINDINGS)')
    require(compact(persistent) == 'channel.dirty_uniform_buffers.fill(~u32{0});'
            'channel.uniform_buffer_binding_sizes.fill({});',
            'persistent uniform binding invalidation must be per-channel')
    require('channel.has_deleted_buffers=true;' in scrub_code,
            'every scrubbed channel must record buffer deletion')
    for absent in ('read_trapped_ranges.Subtract', 'cpu_read_ranges.Subtract',
                   'InvalidateMultiRangeSegments'):
        require(absent not in body, f'Lichii-only call inserted: {absent}')


try:
    verify()
except ValueError as error:
    print(f'UB-081 buffer binding scrub: FAIL\n  {error}')
    sys.exit(1)
print('UB-081 buffer binding scrub: PASS (all active channels, all binding kinds, per-channel dirty flags; '
      'current-channel vertex update guard and gathered cleanup preserved)')
