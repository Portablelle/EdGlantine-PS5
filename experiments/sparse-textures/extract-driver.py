from pathlib import Path
import hashlib,json,sys
mesa=Path(sys.argv[1]); out=Path(sys.argv[2]); out.mkdir(parents=True,exist_ok=True)
queue=mesa/'src/amd/vulkan/radv_queue.c'
platform=mesa/'src/amd/vulkan/winsys/ps5/radv_ps5_platform.c'
formats=mesa/'src/amd/vulkan/radv_formats.c'
chunks=[]
for path,names in [(queue,['radv_sparse_buffer_bind_memory','radv_sparse_image_opaque_bind_memory','radv_sparse_image_bind_memory','radv_queue_submit_bind_sparse_memory']),(platform,['radv_ps5_vrange_bind','radv_ps5_vrange_unbind']),(formats,['fill_sparse_image_format_properties'])]:
    text=path.read_text()
    for name in names:
        start=text.index('\n'+name+'(')
        start=text.rfind('\n',0,start)+1
        if text[max(0,start-7):start]=='static ': start-=7
        brace=text.index('{',start); depth=1; end=brace+1
        while depth:
            depth += (text[end]=='{')-(text[end]=='}'); end+=1
        chunks.append(text[start:end])
(out/'driver-test.c').write_text('#include "driver-harness.h"\n'+'\n'.join(chunks)+'\n#include "driver-tests.c"\n')
(out/'source-hashes.json').write_text(json.dumps({str(p.relative_to(mesa)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (queue,platform,formats)},indent=2)+'\n')
