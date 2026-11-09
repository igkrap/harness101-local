"""Bounded, source-derived local TypeScript contracts; never synthesize fixes."""
import json
import pathlib
import re
import shutil
import subprocess


def resolve(root, names, source=None, source_text=None, max_chars=4000, max_depth=3, max_declarations=12):
    root = pathlib.Path(root).resolve()
    names = list(dict.fromkeys(name for name in names if isinstance(name, str) and len(name) <= 200 and re.fullmatch(r'[\w$.]+', name)))[:12]
    empty = {'declarations': [], 'omitted': [], 'resolved': [], 'ambiguous': []}
    if not names:
        return empty
    node = shutil.which('node')
    if not node or not (root / 'frontend/src').is_dir():
        return empty
    if source is None:
        # Avoid spawning the AST helper for package-only diagnostic names.
        pattern = re.compile(r'\b(?:' + '|'.join(re.escape(name) for name in names) + r')\b')
        found = False
        for path in (root / 'frontend/src').rglob('*'):
            if path.suffix not in ('.ts', '.tsx') or not path.is_file() or path.stat().st_size > 200000:
                continue
            if any(p.is_symlink() for p in [path, *path.parents] if p != root and root in p.parents):
                continue
            try:
                text = path.read_text(encoding='utf-8')
                if pattern.search(text) and re.search(r'\b(?:type|interface|enum|export)\b', text):
                    found = True
                    break
            except (OSError, UnicodeError):
                continue
        if not found:
            return empty
    payload = {'root': str(root), 'names': names, 'source': str(source) if source is not None else None,
               'max_chars': max_chars, 'max_depth': max_depth, 'max_declarations': max_declarations}
    if source_text is not None:
        payload['source_text'] = source_text
    try:
        result = subprocess.run([node, str(pathlib.Path(__file__).with_suffix('.cjs'))],
                                input=json.dumps(payload), capture_output=True, text=True, timeout=10)
        parsed = json.loads(result.stdout)
        if not isinstance(parsed, dict) or not isinstance(parsed.get('declarations'), list):
            return {**empty, 'error': 'Malformed local type extraction result'}
        return parsed
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {**empty, 'error': str(exc)}


def records(result):
    output = [declaration['record'] for declaration in result.get('declarations', [])]
    omissions = result.get('omitted', [])
    if omissions:
        available = result.get('max_chars', 4000) - sum(len(record) + 1 for record in output)
        summary = 'Omitted local type declarations: '
        used = 0
        for item in omissions:
            entry = item['name'] + ' (' + item['reason'] + '); '
            if len(summary + entry) + 30 > available:
                break
            summary += entry
            used += 1
        if used < len(omissions):
            summary += str(len(omissions) - used) + ' more omitted.'
        output.append(summary.rstrip('; '))
    if result.get('error'):
        output.append('Local type extraction unavailable: ' + result['error'])
    return output


def declarations(root, names, source=None, source_text=None, **limits):
    return records(resolve(root, names, source=source, source_text=source_text, **limits))
