import json


def _focused_compact(runner, tools, reserved, capacity, reason, indices, get_anchor):
    from context_budget import measure
    from rejected_new_files import compact_draft_reads
    from source_progress import context_without_retained_sources, retained_read_paths, sync_read_context
    original = runner.messages
    before = measure(original, tools, reserved=reserved, capacity=capacity)
    chosen = None
    # Choose history first. Only current source absent from that history needs
    # another full-source block; failed drafts remain a separate typed anchor.
    # Keep the widest complete tool history that fits. Starting with only the
    # latest two rounds unnecessarily discarded the framework contracts read
    # immediately before an edit-range inspection.
    for start in indices:
        suffix = compact_draft_reads(original[start:])
        supplied = retained_read_paths(runner, suffix)
        anchor = get_anchor()
        paths = set()
        if callable(getattr(runner, 'current_context', None)):
            source, paths = context_without_retained_sources(runner, supplied, suffix)
            anchor['current_source'] = source
        candidate = [original[0], {'role': 'user', 'content': json.dumps(anchor, ensure_ascii=False)}] + suffix
        after = measure(candidate, tools, reserved=reserved, capacity=capacity)
        if after['pressure'] <= 1 and after['estimated_input_tokens'] < before['estimated_input_tokens']:
            chosen = candidate, after, set(paths) | supplied
            break
    if chosen is None:
        if before['pressure'] > 1:
            raise RuntimeError('Latest tool result and immutable contract cannot fit context budget; inspect a smaller scope')
        # A history-length trigger must not inflate an already valid prompt.
        runner.h._context_state = before
        sync_read_context(runner, runner.read)
        runner.h.log_event('autonomy.compact_skipped', {'reason': reason,
            'detail': 'No strictly smaller evidence-preserving candidate', 'context': before, 'model_calls': 0})
        return True
    messages, after, paths = chosen
    sync_read_context(runner, paths)
    runner.focused, runner.idle = True, 0
    runner.h._context_state = after
    if messages != original:
        runner.messages = messages
        runner.h.log_event('autonomy.compact', {'before': before, 'after': after, 'reason': reason,
            'removed_messages': max(0, len(original) - len(messages)), 'retained_paths': sorted(runner.read),
            'model_calls': 0, 'preserved_tool_results': sum(m.get('role') == 'tool' for m in messages)})
    return True

def compact(runner, tools, reserved, capacity, reason):
    original_messages = runner.messages
    indices = [i for (i, m) in enumerate(original_messages) if m.get('role') == 'assistant' and m.get('tool_calls')]
    if not indices:
        return False
    for idx in indices:
        calls = original_messages[idx].get('tool_calls', [])
        for call in calls:
            cid = call.get('id')
            if not any((m.get('role') == 'tool' and m.get('tool_call_id') == cid for m in original_messages[idx + 1:])):
                return False
    start_idx = indices[-2] if len(indices) >= 2 else indices[0]
    suffix = original_messages[start_idx:]

    def get_anchor():
        from focused_context import enabled
        focused = enabled(runner)
        task = getattr(getattr(runner, 'args', None), 'task', original_messages[1].get('content', ''))
        base_fb = getattr(runner, 'baseline_feedback', '')
        fb = getattr(runner, 'feedback', '')
        contract = runner.requirement_gate.context() if hasattr(runner, 'requirement_gate') else ''
        fb_data = fb
        if isinstance(fb, str):
            try:
                fb_data = json.loads(fb)
                if isinstance(fb_data, dict):
                    fb_data = {k: v for (k, v) in fb_data.items() if k not in (('layout', 'screenshot', 'task') if focused else ('layout', 'screenshot'))}
            except json.JSONDecodeError:
                pass
        anchor = {'baseline_feedback': base_fb, 'feedback': fb_data, 'contract': contract, 'instruction': 'Use retained tool results to edit; do not reread unchanged sources'}
        if not focused:
            anchor['task'] = task
        elif callable(getattr(runner, 'rejected_new_context', None)):
            drafts = runner.rejected_new_context()
            if drafts:
                anchor['rejected_new_files'] = drafts
        return anchor
    from focused_context import enabled
    if enabled(runner):
        return _focused_compact(runner, tools, reserved, capacity, reason, indices, get_anchor)
    from context_budget import measure
    before = measure(original_messages, tools, reserved=reserved, capacity=capacity)
    anchor = get_anchor()
    # Tool-only suffixes can contain documentation and lose every source/AST ID.
    # Rebuild the current source anchor instead of inviting an endless reread loop.
    if callable(getattr(runner, 'current_context', None)):
        source, paths = runner.current_context()
        anchor['current_source'] = source
    candidates = []
    from focused_context import enabled
    from rejected_new_files import compact_draft_reads
    def retained_suffix(start):
        suffix = original_messages[start:]
        return compact_draft_reads(suffix) if enabled(runner) else suffix
    if len(indices) >= 2:
        candidates.append([original_messages[0], {'role': 'user', 'content': json.dumps(anchor, ensure_ascii=False)}] + retained_suffix(indices[-2]))
    candidates.append([original_messages[0], {'role': 'user', 'content': json.dumps(anchor, ensure_ascii=False)}] + retained_suffix(indices[-1]))
    best_candidate = None
    best_after = None
    for cand in candidates:
        after = measure(cand, tools, reserved=reserved, capacity=capacity)
        if after['pressure'] <= 1:
            (best_candidate, best_after) = (cand, after)
            break
        if best_after is None or after['pressure'] < best_after['pressure']:
            (best_candidate, best_after) = (cand, after)
    if not best_candidate or best_after['pressure'] > 1:
        raise RuntimeError('Latest tool result and immutable contract cannot fit context budget; inspect a smaller scope')
    runner.focused = True
    runner.idle = 0
    if callable(getattr(runner, 'current_context', None)):
        from source_progress import retained_read_paths, sync_read_context
        sync_read_context(runner, set(paths) | retained_read_paths(runner, best_candidate))
    if best_candidate == original_messages:
        runner.h._context_state = best_after
        return True
    old_len = len(original_messages)
    runner.messages = best_candidate
    runner.h._context_state = best_after
    tool_results_count = sum((1 for m in best_candidate if m.get('role') == 'tool'))
    runner.h.log_event('autonomy.compact', {'before': before, 'after': best_after, 'reason': reason, 'removed_messages': max(0, old_len - len(best_candidate)), 'retained_paths': sorted(runner.read), 'model_calls': 0, 'preserved_tool_results': tool_results_count})
    return True
