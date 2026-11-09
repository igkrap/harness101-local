"""Resolve caller-selected, repository-owned acceptance checks before an agent starts."""
import hashlib
import json
from pathlib import Path
import re


def _path(root, relative):
    if not isinstance(relative, str) or not relative or '\\' in relative:
        raise ValueError('Invalid fixed acceptance path')
    parts = relative.split('/')
    if any(part in ('', '.', '..') for part in parts) or Path(relative).is_absolute():
        raise ValueError('Fixed acceptance paths must stay inside the repository')
    candidate = root.joinpath(*parts)
    cursor = root
    for part in parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError('Fixed acceptance paths must not use symlinks')
    candidate.resolve().relative_to(root)
    return candidate.resolve()


def load_fixed_acceptance(identifier, task, project, repo_root=None):
    """Accept an allowlisted ID, never a caller-provided command or manifest."""
    if not isinstance(identifier, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', identifier):
        raise ValueError('Invalid fixed acceptance ID')
    root = Path(repo_root or Path(__file__).resolve().parent.parent).resolve()
    manifest = _path(root, 'platform/acceptance/' + identifier + '.json')
    if not manifest.is_file() or manifest.stat().st_size > 65536:
        raise ValueError('Unknown or oversized fixed acceptance definition')
    try:
        data = json.loads(manifest.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise ValueError('Invalid fixed acceptance definition') from error
    keys = {'id', 'task', 'project', 'script', 'script_sha256', 'cases'}
    if not isinstance(data, dict) or set(data) != keys or data['id'] != identifier:
        raise ValueError('Invalid fixed acceptance definition fields')
    if not isinstance(task, str) or not task or data['task'] != task:
        raise ValueError('Fixed acceptance task does not match this request')
    expected_project = _path(root, data['project'])
    if not expected_project.is_dir() or expected_project != Path(project).resolve():
        raise ValueError('Fixed acceptance project does not match this request')
    script = _path(root, data['script'])
    tests = _path(root, 'platform/tests')
    if tests not in script.parents or expected_project in script.parents or script.suffix != '.cjs':
        raise ValueError('Fixed acceptance script must be outside the model workspace in platform/tests')
    if not script.is_file() or script.stat().st_size > 1048576:
        raise ValueError('Fixed acceptance script is missing or oversized')
    digest = data['script_sha256']
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest) or hashlib.sha256(script.read_bytes()).hexdigest() != digest:
        raise ValueError('Fixed acceptance script hash mismatch')
    cases = data['cases']
    if (not isinstance(cases, list) or not 1 <= len(cases) <= 64
            or any(not isinstance(case, str) or not case or len(case) > 200 for case in cases)
            or len(set(cases)) != len(cases)):
        raise ValueError('Fixed acceptance cases must be nonempty unique identifiers')
    return {'id': identifier, 'task': task, 'project_root': str(expected_project),
            'script': str(script), 'script_sha256': digest, 'cases': list(cases)}
