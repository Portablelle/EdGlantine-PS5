"""Do not traverse loose-game payloads or unpublished staging trees for add-ons."""
from pathlib import Path
import sys

def prepare(source):
    old='''    for (const auto& subdir : dir->GetSubdirectories()) {
        ScanDirectory(subdir);
    }'''
    assert source.count(old)==1,'Pinned ExternalContentProvider recursion changed'
    new='''    // A loose dump's payload is not an add-on library. Keep its sibling
    // updates/DLC directories searchable without walking every game asset.
    const bool loose_dump = bool(dir->GetFileRelative("exefs/main"));
    for (const auto& subdir : dir->GetSubdirectories()) {
        const auto name = subdir->GetName();
        if (!name.empty() && name.front() == '.') continue;
        if (loose_dump && (name == "romfs" || name == "exefs")) continue;
        ScanDirectory(subdir);
    }'''
    return source.replace(old,new)

if __name__=='__main__':
    source,output=map(Path,sys.argv[1:]);text=prepare(source.read_text())
    if not output.exists() or output.read_text()!=text:output.write_text(text)
