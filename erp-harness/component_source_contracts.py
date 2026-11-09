"""Prefer a uniquely named screen's existing composition during focused edits."""
import json
from pathlib import Path
import re
import shutil
import subprocess


def redesign_requested(task, catalog, current_ids):
    # Preserve explicit alternatives. A new migration or API is not a new layout.
    task = re.sub(r"\b(?:do\s+not|don't|without)\s+(?:chang(?:e|ing)|replac(?:e|ing))\s+(?:the\s+)?(?:layout|pattern)\b"
                  r"|\b(?:do\s+not|don't)\s+(?:redesign|recompose)\b", '', task, flags=re.I)
    change = r'(?:바꿔|변경|교체|재구성)(?!\s*(?:없이|하지\s*(?:말|않)|금지))'
    if re.search(r'\b(?:redesign|recompose|new\s+(?:screen|layout|pattern)|(?:replace|change)\s+(?:the\s+)?(?:layout|pattern))\b'
                 r'|(?:새|새로운|다른)\s*(?:화면\s*)?(?:패턴|레이아웃|배치)'
                 r'|(?:새|새로운)\s*화면'
                 r'|(?:레이아웃|배치|패턴)[^.!?\n]{0,28}' + change +
                 r'|(?:화면|UI)[^.!?\n]{0,18}(?:재설계|재구성)(?!\s*없이)', task, re.I):
        return True
    for cid, entry in catalog.items():
        if entry['kind'] == 'pattern' and cid not in current_ids:
            if re.search(r'(?<![A-Za-z0-9_$])' + re.escape(entry['export']) + r'(?![A-Za-z0-9_$])', task):
                return True
    from component_relations import compatible, requested_layout
    constraints = requested_layout(task)
    return any(not compatible(catalog[cid], constraints) for cid in current_ids)


def existing_composition(root, task, catalog):
    from task_sources import resolve_task_sources
    paths = [path for path in resolve_task_sources(root, task)
             if path.startswith('frontend/src/') and Path(path).suffix in ('.tsx', '.jsx')]
    if len(paths) != 1 or not shutil.which('node'):
        return None
    payload = {'root': str(Path(root).resolve()), 'source': paths[0],
               'catalog': [{key: entry[key] for key in ('id', 'source', 'export')} for entry in catalog.values()]}
    try:
        response = subprocess.run(['node', str(Path(__file__).with_suffix('.cjs'))],
                                  input=json.dumps(payload), text=True, capture_output=True, timeout=5)
        found = json.loads(response.stdout)
        ids = found.get('components', [])
        if (found.get('error') or not ids or any(cid not in catalog for cid in ids)
                or redesign_requested(task, catalog, ids)):
            return None
        return {'source': paths[0], 'components': ids, 'source_fingerprints': found['source_fingerprints']}
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        return None
