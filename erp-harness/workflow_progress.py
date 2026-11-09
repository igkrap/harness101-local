from pathlib import Path
"""Discovery progress for known sources; source authority and tools stay unchanged."""
import hashlib
import json
import time
from types import SimpleNamespace

READ_ONLY_TOOLS = frozenset({'read_file', 'list_files', 'search_code', 'inspect_code',
                             'search_components', 'astryx_docs', 'inspect_layout'})
ANCHOR = 'WORKFLOW ACT PHASE (not completion evidence):'
STATUS = 'WORKFLOW CALL STATUS:'
MAX_COMPACT_ANCHOR_CHARS = 65536
MAX_CURRENT_SOURCE_CHARS = 10000
SCREEN_DISCOVERY_LIMIT = 3
SCREEN_STALL_EXTRA_RESPONSES = 5
SCREEN_STALL_SECONDS = 600
POST_EDIT_READ_LIMIT = 8  # consecutive read-only responses after an edit before the run stops
READ_SUSPEND_AFTER = 2  # read-only responses tolerated after the act reminder before reads are refused


def _screen_target(runner):
    if 'frontend' not in set(getattr(runner, 'modes', ()) or ()):
        return None
    from task_sources import resolve_runner_sources
    paths = [path for path in resolve_runner_sources(runner)
             if path.startswith('frontend/src/screens/') and path.endswith('.tsx')]
    return paths[0] if len(paths) == 1 else None


def _frontend_only_request(task):
    lower = str(task).casefold()
    return not any(term in lower for term in
                   ('백엔드', '데이터베이스', 'database', 'api', '엔드포인트', 'sql',
                    '저장', '조회', '삭제', 'crud', '마이그레이션', '테이블', '스키마', 'db'))


def _policy(runner):
    modes = set(getattr(runner, 'modes', ()) or ())
    focused = getattr(getattr(runner, 'args', None), 'context_profile', 'legacy') == 'focused'
    if focused and 'frontend' in modes and modes <= {'frontend', 'framework'}:
        spec = getattr(getattr(runner, 'args', None), 'fixed_acceptance', None)
        if isinstance(spec, dict):
            try:
                from fixed_acceptance import validate
                validate(spec, runner)
                return SimpleNamespace(enabled=True, authority=spec['script_sha256'],
                                       discovery_round_limit=5, fixture_owner='legacy', database_scope='unknown')
            except (OSError, ValueError, TypeError, AttributeError):
                return None
    screen = _screen_target(runner)
    # A run without backend checks cannot change the backend, so it is a screen task even when its
    # wording contains data words such as '조회' (query panel) or '저장' (save button).
    if screen and ('backend' not in modes or _frontend_only_request(getattr(runner.args, 'task', ''))):
        return SimpleNamespace(enabled=True, authority='screen-source',
                               discovery_round_limit=SCREEN_DISCOVERY_LIMIT,
                               fixture_owner='legacy', database_scope='unknown')
    if not focused:
        return None
    if modes != {'backend'}:
        return None
    from workflow_policy import get_policy
    policy = get_policy(runner)
    return policy if policy.enabled and policy.authority is not None else None


def checker_owned_fixtures(runner):
    policy = _policy(runner)
    if not policy or policy.fixture_owner != 'checker' or policy.database_scope != 'fresh-owned':
        return False
    from seed_updates import is_seed_request
    return not is_seed_request(runner.args.task)


def _memory_stamp(runner):
    entries = getattr(getattr(runner, 'memory', None), 'entries', None)
    if not isinstance(entries, list):
        return None
    facts = [tuple(entry.get(key) for key in ('path', 'base_sha', 'candidate_sha', 'fingerprint'))
             for entry in entries if isinstance(entry, dict)]
    return hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest()


def _state(runner):
    state = getattr(runner, '_workflow_progress', None)
    if state is None:
        state = {'read_only_rounds': 0, 'first_read_at': None, 'last_completed_call': -1, 'phase': 'discovery',
                 'primary': None, 'mutation_seen': False, 'memory_stamp': _memory_stamp(runner)}
        runner._workflow_progress = state
    return state


def _mutation_priority(runner, state):
    if (getattr(getattr(runner, 'cp', None), 'pending', False)
            or getattr(runner, 'accepted', False)
            or getattr(runner, '_selected_check_progress', None)
            or getattr(runner, 'rejected_candidate', None)
            or getattr(runner, '_failed_ast_candidate', None)
            or getattr(getattr(runner, 'rejected_new_files', None), 'files', None)
            or _memory_stamp(runner) != state['memory_stamp']):
        state['mutation_seen'] = True
    return state['mutation_seen']


def _primary_supplied(runner):
    from source_progress import current_bytes
    from task_sources import resolve_runner_sources
    modes = set(getattr(runner, 'modes', ()) or ())
    screen = _screen_target(runner)
    if screen:
        primary = [screen] if screen in getattr(runner, 'read', ()) else []
    elif 'frontend' in modes and modes <= {'frontend', 'framework'}:
        primary = [path for path in getattr(runner, 'read', ())
                   if path.startswith('frontend/src/screens/') and path.endswith('.tsx')]
        if len(primary) == 1:
            from source_progress import retained_read_paths
            if primary[0] in retained_read_paths(runner, runner.messages):
                return primary[0]
    else:
        primary = [path for path in resolve_runner_sources(runner)
                   if path.startswith('backend/src/main/java/') and path.endswith('.java')]
    if len(primary) != 1 or primary[0] not in getattr(runner, 'read', ()):
        return None
    path = primary[0]
    try:
        raw = current_bytes(runner, path)
        if raw is None:
            return None
        block = 'CURRENT FILE ' + path + '\n' + raw.decode('utf-8') + '\n'
        for message in getattr(runner, 'messages', ()):
            content = message.get('content')
            if message.get('role') != 'user' or not isinstance(content, str):
                continue
            if block in content:
                return path
            # Native focused compaction serializes CURRENT FILE blocks inside
            # its top-level current_source field. Decode only that bounded
            # field; unrelated JSON, partial or stale bytes grant nothing.
            if len(content) <= MAX_COMPACT_ANCHOR_CHARS and content.lstrip().startswith('{'):
                try:
                    anchor = json.loads(content)
                    source = anchor.get('current_source') if isinstance(anchor, dict) else None
                    if isinstance(source, str) and len(source) <= MAX_CURRENT_SOURCE_CHARS and block in source:
                        return path
                except (ValueError, TypeError, RecursionError):
                    pass
    except (OSError, ValueError, UnicodeError):
        pass
    return None


def _primary_ready(runner, state):
    primary = _primary_supplied(runner)
    if primary:
        return primary
    # Compaction can keep a full read result instead of duplicating its bytes
    # in another CURRENT FILE block. Its current-byte proof remains necessary.
    from source_progress import retained_read_paths
    known = state['primary']
    if known and known in getattr(runner, 'read', ()) and known in retained_read_paths(runner, runner.messages):
        return known
    return None


def note_completed_response(runner, message):
    """Count one completed discovery response, regardless of its tool batch size."""
    policy = _policy(runner)
    if not policy or policy.discovery_round_limit <= 0:
        return
    state = _state(runner)
    used = getattr(runner, 'used', 0)
    if not isinstance(used, int) or used <= state['last_completed_call']:
        return
    state['last_completed_call'] = used
    if isinstance(message, dict):
        names = [call['function'].get('name') for call in (message.get('tool_calls') or [])
                 if isinstance(call, dict) and isinstance(call.get('function'), dict)]
        if names and all(n in READ_ONLY_TOOLS for n in names):
            state['post_edit_reads'] = state.get('post_edit_reads', 0) + 1
        elif any(n not in READ_ONLY_TOOLS and n != 'finish' for n in names):
            state['post_edit_reads'] = 0
    if _mutation_priority(runner, state):
        return
    primary = _primary_ready(runner, state)
    if primary:
        state['primary'] = primary
    if not state['primary'] or not isinstance(message, dict):
        return
    calls = message.get('tool_calls')
    if isinstance(calls, list) and any(isinstance(call, dict) and isinstance(call.get('function'), dict)
                                       and call['function'].get('name') not in READ_ONLY_TOOLS
                                       and call['function'].get('name') != 'finish' for call in calls):
        # An edit attempt (even a rejected one) earns a fresh read allowance: after a failed edit
        # the model legitimately needs the current source again.
        state['read_only_rounds'] = 0
        state['reads_suspended_logged'] = False
    if (not isinstance(calls, list) or not calls
            or any(not isinstance(call, dict) or not isinstance(call.get('function'), dict)
                   or call['function'].get('name') not in READ_ONLY_TOOLS for call in calls)):
        return  # Planning/plain text, finish, and mutation responses do not count.
    state['read_only_rounds'] += 1
    if state['first_read_at'] is None:
        state['first_read_at'] = time.monotonic()


def stop_if_stalled(runner):
    """End an expensive, source-supplied read loop after its act reminder failed."""
    policy = _policy(runner)
    state = getattr(runner, '_workflow_progress', None)
    if state and state.get('mutation_seen') and state.get('post_edit_reads', 0) >= POST_EDIT_READ_LIMIT:
        # After an edit was verified and failed, a long run of reads without any new edit means the
        # model has no fix in sight (often the failure is not in its code); more calls only cost time.
        runner.h.log_event('autonomy.stalled', {
            'reason': 'read_only_loop_after_edit', 'consecutive_read_only_responses': state['post_edit_reads'],
            'model_calls': getattr(runner, 'used', 0)})
        return True
    if (not policy or policy.authority != 'screen-source' or not state or
            state['phase'] != 'act' or _mutation_priority(runner, state) or
            state['read_only_rounds'] < policy.discovery_round_limit + SCREEN_STALL_EXTRA_RESPONSES or
            state['first_read_at'] is None or
            time.monotonic() - state['first_read_at'] < SCREEN_STALL_SECONDS):
        return False
    runner.h.log_event('autonomy.stalled', {
        'reason': 'read_only_discovery_loop',
        'completed_read_only_responses': state['read_only_rounds'],
        'primary_source': state['primary'], 'model_calls': getattr(runner, 'used', 0),
        'elapsed_seconds': round(time.monotonic() - state['first_read_at']),
    })
    return True


def _status(runner, state, policy):
    maximum = getattr(runner.args, 'max_rounds', 0)
    remaining = str(max(0, maximum - getattr(runner, 'used', 0))) if maximum > 0 else 'unbounded'
    return (STATUS + ' completed read-only responses=' + str(state['read_only_rounds'])
            + '; discovery limit=' + str(policy.discovery_round_limit)
            + '; remaining model calls before the next request=' + remaining + '.')


def context(runner):
    """Re-present the same phase after a fresh/compact context, without resetting it."""
    policy = _policy(runner)
    state = getattr(runner, '_workflow_progress', None)
    if not policy or not state or state['phase'] != 'act':
        return ''
    status = _status(runner, state, policy)
    if _mutation_priority(runner, state):
        return '\n' + status + ' Existing candidate repair and verification feedback take precedence.\n'
    return ('\n' + ANCHOR + '\nA complete current primary source has already been supplied. '
            'Use the available evidence to make the next justified implementation change for the task, then check it. '
            'Read further only when necessary; all existing read tools and edit guards remain available. '
            'The immutable completion gate still decides success.\n' + status + '\n')


def before_request(runner):
    policy = _policy(runner)
    if not policy or policy.discovery_round_limit <= 0:
        return
    state = _state(runner)
    primary = _primary_ready(runner, state)
    if primary:
        state['primary'] = primary
    mutation = _mutation_priority(runner, state)
    if (state['phase'] == 'discovery' and not mutation and primary
            and state['read_only_rounds'] >= policy.discovery_round_limit):
        state['phase'] = 'act'
        runner.h.log_event('autonomy.workflow_progress', {
            'phase': 'act', 'completed_read_only_responses': state['read_only_rounds'],
            'discovery_round_limit': policy.discovery_round_limit, 'primary_source': primary,
            'model_calls': 0,
        })
    if state['phase'] != 'act':
        return
    text = context(runner)
    status = _status(runner, state, policy)
    contents = [message.get('content', '') for message in runner.messages
                if message.get('role') == 'user' and isinstance(message.get('content'), str)]
    if any((text.strip() in content if mutation else status in content) for content in contents):
        return
    if not mutation and any(ANCHOR in content for content in contents):
        text = '\n' + status + '\n'
    runner.messages.append({'role': 'user', 'content': text})


def read_suspended(runner, name, inputs=None):
    """After the act reminder was ignored, refuse further reads until the next edit.

    The tool list itself is left unchanged so the cached prompt prefix stays valid.
    """
    if name not in READ_ONLY_TOOLS:
        return None
    if name == 'inspect_code' and isinstance(inputs, dict) and inputs.get('action') == 'edit_ranges':
        return None  # AST edit IDs are the prerequisite for editing an existing file, not discovery
    # Only re-reads are refused: with a cached prompt a new file costs seconds and may be exactly what
    # the model needs, but a file whose content is still in context adds nothing.
    target = inputs.get('path') if isinstance(inputs, dict) else None
    if name not in ('read_file', 'inspect_code') or not isinstance(target, str) or target not in getattr(runner, 'read', set()):
        return None
    policy = _policy(runner)
    state = getattr(runner, '_workflow_progress', None)
    if (not policy or policy.discovery_round_limit <= 0 or not state or state['phase'] != 'act'
            or _mutation_priority(runner, state)
            or state['read_only_rounds'] < policy.discovery_round_limit + READ_SUSPEND_AFTER):
        return None
    if not state.get('reads_suspended_logged'):
        state['reads_suspended_logged'] = True
        runner.h.log_event('autonomy.reads_suspended', {
            'completed_read_only_responses': state['read_only_rounds'],
            'primary_source': state['primary'], 'model_calls': getattr(runner, 'used', 0)})
    return {'error': (
        'READ SUSPENDED: ' + str(target) + ' is already in your context (read earlier and unchanged); rereading adds nothing. '
        + str(state['read_only_rounds']) + ' read-only responses completed. Make the implementation change now '
        'with an edit tool. If the screen alone cannot satisfy the request because a shared framework component '
        'hard-codes the behavior, edit that component (keep other screens working, e.g. behind an optional prop). '
        'Reads resume after your next edit.')}


def outside_scope(runner, name, inputs=None):
    """For a single existing screen task, refuse frontend reads outside what that screen depends on.

    Allowed: the screen's relative-import closure (2 hops, barrels expanded to used names), files the
    run already changed, and files the planner's implementation direction names.
    """
    if name not in ('read_file', 'inspect_code') or not isinstance(inputs, dict):
        return None
    target = inputs.get('path')
    if not isinstance(target, str) or not target.startswith('frontend/src/'):
        return None
    policy = _policy(runner)
    if not policy or getattr(policy, 'authority', None) != 'screen-source':
        return None
    screen = _screen_target(runner)
    if not screen:
        return None
    allowed = getattr(runner, '_read_scope', None)
    if allowed is None or allowed[0] != screen:
        import os
        import re
        from import_graph import closure
        files = set(closure(runner.h.workspace.root, screen, depth=2))
        files.update(re.findall(r'frontend/src/[\w./-]+\.(?:tsx|ts|css)', os.environ.get('HARNESS_TASK_APPROACH', '')))
        runner._read_scope = allowed = (screen, files)
    files = set(allowed[1])
    state = getattr(runner, '_workflow_progress', None)
    named = set(approach_files(runner))
    narrowed = bool(named and state and state.get('phase') == 'act')
    if narrowed:
        # The planner already named the files to change and the act reminder was given: further
        # exploration of the wider dependency set is no longer useful (barrels stay readable).
        files = named | {screen} | {f for f in files if Path(f).stem == 'index'}
    files.update(getattr(getattr(runner, 'cp', None), '_records', {}) or {})
    files.update(getattr(runner, '_selected_check_progress', {}) or {})
    if target in files:
        return None
    if not getattr(runner, '_scope_logged', False):
        runner._scope_logged = True
        runner.h.log_event('autonomy.read_scope', {'screen': screen, 'refused': target, 'allowed': sorted(files)})
    if narrowed:
        return {'error': ('OUT OF SCOPE: discovery is over. The implementation direction names ' + ', '.join(sorted(named))
                          + ' and they are already in your context. Edit them now; ' + target + ' is not needed for this change.')}
    return {'error': ('OUT OF SCOPE: ' + target + ' is not used by ' + screen + ' (directly or through the components it '
                      'renders). Files relevant to this task: ' + ', '.join(sorted(files)) + '. Read or edit those instead.')}


def approach_files(runner):
    """Frontend files the planner's implementation direction names (matched by path or file name)."""
    import os
    import re
    text = os.environ.get('HARNESS_TASK_APPROACH', '')
    if not text:
        return []
    names = set(re.findall(r'([A-Za-z0-9_-]+\.(?:tsx|ts))(?![A-Za-z0-9_.])', text))
    if not names:
        return []
    root = runner.h.workspace.root
    found = []
    for path in sorted(Path(root, 'frontend/src').rglob('*.ts*')):
        if path.name in names and 'node_modules' not in path.parts:
            found.append(path.relative_to(root).as_posix())
    return found


REPEAT_READ_LIMIT = 2      # reads of one unchanged file before further reads are refused
READ_STREAK_LIMIT = 12     # read-only responses in a row (any task type) before the run stops


def repeated_read(runner, name, inputs=None):
    """Any task type: refuse a third read of a file whose content has not changed since it was read."""
    if name != 'read_file' or not isinstance(inputs, dict) or not isinstance(inputs.get('path'), str):
        return None
    import hashlib
    path = inputs['path']
    try:
        digest = hashlib.sha256((runner.h.workspace.root / path).read_bytes()).hexdigest()
    except (OSError, TypeError, AttributeError):
        return None
    seen = runner.__dict__.setdefault('_read_counts', {})
    key = (path, digest)
    seen[key] = seen.get(key, 0) + 1
    if seen[key] <= REPEAT_READ_LIMIT:
        return None
    return {'error': f'{path} was already read {REPEAT_READ_LIMIT} times and has not changed. '
                     'Reading it again adds nothing. Write the change now with an edit tool.'}


def note_read_streak(runner, message, edited):
    """Count read-only responses in a row; True when the run should stop."""
    calls = (message or {}).get('tool_calls') or []
    names = [c['function'].get('name') for c in calls if isinstance(c, dict) and isinstance(c.get('function'), dict)]
    if edited or any(n not in READ_ONLY_TOOLS and n != 'finish' for n in names):
        runner._read_streak = 0
    elif names:
        runner._read_streak = getattr(runner, '_read_streak', 0) + 1
    if getattr(runner, '_read_streak', 0) >= READ_STREAK_LIMIT:
        runner.h.log_event('autonomy.stalled', {'reason': 'read_only_streak', 'responses': runner._read_streak,
                                                'model_calls': getattr(runner, 'used', 0)})
        return True
    return False
