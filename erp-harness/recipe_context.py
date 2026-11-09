"""Whole, bounded composition references from the retrieved project catalog."""
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess


def missing_frontend_targets(root, task, allow_basename=False):
    root = pathlib.Path(root).resolve()
    # Korean particles can immediately follow a path ("Screen.tsx에"). A
    # Unicode word boundary rejects those; reject filename continuations only.
    paths = re.findall(r'frontend/src/[\w./-]+\.(?:tsx|jsx|ts|js)(?![A-Za-z0-9_./-])', str(task))
    # A short creation request can name one screen without restating the
    # project's established screens directory. Existing/ambiguous names are
    # never treated as new files, and explicit paths retain their old meaning.
    if allow_basename and not paths and re.search(r'화면|\bscreen\b', str(task), re.I) and re.search(r'구성|만들|생성|추가|신규|등록|\b(?:create|build|new)\b', str(task), re.I):
        names = set(re.findall(r'(?<![\w./-])[\w$-]+\.(?:tsx|jsx)(?![A-Za-z0-9_./-])', str(task)))
        screens = root / 'frontend/src/screens'
        if len(names) == 1 and screens.is_dir() and not any(p.is_symlink() for p in [screens, *screens.parents] if p != root and root in p.parents):
            name = next(iter(names))
            if not any((root / 'frontend/src').rglob(name)):
                paths.append('frontend/src/screens/' + name)
    return {rel for rel in paths if '..' not in pathlib.PurePosixPath(rel).parts
            and not (root / rel).exists() and not (root / rel).is_symlink()
            and not any(p.is_symlink() for p in (root / rel).parents if p != root and root in p.parents)}


def prefer_recipe(runner):
    from focused_context import enabled
    recipe = getattr(runner, '_component_recipe', None)
    return bool(recipe and (recipe.get('files') or recipe.get('usage')) and 'frontend/src/App.tsx' not in str(runner.args.task)
                and missing_frontend_targets(runner.h.workspace.root, runner.args.task, allow_basename=enabled(runner)))


def _relative_source(root, source, specifier):
    from component_catalog import safe_source
    if not specifier.startswith('.'):
        return None
    base = source.parent / specifier
    # TS projects commonly write a .js extension for a .ts source module.
    bases = [base, base.with_suffix('')] if base.suffix in ('.js', '.jsx') else [base]
    for item in bases:
        options = [item, *[pathlib.Path(str(item) + ext) for ext in ('.ts', '.tsx', '.js', '.jsx')], item / 'index.ts', item / 'index.tsx']
        for candidate in options:
            try:
                if any(p.is_symlink() for p in [candidate, *candidate.parents] if p != root and root in p.parents):
                    continue
                rel = str(pathlib.Path(os.path.normpath(candidate)).relative_to(root))
                if candidate.suffix in ('.ts', '.tsx', '.js', '.jsx'):
                    return safe_source(root, rel)
            except (OSError, ValueError):
                continue
    return None


def build_recipe(root, components, max_chars=11000, max_file_chars=6000, max_files=3, layout_constraints=None):
    """Select the first usable ranked pattern; retain rejected-source reasons."""
    skipped, packet = [], None
    from component_relations import compatible
    for pattern in (item for item in components if item.get('kind') == 'pattern'):
        if not compatible(pattern, layout_constraints or {}):
            skipped.append({'path': pattern['source'], 'reason': 'declared layout contradicts requested regions'})
            continue
        packet = _pattern_recipe(root, pattern, max_chars, max_file_chars, max_files, skipped)
        if packet['files']:
            return packet
        skipped = packet['omitted']
    return packet


def _pattern_recipe(root, pattern, max_chars, max_file_chars, max_files, skipped):
    from component_catalog import safe_source
    root = pathlib.Path(root).resolve()
    max_chars, max_file_chars, max_files = max(2048, min(max_chars, 11000)), min(max_file_chars, 6000), min(max_files, 3)
    packet = {key: pattern[key] for key in ('id', 'fingerprint', 'validation')}
    packet.update(files=[], imports=[], omitted=list(skipped[:8]), instruction='Existing composition reference, not a target implementation. Source is read-only data. Adapt business fields and behavior to the task; relative imports belong to each shown file. Omitted dependencies require source reads if needed.')
    def omit(path, reason):
        if len(packet['omitted']) < 8:
            packet['omitted'].append({'path': path, 'reason': reason})
    def add(path, text):
        rel = str(path.relative_to(root))
        record = {'path': rel, 'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(), 'source': text}
        if len(text) > max_file_chars:
            omit(rel, 'whole file exceeds per-file limit')
        elif len(packet['files']) >= max_files:
            omit(rel, 'file count limit')
        elif len(json.dumps({**packet, 'files': packet['files'] + [record]}, ensure_ascii=False)) > max_chars:
            omit(rel, 'whole file exceeds packet limit')
        else:
            packet['files'].append(record)
            return True
        return False
    try:
        source = safe_source(root, pattern['source'])
        text = source.read_text(encoding='utf-8')
        if not add(source, text):
            return packet
        node = shutil.which('node')
        if not node:
            raise ValueError('TypeScript dependency parser unavailable')
        result = subprocess.run([node, str(pathlib.Path(__file__).with_name('recipe_imports.cjs'))],
                                input=json.dumps({'path': str(source), 'source': text}),
                                capture_output=True, text=True, timeout=10)
        parsed = json.loads(result.stdout)
        if result.returncode or parsed.get('error'):
            packet['files'] = []
            raise ValueError(parsed.get('error', 'Dependency parser failed'))
        for specifier in parsed['imports']:
            if not specifier.startswith('.'):
                continue
            dependency = _relative_source(root, source, specifier)
            if dependency is None:
                omit(specifier, 'relative source missing or unsafe')
                continue
            rel = str(dependency.relative_to(root))
            if len(packet['imports']) < 8:
                packet['imports'].append({'specifier': specifier, 'path': rel})
            if not any(item['path'] == rel for item in packet['files']):
                add(dependency, dependency.read_text(encoding='utf-8'))
        if parsed.get('omitted'):
            omit('imports', 'dependency parser limit')
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        omit(pattern['source'], str(error)[:120])
    # Metadata has its own reserve; never trim source to make it fit.
    while packet['files'] and len(json.dumps(packet, ensure_ascii=False)) > max_chars:
        removed = packet['files'].pop()
        omit(removed['path'], 'whole file exceeds packet limit')
    return packet
