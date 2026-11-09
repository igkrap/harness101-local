"""Relative-import graph of the frontend: which files a target screen actually depends on.

Barrel files (index.ts) are followed only for the names the importer uses, so importing three
components from the framework barrel does not pull in the whole framework.
"""
from pathlib import Path
import re

_EXTS = ('.tsx', '.ts', '.jsx', '.js')
_IMPORT = re.compile(r'''import\s+(type\s+)?([^;'"]*?)\s+from\s+['"](\.{1,2}/[^'"]+)['"]''')
_SIDE = re.compile(r'''import\s+['"](\.{1,2}/[^'"]+)['"]''')
_REEXPORT = re.compile(r'''export\s+(type\s+)?\{([^}]*)\}\s+from\s+['"](\.{1,2}/[^'"]+)['"]''')


def _read(root, rel):
    try:
        return (Path(root) / rel).read_text(encoding='utf-8')
    except (OSError, UnicodeError):
        return ''


def resolve(root, from_rel, spec):
    base = (Path(from_rel).parent / spec).as_posix()
    parts = []
    for part in base.split('/'):
        if part == '..':
            if parts:
                parts.pop()
        elif part not in ('', '.'):
            parts.append(part)
    base = '/'.join(parts)
    candidates = [base] + [base + e for e in _EXTS] + [base + '/index' + e for e in _EXTS]
    for candidate in candidates:
        if (Path(root) / candidate).is_file():
            return candidate
    return None


def _names(clause):
    clause = re.sub(r'^[^{]*', '', clause) if '{' in clause else ''
    names = []
    for item in clause.strip('{} \n').split(','):
        item = re.sub(r'^\s*type\s+', '', item.strip())
        if item:
            names.append(item.split(' as ')[0].strip())
    return names


def direct_imports(root, rel):
    """[(target_rel, imported_names or None for whole-module/default, type_only)] for one file."""
    source = _read(root, rel)
    result = []
    for match in _IMPORT.finditer(source):
        target = resolve(root, rel, match.group(3))
        if target:
            clause = match.group(2)
            names = _names(clause)
            has_default = bool(re.match(r'\s*[A-Za-z_$][\w$]*\s*(,|$)', clause))
            result.append((target, None if has_default or not names else names, bool(match.group(1))))
    for match in _SIDE.finditer(source):
        target = resolve(root, rel, match.group(1))
        if target:
            result.append((target, None, False))
    return result


def _through_barrel(root, barrel, names):
    """Map names imported from a barrel to the files that define them."""
    source = _read(root, barrel)
    files = []
    for match in _REEXPORT.finditer(source):
        exported = [n.split(' as ')[-1].strip() for n in match.group(2).split(',') if n.strip()]
        if names is None or any(n in names for n in exported):
            target = resolve(root, barrel, match.group(3))
            if target:
                files.append((target, bool(match.group(1)) or all(
                    n.strip().startswith('type ') for n in match.group(2).split(',') if n.strip())))
    return files


def dependencies(root, rel, include_types=False):
    """Files rel depends on directly, expanding barrels to the used names."""
    out = []
    for target, names, type_only in direct_imports(root, rel):
        if type_only and not include_types:
            continue
        if Path(target).stem == 'index':
            for file, file_type_only in _through_barrel(root, target, names):
                if include_types or not file_type_only:
                    out.append(file)
        else:
            out.append(target)
    return list(dict.fromkeys(p for p in out if p != rel))


def closure(root, start, depth=2):
    """start plus everything reachable through relative imports within depth hops."""
    seen = {start: 0}
    frontier = [start]
    for level in range(1, depth + 1):
        nxt = []
        for rel in frontier:
            # Barrels the file imports through are part of its dependency surface (small, and the
            # model reads them to see what is exported); their other re-exports are not followed.
            for target, _, _ in direct_imports(root, rel):
                if Path(target).stem == 'index' and target not in seen:
                    seen[target] = level
            for dep in dependencies(root, rel, include_types=True):
                if dep not in seen:
                    seen[dep] = level
                    nxt.append(dep)
        frontier = nxt
    return seen


def target_screens(root, task):
    """Screens a task names by meta.title, file path or stem."""
    found = []
    for path in sorted((Path(root) / 'frontend/src/screens').glob('*.tsx')):
        source = _read(root, path.relative_to(root).as_posix())[:8192]
        meta = re.search(r'\bexport\s+const\s+meta\s*=\s*\{([^{}]{0,1000})\}', source)
        title = meta and re.search(r'''\btitle\s*:\s*(['"])([^'"\r\n]{2,100})\1''', meta.group(1))
        rel = path.relative_to(root).as_posix()
        if (title and title.group(2) in task) or rel in task or re.search(r'\b' + re.escape(path.stem) + r'\b', task):
            found.append(rel)
    return found


def planner_context(root, task, budget=11000):
    """Target screen source plus the components it renders, for the task planner."""
    chunks, used = [], 0
    for screen in target_screens(root, task)[:2]:
        source = _read(root, screen)
        ret = source.rfind('return (')
        body = source if len(source) <= 4500 else source[:1200] + '\n...\n' + source[max(ret, 0):][:3300]
        chunks.append(f'[대상 화면 {screen}]\n{body}')
        used += len(chunks[-1])
        rendered = source[max(ret, 0):]
        def order(dep):
            at = rendered.find('<' + Path(dep).stem)
            return at if at >= 0 else len(rendered) + 1
        from framework_docs import is_internal, files_usage
        framework = []
        for dep in sorted(dependencies(root, screen), key=order):
            if not dep.startswith('frontend/src/') or used > budget:
                continue
            if is_internal(dep):
                framework.append(dep)
                continue
            text = _read(root, dep)[:2600]
            chunks.append(f'[화면이 사용하는 {dep}]\n{text}')
            used += len(chunks[-1])
        if framework:
            # Framework components are used through their documented API, not their internals.
            text = files_usage(root, framework, budget=max(1500, budget - used - 200))
            chunks.append('[화면이 사용하는 프레임워크 컴포넌트 사용법 (frontend/src/framework/API.txt + props)]\n' + text)
    return '\n\n'.join(chunks)[:budget]
