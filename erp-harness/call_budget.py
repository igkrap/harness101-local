import json
import hashlib
import re
from pathlib import Path

def snapshot(runner):
    import re, json, pathlib
    task = getattr(runner.args, 'task', '')
    step_idx = getattr(runner, 'step', 0)
    steps = getattr(runner, 'steps', [])
    title = steps[step_idx].get('title', '') if 0 <= step_idx < len(steps) else ''
    msgs = getattr(runner, 'messages', [])
    read_set = getattr(runner, 'read', set())
    
    from source_progress import current_bytes, progress_context
    from focused_context import enabled
    from task_sources import resolve_runner_sources
    # Recent tool targets and committed patches survive a history reset. They
    # must not be displaced by two static task paths on every fresh context.
    candidates = resolve_runner_sources(runner) if enabled(runner) else []
    candidates.extend(sorted([p for p in read_set if p in title], reverse=True))
    for msg in reversed(msgs):
        for tc in reversed(msg.get('tool_calls', [])):
            func = tc.get('function', {})
            if func.get('name') in ('read_file', 'write_file', 'edit_file', 'apply_edits', 'apply_ast_edits', 'insert_text', 'apply_insertions'):
                try:
                    candidates.append(json.loads(func.get('arguments', '{}')).get('path'))
                except (ValueError, TypeError, AttributeError): pass
    candidates.extend(reversed(getattr(runner, '_selected_check_progress', {})))
    candidates.extend(sorted([p for p in read_set if p in task], reverse=True))
    # Paths in Korean prose often have a particle attached to the extension.
    # Prefer complete known file names before the legacy whitespace fallback.
    text = f"{task} {title}"
    candidates.extend(re.findall(
        r'(?:frontend|backend)/[\w./-]+\.(?:tsx|jsx|ts|js|json|java|xml|sql|yaml|yml|properties|txt|css|html)(?![A-Za-z0-9_./-])', text))
    for m in re.findall(r'(?:frontend|backend)/[^\s]+', text):
        candidates.append(m)
    # Metadata shares the existing 10k character budget with complete sources.
    # No partial source is ever marked read, and unrelated fallback files do not
    # occupy remaining space when the task already has relevant sources.
    from workflow_progress import context as workflow_context
    out = progress_context(runner) + workflow_context(runner)
    from focused_context import enabled
    supplied = getattr(runner, '_context_supplied_paths', ()) if enabled(runner) else ()
    seen, paths = set(), set()
    for group in (candidates, sorted(read_set)):
        for path_str in group:
            if not path_str or path_str in seen or path_str in supplied: continue
            seen.add(path_str)
            try:
                raw = current_bytes(runner, path_str)
                if raw is None: continue
                content = raw.decode('utf-8')
                block = f'CURRENT FILE {path_str}\n{content}\n'
                if len(content) <= 9000 and len(out) + len(block) <= 10000:
                    out += block
                    paths.add(path_str)
                    if (getattr(getattr(runner, '_job_migrations', None), 'enabled', False)
                            and path_str.startswith('backend/src/main/resources/db/migration/')
                            and path_str.endswith('.sql')):
                        receipts = getattr(runner, '_migration_full_reads', None)
                        if not isinstance(receipts, dict):
                            receipts = runner._migration_full_reads = {}
                        receipts[path_str] = hashlib.sha256(raw).hexdigest()
            except (OSError, ValueError, TypeError): continue
        if paths: break
    return out, paths


def ask_with_recovery(runner):
    """Calls runner.ask with a single timeout retry per step."""
    def request():
        from workflow_progress import before_request, note_completed_response
        before_request(runner)
        message = runner.ask(runner.messages, tools=runner.tools())
        note_completed_response(runner, message)
        return message

    if runner.cp.pending or (runner.args.max_rounds > 0 and runner.used >= runner.args.max_rounds):
        return request()

    try:
        return request()
    except Exception as exc:
        err_str = str(exc).lower()
        is_timeout = isinstance(exc, TimeoutError) or 'timeout' in err_str or 'timed out' in err_str
        
        if not is_timeout or runner.cp.pending or (runner.args.max_rounds > 0 and runner.used >= runner.args.max_rounds):
            raise exc
            
        retries = getattr(runner, 'timeout_retries', {})
        current_step = runner.step + 1
        
        if retries.get(current_step, 0) >= 1:
            raise exc
            
        # Mark retry used
        retries[current_step] = 1
        runner.timeout_retries = retries
        
        runner.feedback = "Model timed out; no tool from previous response ran."
        runner.h.log_event('autonomy.strategy', {
            'reason': 'timeout_retry',
            'step': current_step,
            'retry': 1
        })
        
        # Shrink history via snapshot
        runner.fresh('model timeout; retry with current-file context')
        
        # The second attempt: if it fails, it propagates naturally
        return request()
