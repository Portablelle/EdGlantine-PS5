"""Bound the pinned VFS cache and avoid 16 MiB minimum GPU descriptor tables."""
from pathlib import Path
import sys

def replace_once(text, old, new):
    assert text.count(old) == 1, (old[:100], text.count(old))
    return text.replace(old, new)

def adapt_descriptors(s):
    s=replace_once(s, '#include <algorithm>', '#include <algorithm>\n#include <bit>\n#include "descriptor_memory.h"')
    begin=s.index('        // Mario Brothership reallocates')
    end=s.index('        size_t old_size',begin)
    s=s[:begin]+'''        // Geometric growth retains spare capacity without allocating 16 MiB
        // for every tiny table. Widen before adding the inclusive last index.
        const size_t num_descriptors = std::bit_ceil(std::max<size_t>(64, size_t(limit) + 1));
'''+s[end:]
    s=replace_once(s, '        descriptors.resize(num_descriptors);', '''        descriptors.resize(num_descriptors);
        accounting.Update(descriptors.capacity() * sizeof(T) + read_descriptors.capacity() * sizeof(u64));''')
    s=replace_once(s, '    std::vector<u64> read_descriptors;', '    Eden::HostMemory::DescriptorAccounting accounting;\n    std::vector<u64> read_descriptors;')
    return s

if __name__=='__main__':
    source,port,headers=map(Path,sys.argv[1:])
    out=port/'host-memory/video_core/texture_cache/descriptor_table.h';out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(adapt_descriptors((source/'src/video_core/texture_cache/descriptor_table.h').read_text()))
