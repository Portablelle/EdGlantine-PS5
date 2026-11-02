"""Generate the final shader environment once, from canonical core sources."""
from pathlib import Path
import importlib.util, sys
source, target, port, native = sys.argv[1:]
port = Path(port)
text = Path(source).read_text()
begin = text.index('void LoadPipelines(')
end = text.rindex('} // namespace VideoCommon')
text = '#include <cstdio>\n#include <new>\n#include <stdexcept>\n#include <system_error>\n' + text[:begin] + '#include "' + str(port/'shader_cache_reader.inc') + '"\n\n' + text[end:]
if native == 'ON':
    spec = importlib.util.spec_from_file_location('native_policy', Path(__file__).with_name('prepare-native-shader-policy.py'))
    policy = importlib.util.module_from_spec(spec); spec.loader.exec_module(policy)
    text = policy.shader_environment(text)
target = Path(target)
if not target.exists() or target.read_text() != text: target.write_text(text)
