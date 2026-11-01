from pathlib import Path
import json,sys
root=Path(__file__).resolve().parents[1]
param=json.loads((root/'sce_sys/param.json').read_text())
assert param['titleId']=='PPSA99862'
assert param['conceptId']=='99862'
assert param['contentId']=='UP9000-PPSA99862_00-EDENNX2PROTO0001'
assert param['localizedParameters']['en-US']['titleName']=='Eden NX2 Prototype'
paths=(root/'headless/storage_paths.h').read_text()
assert 'kDataDir = "/data/eden-nx2"' in paths
assert 'kInstallDir = "/data/homebrew/PPSA99862"' in paths
main=(root/'headless/main.cpp').read_text()
assert 'setenv("EDEN_NX2_MME_JIT", "1", 1)' in main
assert 'Settings::values.disable_macro_jit = true;' in main
assert 'setenv("EDEN_NX2_SPLIT", "1", 1)' in main
# The split is available, but PS5 sessions boot unarmed until an explicit request.
source=Path((root/'.local/headless-cache').read_text().strip())/'source/src/video_core'
split=(source/'gpu_split.cpp').read_text()
header=(source/'gpu_split.h').read_text()
assert '#ifdef EDEN_NX2_PS5_PROTO' in split.split('void GpuSplit::MaybeStart(',1)[1].split('static const char mode',1)[0]
assert 'if (!activation_requested.load(std::memory_order_acquire)) return;' in split
assert 'std::atomic<bool> activation_requested{};' in header
assert 'if (!active) activation_requested.store(false, std::memory_order_release);' in header
assert '            MigrateSandboxData();' not in main
for folder in ('headless','src','sce_sys'):
    for p in (root/folder).rglob('*'):
        if p.suffix not in ('.h','.hpp','.c','.cpp','.inc','.json','.cmake'):continue
        content=p.read_text()
        assert 'PPSA99071' not in content and '/data/botty' not in content,p
        assert '/data/prosperoeden' not in content,p
assert 'bool Begin() { return false; }' in (root/'headless/update_notice.cpp').read_text()
if len(sys.argv)>1:
    app=Path(sys.argv[1])
    assert app.name=='PPSA99862'
    assert json.loads((app/'sce_sys/param.json').read_text())==param
    assert not (app/'self-updater.elf').exists()
    assert json.loads((app/'lapy-manifest.json').read_text())['target_title']=='PPSA99862'
    assert not any(p.name in ('prod.keys','title.keys') or p.suffix in ('.nsp','.xci','.nca') for p in app.rglob('*'))
print('Prototype identity, paths, macro settings, disabled self-update and isolation: PASS')
