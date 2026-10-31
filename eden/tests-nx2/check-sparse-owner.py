"""Exercise the real vk::Image move/reset ownership and production Release body."""
from pathlib import Path
import subprocess
root=Path(__file__).resolve().parents[1]
scratch=Path((root/'.local/headless-cache').read_text().strip())
source=scratch/'source/src'
out=root/'build/nx2-tests/sparse-owner'
out.mkdir(parents=True,exist_ok=True)
# Header-only wrapper tests need no host window-system APIs.
vulkan=source/'video_core/vulkan_common/vulkan.h'
shim=out/'include/video_core/vulkan_common/vulkan.h'
shim.parent.mkdir(parents=True,exist_ok=True)
shim.write_text(vulkan.read_text().replace('#define VK_USE_PLATFORM_XLIB_KHR','// no Xlib in this test').replace('#define VK_USE_PLATFORM_WAYLAND_KHR','// no Wayland in this test'))
text=(source/'video_core/vulkan_common/vulkan_wrapper.cpp').read_text()
start=text.index('void Image::Release() const noexcept {')
end=text.index('\nvoid Buffer::Flush()',start)
body=text[start:end]
(out/'test.cpp').write_text('''#include <cassert>
#include "video_core/vulkan_common/vulkan_wrapper.h"
static unsigned ordinary_releases;
void vmaDestroyImage(VmaAllocator, VkImage, VmaAllocation) { ++ordinary_releases; }
namespace Vulkan::vk {
'''+body+'''
}
using namespace Vulkan::vk;
struct Backing final : ImageBacking { unsigned calls{}; void Release() noexcept override { ++calls; } };
int main() {
 DeviceDispatch dispatch{};
 auto backing=std::make_shared<Backing>();
 {
  Image first{(VkImage)1,0,nullptr,nullptr,nullptr,dispatch,backing};
  assert(!first.IsUnbacked());
  Image second{std::move(first)};assert(!first && second);
  Image third;third=std::move(second);assert(!second && third);
  third=std::move(third);assert(third && backing->calls==0);
  third.reset();assert(!third && backing->calls==1);
 }
 assert(backing->calls==1 && ordinary_releases==0);
 {
  Image ordinary{(VkImage)2,0,nullptr,nullptr,nullptr,dispatch};
  assert(ordinary.IsUnbacked());
 }
 assert(ordinary_releases==1);
 auto other=std::make_shared<Backing>();
 {
  Image a{(VkImage)3,0,nullptr,nullptr,nullptr,dispatch,backing};
  Image b{(VkImage)4,0,nullptr,nullptr,nullptr,dispatch,other};
  a=std::move(b); assert(backing->calls==2 && other->calls==0);
 }
 assert(backing->calls==2 && other->calls==1);
}
''')
subprocess.run(['clang++-18','-std=c++20','-O1','-g','-fsanitize=address,undefined','-I'+str(out/'include'),'-I'+str(source),'-I/work/mihawk-vulkan-review/.deps/native/radv-release/include',str(out/'test.cpp'),'-o',str(out/'test')],check=True)
subprocess.run([str(out/'test')],check=True)
print('Sparse vk::Image ownership: move, replace, self-move, reset, ordinary fallback and single release PASS')
