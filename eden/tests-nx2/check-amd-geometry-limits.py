"""UB-117 (d514ee0 residual): lowered passthrough geometry shaders stay within device limits.

Usage: python3 tests-nx2/check-amd-geometry-limits.py [--source-only] [SOURCE_DIR]
SOURCE_DIR contains src/; defaults to the prepared headless cache.

Source-level checks (no compilation, so --source-only is the whole test):
  * the lowered passthrough mask keeps only Position..Generic31W;
  * generic geometry outputs the fragment shader never reads are pruned, except for XFB,
    legacy or indexed varyings and natively run passthrough, and the pruning is wired into the
    geometry stage after ConvertLegacyToGeneric; stores to a pruned output are skipped;
  * a blit within one image stays in GENERAL (every dst layout use goes through dst_layout);
  * SparseLayers::MakePlan rejects a driver block that is not one page of memory.alignment,
    modelled here on the plan's own guard.
"""
from pathlib import Path
import re
import sys

args = [a for a in sys.argv[1:] if not a.startswith('--')]
root = Path(__file__).resolve().parents[1]
source = Path(args[0]).resolve() if args else Path(
    (root / '.local/headless-cache').read_text().strip()) / 'source'
failures = []


def check(condition, message):
    if not condition:
        failures.append(message)


def read(rel):
    return (source / rel).read_text()


def function_body(text, signature):
    start = text.index(signature)
    brace = text.index('{', text.index(')', start))
    depth, i = 1, brace + 1
    while depth:
        depth += (text[i] == '{') - (text[i] == '}')
        i += 1
    return text[brace:i]


# 1. Passthrough mask restricted to Position..Generic31W when lowering.
translate = read('src/shader_recompiler/frontend/maxwell/translate_program.cpp')
lower_at = translate.index('if (!normalized_host_info.support_geometry_shader_passthrough) {')
lower_block = translate[lower_at:translate.index('LowerGeometryPassthrough(program', lower_at)]
check('program.info.passthrough.mask[i] = false' in lower_block and
      'IR::Attribute::PositionX' in lower_block and 'IR::Attribute::Generic31W' in lower_block,
      'lowered passthrough does not restrict the mask to Position and the generics')

# 2. Unused generic geometry outputs are pruned, with the documented exclusions.
cache = read('src/video_core/renderer_vulkan/vk_pipeline_cache.cpp')
if 'PruneUnreadGeometryOutputs(Shader::IR::Program& geometry' not in cache:
    check(False, 'no geometry output pruning in vk_pipeline_cache.cpp')
else:
    prune = function_body(cache, 'void PruneUnreadGeometryOutputs(')
    for token, why in (('xfb_enabled', 'XFB'), ('loads_indexed_attributes', 'indexed varyings'),
                       ('fs.loads.Legacy()', 'legacy fragment inputs'),
                       ('stores.Legacy()', 'legacy geometry outputs'),
                       ('is_geometry_passthrough && native_passthrough', 'native passthrough')):
        check(token in prune, f'pruning does not bail out for {why}')
    check(re.search(r'if \(!fs\.loads\.Generic\(index\)\)', prune) and
          'stores.Set(Shader::IR::Attribute::Generic0X + index * 4 + element, false)' in prune,
          'pruning does not clear generic stores the fragment shader never loads')
    create = function_body(cache, 'std::unique_ptr<GraphicsPipeline> PipelineCache::CreateGraphicsPipeline(')
    convert = create.index('ConvertLegacyToGeneric(program, runtime_info);')
    emit = create.index('EmitSPIRV(profile, runtime_info, program, binding)')
    wired = create.find('PruneUnreadGeometryOutputs(', convert)
    check(convert < wired < emit and 'Maxwell::ShaderType::Geometry' in create[convert:wired],
          'pruning is not applied to the geometry stage between legacy conversion and emission')
    check('IsNvGeometryShaderPassthroughSupported()' in create[wired:emit],
          'pruning is not told whether passthrough runs natively')

getset = read('src/shader_recompiler/backend/spirv/emit_spirv_context_get_set.cpp')
pointer = function_body(getset, 'std::optional<OutAttr> OutputAttrPointer(')
check(re.search(r'if \(!Sirit::ValidId\(info\.id\)\) \{\s*return std::nullopt;', pointer),
      'stores to a pruned generic output are not skipped')

# 3. A blit within one image keeps it in GENERAL.
texture = read('src/video_core/renderer_vulkan/vk_texture_cache.cpp')
blit = function_body(texture, 'void TextureCacheRuntime::BlitImage(')
check(re.search(r'dst_layout\s*=\s*src_image == dst_image\s*\?\s*VK_IMAGE_LAYOUT_GENERAL\s*:\s*'
                r'VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL', blit),
      'intra-image blit does not choose GENERAL')
check('VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL' not in re.sub(
          r'dst_layout\s*=\s*src_image == dst_image\s*\?\s*VK_IMAGE_LAYOUT_GENERAL\s*:\s*'
          r'VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL', '', blit),
      'BlitImage still hardcodes TRANSFER_DST_OPTIMAL for the destination')
check(blit.count('dst_layout') >= 6, 'BlitImage does not use dst_layout for barriers and blit/resolve')

# 4. SparseLayers::MakePlan rejects a block that is not one page of memory.alignment.
sparse = read('src/video_core/renderer_vulkan/vk_sparse_layers.h')
plan = function_body(sparse, 'inline std::optional<Plan> MakePlan(')
guard = re.search(r'block_texels\s*=\s*uint64_t\{g\.width\}\s*\*\s*g\.height;\s*'
                  r'const uint64_t page_bits\s*=\s*memory\.alignment\s*\*\s*8;\s*'
                  r'if \(page_bits % block_texels \|\| page_bits / block_texels < 1 \|\| '
                  r'page_bits / block_texels > 128\)\s*return \{\};', plan)
check(guard and plan.index('block_texels') < plan.index('p.layers.resize'),
      'MakePlan does not validate the sparse block against memory.alignment before planning')
check(re.search(r'memory\.alignment > ImageBudget\)\s*return \{\};', plan),
      'MakePlan does not bound alignment before computing page bits')


def accepts(width, height, alignment):  # the guard above, executed
    texels = width * height
    bits = alignment * 8
    return alignment <= (64 << 20) and not bits % texels and 1 <= bits // texels <= 128


check(accepts(128, 128, 65536) and accepts(256, 256, 65536), 'model rejects RGBA8/BC3 pages')
check(not accepts(65549, 339860304, 65536), 'model accepts the AMD 65549x339860304 block')
check(not accepts(127, 128, 65536), 'model accepts a block that is not a whole page')

if failures:
    print('FAIL: UB-117 AMD geometry limits')
    for failure in failures:
        print(' -', failure)
    sys.exit(1)
print('OK: UB-117 AMD geometry limits')
