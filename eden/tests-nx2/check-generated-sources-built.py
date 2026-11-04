"""Every .cpp that tools/prepare-vulkan-port.py generates is in the build, in place of its Eden source.

The script writes its adaptations to ${PORT_BUILD_DIR}; only headless/*.cmake put them in the build.
A generated file no list names is left out without a word and Eden's original is compiled instead:
the staging buffer pool's adaptation (headless/staging_buffers.h) was never in the console binary,
from the publication commit to issue #20. Reads the two sources only; runs anywhere.
"""
from pathlib import Path
import ast
import re

root = Path(__file__).resolve().parents[1]


def strings(node, scope):
    """The strings an expression of the script can be, with the loop variables in `scope`."""
    if isinstance(node, ast.Constant):
        return [node.value] if isinstance(node.value, str) else []
    if isinstance(node, ast.Name):
        return scope.get(node.id, [])
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return [a + b for a in strings(node.left, scope) for b in strings(node.right, scope)]
    if isinstance(node, ast.IfExp):
        test = node.test  # `name == 'text'` is decided when the loop gives `name` one value
        if (isinstance(test, ast.Compare) and isinstance(test.ops[0], ast.Eq)
                and len(left := strings(test.left, scope)) == 1 and len(right := strings(test.comparators[0], scope)) == 1):
            return strings(node.body if left == right else node.orelse, scope)
        return strings(node.body, scope) + strings(node.orelse, scope)
    if isinstance(node, ast.FormattedValue):
        return strings(node.value, scope)
    if isinstance(node, ast.JoinedStr):
        texts = ['']
        for part in node.values:
            texts = [a + b for a in texts for b in strings(part, scope)]
        return texts
    return []


def generated(statements, scope, found):
    """Adds (destination, Eden source or None) for each .cpp the statements write."""
    for statement in statements:
        if isinstance(statement, ast.FunctionDef):
            continue
        if isinstance(statement, ast.For) and isinstance(statement.iter, (ast.Tuple, ast.List)):
            for item in statement.iter.elts:
                names = statement.target.elts if isinstance(statement.target, ast.Tuple) else [statement.target]
                items = item.elts if isinstance(item, ast.Tuple) else [item]
                inner = dict(scope)
                for name, value in zip(names, items):
                    if isinstance(name, ast.Name):
                        inner[name.id] = strings(value, scope)
                generated(statement.body, inner, found)
            continue
        if isinstance(statement, ast.Assign) and isinstance(statement.targets[0], ast.Name):
            scope[statement.targets[0].id] = strings(statement.value, scope)
        for node in ast.walk(statement):
            if isinstance(node, ast.Call) and getattr(node.func, 'id', '') == 'adapt':
                for source in strings(node.args[0], scope):
                    found |= {(d, source) for d in strings(node.args[1], scope) if d.endswith('.cpp')}
            elif (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
                  and getattr(node.left, 'id', '') == 'output'):
                found |= {(d, None) for d in strings(node.right, scope) if d.endswith('.cpp')}
        if isinstance(statement, (ast.For, ast.If, ast.While, ast.With, ast.Try)):
            for block in ('body', 'orelse', 'finalbody'):
                generated(getattr(statement, block, []), dict(scope), found)


def commands(text):
    """CMake commands as (name, arguments, inside an if() block), foreach(var ...) bodies expanded."""
    text = re.sub(r'(?m)^\s*#.*$', '', text)  # the port's cmake files only have whole-line comments
    out, loops, depth = [], [], 0
    for match in re.finditer(r'(\w+)\s*\(((?:[^()"]|"(?:\\.|[^"\\])*"|\((?:[^()"]|"(?:\\.|[^"\\])*")*\))*)\)', text):
        name = match[1].lower()
        args = [a.strip('"') for a in re.findall(r'"(?:\\.|[^"\\])*"|[^\s"]+', match[2])]
        if name == 'foreach':
            loops.append((args[0], args[1:], []))
            continue
        if name == 'endforeach':
            var, items, body = loops.pop()
            body = [(n, [a.replace('${' + var + '}', item) for a in b], d) for item in items for n, b, d in body]
            (loops[-1][2] if loops else out).extend(body)
            continue
        depth += (name == 'if') - (name == 'endif')
        (loops[-1][2] if loops else out).append((name, args, depth > 0))
    return out


found = set()
generated(ast.parse((root / 'tools/prepare-vulkan-port.py').read_text()).body, {}, found)
assert ('vulkan_staging_buffer_pool.cpp', 'src/video_core/renderer_vulkan/vk_staging_buffer_pool.cpp') in found, found

built, nested, removed = set(), set(), set()
for cmake in sorted((root / 'headless').glob('*.cmake')) + [root / 'headless/CMakeLists.txt']:
    for name, args, inside_if in commands(cmake.read_text()):
        if name == 'list' and args[:1] == ['REMOVE_ITEM']:
            removed.update(args[2:])
        elif (name == 'list' and args[:1] == ['APPEND']) or name == 'target_sources':
            for arg in args:
                if arg.startswith('${PORT_BUILD_DIR}/') and arg.endswith('.cpp'):
                    built.add(arg.removeprefix('${PORT_BUILD_DIR}/'))
                    if inside_if:
                        nested.add(arg.removeprefix('${PORT_BUILD_DIR}/'))

missing = sorted({destination for destination, _ in found} - built)
assert not missing, ('prepare-vulkan-port.py generates these, but no headless/*.cmake list builds them, '
                     'so Eden\'s originals are compiled instead: ' + ', '.join(missing))
# A replacement built beside Eden's original: two definitions of the same functions. Sources the
# port adds inside an if() block (frame generation) are ones upstream leaves out, so nothing to remove.
twice = sorted(f'{destination} ({source})' for destination, source in found
               if source and source.startswith('src/video_core/') and destination not in nested
               and source.removeprefix('src/video_core/') not in removed)
assert not twice, 'Generated, but the Eden source is not REMOVE_ITEM\'d from video_sources: ' + ', '.join(twice)
print(f'PASS: the {len({d for d, _ in found})} sources prepare-vulkan-port.py generates are all built, in place of Eden\'s')
