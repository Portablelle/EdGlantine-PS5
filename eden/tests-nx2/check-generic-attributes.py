"""Reproduce the real inclusive attribute bound on dedie; exercise all 32 vec4s."""
from pathlib import Path
import importlib.util,platform,subprocess,tempfile
assert platform.system()=='Linux','Run on dedie'
r=Path(__file__).resolve().parents[1];cache=Path((r/'.local/headless-cache').read_text().strip())
s=(cache/'source/src/shader_recompiler/frontend/ir/attribute.h').read_text()
def fixture(s):
 start=s.index('enum class Attribute');end=s.index('[[nodiscard]] inline std::string NameOf')
 return '''#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <stdexcept>
using u32=uint32_t;using u64=uint64_t;
struct InvalidArgument:std::runtime_error{template<class... T>InvalidArgument(const char* s,T...):std::runtime_error(s){}};
'''+s[start:end]
main=r'''
int main(){
 if(OLD){assert(IsGeneric(Attribute::Generic31X));assert(!IsGeneric(Attribute::Generic31Y));assert(!IsGeneric(Attribute::Generic31Z));assert(!IsGeneric(Attribute::Generic31W));puts("BASELINE Generic31 Y/Z/W rejected");return 0;}
 for(u32 location=0;location<32;++location)for(u32 component=0;component<4;++component){
  auto attr=Attribute(u32(Attribute::Generic0X)+location*4+component);
  assert(IsGeneric(attr));assert(GenericAttributeIndex(attr)==location);assert(GenericAttributeElement(attr)==component);
 }
 for(auto raw:{u64(Attribute::Generic0X)-1,u64(Attribute::Generic31W)+1,u64(0),u64(255)}){
  auto attr=Attribute(raw);assert(!IsGeneric(attr));
  bool caught=false;try{(void)GenericAttributeIndex(attr);}catch(const InvalidArgument&){caught=true;}assert(caught);
  caught=false;try{(void)GenericAttributeElement(attr);}catch(const InvalidArgument&){caught=true;}assert(caught);
 }
 puts("PASS 128 generic components, last-slot Y/Z/W, index/component mapping and out-of-range rejection");
}
'''
with tempfile.TemporaryDirectory(prefix='generic-attributes-') as tmp:
 p=Path(tmp)
 for old in [1,0]:
  cpp=p/('old.cpp' if old else 'fixed.cpp');exe=cpp.with_suffix('');cpp.write_text(fixture(s.replace('attribute <= Attribute::Generic31W','attribute <= Attribute::Generic31X') if old else s)+main)
  subprocess.run(['c++','-std=c++20','-O1','-g','-fsanitize=address,undefined','-DOLD='+str(old),str(cpp),'-o',str(exe)],check=True)
  subprocess.run([str(exe)],check=True)
