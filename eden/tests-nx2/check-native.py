"""Confirm that the final native link uses the adapted NX2 macro JIT."""
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
cache = Path((root / '.local/headless-cache').read_text().strip())
build = cache / 'native-local'
assert '-DEDEN_NX2_PS5_PROTO=1' in (build / 'build.ninja').read_text()
symbols = subprocess.check_output(
    ['nm', '-C', str(build / 'bin/eden-headless')], text=True)
assert 'Tegra::TuringMacroJit::' in symbols, 'NX2 MME JIT missing'
assert 'Tegra::MmePs5Allocator()' in symbols, 'PS5 MME allocator missing'
callbacks = [line for line in symbols.splitlines() if 'TuringMacroJit::Thunks<' in line]
assert any('Tegra::MacroEngine::Execute(' in line for line in callbacks), 'Graphics MME callbacks missing'
assert any('KeplerCompute::ProcessNativeMethod(' in line for line in callbacks), 'Compute MME callbacks missing'
assert not any('FrontRunMacro' in line for line in callbacks), 'Split-front MME unexpectedly linked'
assert 'Tegra::MacroEngine::Execute' in symbols, 'Macro execution missing'
print('Native NX2 graphics + compute MME callbacks and PS5 allocator present; split-front absent: PASS')

assert 'Vulkan::TryMakeSparseLayerImage(' in symbols, 'Sparse layer image backend missing'
# LTO can inline the small environment gate; require its option and real manager instead.
assert b'EDEN_NX2_SPARSE_LAYERS' in (build / 'bin/eden-headless').read_bytes(), 'Sparse opt-in option missing'
assert 'Vulkan::SparseLayers::Residency::Initialize(' in symbols, 'Sparse manager missing'
assert 'Vulkan::SparseLayers::Residency::Retire()' in symbols, 'Sparse retirement missing'
print('Native sparse layer backend and opt-in gate linked: PASS')

# Upstream PAuth tests alone miss the port's replacement Jit::Impl. Check the
# generated native source as well as executing that replacement in host tests.
interface = (build / 'headless/a64_interface.cpp').read_text()
assert interface.count('.enable_pauth_returns = conf.enable_pauth_returns') == 2, 'Native run/precompile lost PAuth option'
assert interface.count('.address_space_bits = conf.page_table_address_space_bits') == 2, 'Native run/precompile lost address width'
wrapper = (build / 'headless/arm_dynarmic_64.cpp').read_text()
assert 'config.enable_pauth_returns = m_cb->m_process && m_cb->m_process->UsesPAuthReturns();' in wrapper
print('Native ARM wrapper, run and precompile preserve process PAuth policy and address width: PASS')
