"""Recognize complete current AST snapshots already retained in tool history.

This only suppresses duplicate presentation. The editor still supplies and checks
the authoritative snapshot; no snapshot ID or edit permission is created here.
"""
import hashlib
import json


def signature(snapshot):
    if not isinstance(snapshot, dict):
        return None
    if snapshot.get('error') or snapshot.get('unchanged') or snapshot.get('truncated'):
        return None
    if snapshot.get('status') == 'rejected_candidate' or snapshot.get('exists') is False:
        return None
    for key in ('snapshot_id', 'path', 'source_hash'):
        if not isinstance(snapshot.get(key), str) or not snapshot[key]:
            return None
    nodes = snapshot.get('nodes')
    if not isinstance(nodes, list) or not nodes or not isinstance(snapshot.get('diagnostics'), list):
        return None
    if any(not isinstance(node, dict) or
           any(not isinstance(node.get(key), str) for key in ('id', 'kind', 'label', 'source'))
           for node in nodes):
        return None
    try:
        payload = {key: snapshot[key] for key in ('snapshot_id', 'path', 'source_hash', 'diagnostics', 'nodes')}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                         allow_nan=False).encode('utf-8')).hexdigest()
    except (ValueError, TypeError):
        return None


def retained_snapshots(runner, messages):
    from source_progress import current_bytes
    calls, retained = {}, set()
    for message in messages:
        if message.get('role') == 'assistant':
            for call in message.get('tool_calls', []):
                function = call.get('function', {})
                if function.get('name') != 'inspect_code':
                    continue
                try:
                    args = json.loads(function.get('arguments', '{}'))
                    if args.get('action') == 'edit_ranges' and isinstance(args.get('path'), str):
                        calls[call.get('id')] = args['path']
                except (ValueError, TypeError, AttributeError):
                    pass
        if message.get('role') != 'tool' or message.get('tool_call_id') not in calls:
            continue
        try:
            content = message.get('content', '')
            if not isinstance(content, str) or len(content) > 1_000_000:
                continue
            snapshot = json.loads(content)
            key = signature(snapshot)
            if key is None or snapshot['path'] != calls[message['tool_call_id']]:
                continue
            raw = current_bytes(runner, snapshot['path'])
            if raw is not None and hashlib.sha256(raw).hexdigest() == snapshot['source_hash']:
                retained.add(key)
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    return frozenset(retained)


def already_retained(runner, authoritative_snapshot):
    key = signature(authoritative_snapshot)
    return key is not None and key in getattr(runner, '_context_supplied_ast_snapshots', ())
