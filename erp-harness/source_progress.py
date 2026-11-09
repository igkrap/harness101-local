"""Bounded evidence of committed patches, never proof of task completion."""
import hashlib
from pathlib import Path

MAX_RECORDS = 64
MAX_CONTEXT_CHARS = 2600


def sync_read_context(runner, paths):
    """Forget service read caches when their source evidence leaves the prompt."""
    runner.read = set(paths)
    service = getattr(runner.h, '_code_intelligence', None)
    if callable(getattr(service, 'retain_reads', None)):
        service.retain_reads(runner.read)


def context_without_retained_sources(runner, paths, messages=None):
    """Snapshot missing sources after choosing the retained tool history."""
    previous = getattr(runner, '_context_supplied_paths', None)
    previous_ast = getattr(runner, '_context_supplied_ast_snapshots', None)
    runner._context_supplied_paths = frozenset(paths)
    from ast_context import retained_snapshots
    runner._context_supplied_ast_snapshots = retained_snapshots(runner, messages or [])
    try:
        return runner.current_context()
    finally:
        if previous is None:
            del runner._context_supplied_paths
        else:
            runner._context_supplied_paths = previous
        if previous_ast is None:
            del runner._context_supplied_ast_snapshots
        else:
            runner._context_supplied_ast_snapshots = previous_ast


def remember_accepted(runner, records):
    progress = getattr(runner, '_selected_check_progress', {})
    for path, record in records.items():
        expected = record.get('expected')
        progress.pop(path, None)
        progress[path] = hashlib.sha256(expected).hexdigest() if expected is not None else None
        if len(progress) > MAX_RECORDS:
            progress.pop(next(iter(progress)))
            runner._progress_evictions = getattr(runner, '_progress_evictions', 0) + 1
    runner._selected_check_progress = progress


def current_bytes(runner, path):
    """Read a current regular file, rejecting symlink aliases before resolution."""
    workspace = runner.h.workspace
    relative = Path(path)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Unsafe snapshot path')
    if hasattr(workspace, 'root'):
        parent = workspace.root
        for part in relative.parts:
            parent = parent / part
            if parent.is_symlink():
                raise ValueError('Symlink snapshot path')
    target = workspace.safe_path(path)
    if target.is_symlink():
        raise ValueError('Symlink snapshot path')
    return target.read_bytes() if target.is_file() else None


def progress_context(runner):
    progress = getattr(runner, '_selected_check_progress', {})
    if not progress:
        return ''
    text = ('SELECTED-CHECK PATCH PROGRESS (not task completion):\n'
            'These committed versions passed the selected native checks. The completion gate still decides task success.\n'
            'Only CURRENT FILE blocks supply complete current source; omitted files require read_file before editing.\n')
    entries = list(reversed(progress.items()))
    included = 0
    for path, checked_hash in entries:
        try:
            raw = current_bytes(runner, path)
            actual = hashlib.sha256(raw).hexdigest() if raw is not None else None
            state = ('unchanged' if raw is not None else 'deleted') if actual == checked_hash else 'CHANGED since checks; old evidence is stale'
        except (OSError, ValueError):
            state = 'unavailable; old evidence is stale'
        line = f'{path} | checked SHA={checked_hash or "deleted"} | current={state}\n'
        if len(text) + len(line) > MAX_CONTEXT_CHARS - 140:
            break
        text += line
        included += 1
    omitted = len(entries) - included
    evicted = getattr(runner, '_progress_evictions', 0)
    if omitted or evicted:
        text += f'Progress summary omitted {omitted} current records and {evicted} older records (bounded context).\n'
    return text


def retained_read_paths(runner, messages):
    """Authorize only complete read results still matching the current bytes."""
    import json
    calls = {}
    paths = set()
    for msg in messages:
        for call in msg.get('tool_calls', []):
            function = call.get('function', {})
            if function.get('name') == 'read_file':
                try:
                    calls[call.get('id')] = json.loads(function.get('arguments', '{}'))['path']
                except (ValueError, TypeError, KeyError):
                    pass
        if msg.get('role') != 'tool' or msg.get('tool_call_id') not in calls:
            continue
        path = calls[msg['tool_call_id']]
        try:
            result = json.loads(msg.get('content', '{}'))
            content = result.get('content')
            if not result.get('error') and not result.get('unchanged') and result.get('exists') is not False and result.get('status') != 'rejected_candidate' and isinstance(content, str):
                if current_bytes(runner, path) == content.encode('utf-8'):
                    paths.add(path)
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    return paths
