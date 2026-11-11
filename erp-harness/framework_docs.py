"""Framework usage the way a developer gets it: the API document, not the implementation.

frontend/src/framework/API.txt is split into its upper-case sections. A component's usage is
every section that names its export, so a screen author sees how to place and parameterize a
component without reading framework internals.
"""
from pathlib import Path
import re

DOC = 'frontend/src/framework/API.txt'
FRAMEWORK = 'frontend/src/framework/'


def sections(root):
    try:
        text = (Path(root) / DOC).read_text(encoding='utf-8')
    except (OSError, UnicodeError):
        return []
    out, title, body = [], None, []
    for line in text.splitlines():
        head = line.split('(')[0].strip()
        if not line.startswith(' ') and re.fullmatch(r'[A-Z][A-Z0-9 /+,.-]{3,}', head):
            if title:
                out.append((title, '\n'.join(body).strip('\n')))
            title, body = line.strip(), []
        elif title:
            body.append(line)
    if title:
        out.append((title, '\n'.join(body).strip('\n')))
    return out


GENERAL = ('COMPOSABLE ERP FRAMEWORK', 'COMPOSITION GUIDE')


def usage(root, names, budget=6000, general=False):
    """API.txt sections that mention any of names, in document order, within budget.

    general adds the overview/composition guide (useful when composing a new screen)."""
    names = [n for n in dict.fromkeys(names) if n]
    if not names:
        return ''
    pattern = re.compile(r'(?<![\w$])(?:' + '|'.join(map(re.escape, names)) + r')(?![\w$])')
    # Budget goes first to the sections that present a requested component (its JSX or call appears in
    # them), then to the general guide (when asked for), then to sections that merely mention one; output keeps document order.
    presents = re.compile(r'(?:<(?:' + '|'.join(map(re.escape, names)) + r')\b|\b(?:' + '|'.join(map(re.escape, names)) + r')\s*[({=])')
    ranked = []
    for index, (title, body) in enumerate(sections(root)):
        if title in GENERAL:
            if general:
                ranked.append((1, index, title, body))
        elif pattern.search(title + '\n' + body):
            ranked.append((0 if presents.search(body) else 2, index, title, body))
    chosen, used = [], 0
    for _, index, title, body in sorted(ranked, key=lambda item: (item[0], item[1])):
        chunk = title + '\n' + body
        if used + len(chunk) > budget:
            continue
        chosen.append((index, chunk))
        used += len(chunk)
    return '\n\n'.join(chunk for _, chunk in sorted(chosen))


def is_internal(rel):
    """A framework implementation file (the barrel and the API document stay plain reads)."""
    rel = str(rel)
    return (rel.startswith(FRAMEWORK) and rel.endswith(('.ts', '.tsx', '.js', '.jsx'))
            and Path(rel).stem != 'index')


def exports(root, rel):
    try:
        source = (Path(root) / rel).read_text(encoding='utf-8')
    except (OSError, UnicodeError):
        return []
    return re.findall(r'export\s+(?:function|const|class)\s+([A-Z][\w$]*)', source)


def file_usage(root, rel, budget=4000):
    return files_usage(root, [rel], budget)


def files_usage(root, rels, budget=6000):
    """What a developer sees to use framework files' components: their API.txt sections
    (or, if undocumented, the catalog summary/example) plus the declared props, deduplicated."""
    rels = list(dict.fromkeys(rels))
    names = [n for rel in rels for n in exports(root, rel)]
    docs = usage(root, names, budget=budget * 2 // 3)
    documented = set(re.findall(r'(?<![\w$])[A-Z][\w$]*', docs))
    try:
        from component_catalog import descriptors, actual_props
        catalog, _ = descriptors(root)
    except Exception:
        catalog = {}
    parts, seen = [docs] if docs else [], set()
    for entry in catalog.values():
        if entry.get('source') not in rels:
            continue
        if entry.get('export') not in documented:
            parts.append(entry.get('export', '') + ': ' + entry.get('summary', '') + '\nExample: ' + entry.get('example', ''))
        try:
            props = actual_props(root, entry)
        except Exception:
            props = ''
        for block in re.split(r'(?=^Project declaration )', props, flags=re.MULTILINE):
            if block.strip() and block.strip() not in seen:
                seen.add(block.strip())
                parts.append(block.strip())
    out = ''
    for part in parts:
        if len(out) + len(part) + 2 > budget:
            continue
        out += ('\n\n' if out else '') + part
    return out


def internal_read(runner, name, inputs):
    """First read of a framework implementation file returns its usage instead of its source.

    Using a component needs its documented API, not its code. A run that must change the shared
    component itself (named by the planner's direction, or read a second time) gets the source.
    """
    if name not in ('read_file', 'inspect_code') or not isinstance(inputs, dict):
        return None
    if name == 'inspect_code' and inputs.get('action') not in (None, 'outline', 'symbol'):
        return None
    rel = inputs.get('path')
    if not isinstance(rel, str) or not is_internal(rel):
        return None
    try:
        from workflow_progress import approach_files
        named = set(approach_files(runner))
    except Exception:
        named = set()
    asked = runner.__dict__.setdefault('_framework_usage_given', set())
    if rel in named or rel in asked or rel in getattr(runner, 'read', ()):
        return None
    text = file_usage(runner.h.workspace.root, rel)
    if not text:
        return None
    asked.add(rel)
    runner.h.log_event('autonomy.framework_usage', {'path': rel, 'chars': len(text)})
    return {'success': True, 'path': rel, 'framework_usage': text,
            'note': ('This is a framework component. Its usage (API.txt) and props are above; screens use it by '
                     'placing it and passing these props, without its internals. Only if the request requires '
                     'changing this shared component itself, read the same path again to get its source.')}
