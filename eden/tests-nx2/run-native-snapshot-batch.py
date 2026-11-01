from pathlib import Path
import subprocess,sys
root=Path(__file__).resolve().parents[1]
source=Path(sys.argv[1])
out=root/'build/nx2-snapshot-batch';out.mkdir(parents=True,exist_ok=True)
s=(source/'src/video_core/renderer_vulkan/vk_scheduler.cpp').read_text();a=s.index('void Scheduler::QueueNativeSnapshot');b=s.index('\n#endif',a);(out/'scheduler-methods.inc').write_text(s[a:b])
s=(source/'src/video_core/renderer_vulkan/vk_buffer_cache.cpp').read_text();a=s.index('    bool overlaps_snapshot =');b=s.index('\n#endif',a);(out/'upload-guard.inc').write_text(s[a:b])
subprocess.run(['clang++-18','-std=c++20','-O1','-g','-fsanitize=address,undefined',f'-I{source}/src',f'-I{out}',str(root/'tests-nx2/native-snapshot-batch.cpp'),'-o',str(out/'test')],check=True)
subprocess.run([str(out/'test')],check=True,timeout=90)
