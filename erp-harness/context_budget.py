import json
import math
import os

FOCUSED_PRESSURE = 0.95
CAPACITY = int(os.environ.get('LOCAL_LLM_CONTEXT', '32768'))
# Set by context_manager once real prompt token counts are observed (chars per token,
# already conservative). None keeps the original chars/3 overestimate.
CALIBRATED_CHARS_PER_TOKEN = None


def focused_signature(runner, messages, tools, reserved, capacity):
    """A presentation cache must expire when source evidence or budgets change."""
    import hashlib
    from source_progress import current_bytes
    from task_sources import resolve_runner_sources
    versions = []
    workspace = getattr(getattr(runner, 'h', None), 'workspace', None)
    if getattr(workspace, 'root', None) is not None:
        paths = set(getattr(runner, 'read', ()))
        paths.update(getattr(runner, '_selected_check_progress', {}))
        paths.update(getattr(getattr(runner, 'rejected_new_files', None), 'files', {}))
        paths.update(resolve_runner_sources(runner))
        for path in sorted(paths):
            try:
                raw = current_bytes(runner, path)
                digest = hashlib.sha256(raw).hexdigest() if raw is not None else None
            except (OSError, ValueError):
                digest = 'unavailable'
            versions.append((path, digest))
    packet = {'messages': messages, 'tools': tools, 'reserved': reserved,
              'capacity': capacity, 'sources': versions}
    return hashlib.sha256(json.dumps(packet, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()

def measure(messages, tools=None, reserved=4096, capacity=32768):
    messages = [{k: v for k, v in m.items() if k not in ('reasoning', 'reasoning_content')} for m in messages]
    msg_json = json.dumps(messages, ensure_ascii=False)
    tool_json = json.dumps(tools, ensure_ascii=False) if tools else ""
    per_token = CALIBRATED_CHARS_PER_TOKEN or 3
    input_tokens = math.ceil((len(msg_json) + len(tool_json)) / per_token)
    
    # system_tokens_estimate logic: looking for system role in messages
    sys_msgs = [m for m in messages if m.get("role") == "system"]
    system_tokens_estimate = math.ceil(len(json.dumps(sys_msgs, ensure_ascii=False)) / 3) if sys_msgs else 0
    
    tools_tokens_estimate = math.ceil(len(tool_json) / 3) if tool_json else 0
    tool_results = [m for m in messages if m.get("role") == "tool"]
    
    remaining_tokens = max(0, capacity - input_tokens - reserved)
    return {
        "estimated_input_tokens": input_tokens,
        "reserved_output_tokens": reserved,
        "budget_tokens": capacity,
        "remaining_tokens": remaining_tokens,
        "pressure": (input_tokens + reserved) / capacity,
        "system_tokens_estimate": system_tokens_estimate,
        "tools_tokens_estimate": tools_tokens_estimate,
        "message_count": len(messages),
        "tool_result_count": len(tool_results),
        "method": "calibrated_chars" if CALIBRATED_CHARS_PER_TOKEN else "char_count_div3",
        "estimated": True
    }

from recent_context import compact

class ContextBudgetMixin:
    def fresh(self, reason=''):
        from focused_context import enabled
        focused = enabled(self)
        reserved = int(os.environ.get('LOCAL_LLM_MAX_TOKENS', 4096))
        if reason == 'context budget threshold' or reason.startswith('context reset after'):
            tools = self.tools()
            if focused:
                before = measure(self.messages, tools, reserved=reserved, capacity=CAPACITY)
                signature = focused_signature(self, self.messages, tools, reserved, CAPACITY)
                if before['pressure'] < FOCUSED_PRESSURE or (before['pressure'] <= 1 and
                        signature == getattr(self, '_focused_pressure_signature', None)):
                    self.h._context_state = before
                    # Preserve the idle guard's reset without rewriting a valid
                    # prefix; duplicate-read and round/stall limits stay active.
                    if reason.startswith('context reset after'):
                        self.idle = 0
                    return
            if compact(self, tools, reserved, CAPACITY, reason):
                if focused:
                    tools = self.tools()
                    after = measure(self.messages, tools, reserved=reserved, capacity=CAPACITY)
                    if after['pressure'] > 1:
                        raise RuntimeError('Context exceeds input plus reserved-output budget')
                    self._focused_pressure_signature = focused_signature(self, self.messages, tools, reserved, CAPACITY)
                return
        before = measure([m for m in self.messages if m.get('role') not in ('reasoning', 'reasoning_content')], self.tools()) if (self.messages or self.tools()) else None
        super().fresh(reason)
        after = measure([m for m in self.messages if m.get('role') not in ('reasoning', 'reasoning_content')], self.tools())
        if before and reason:
            self.h.log_event('autonomy.compact', {
                'before': before, 'after': after, 'reason': reason,
                'removed_messages': max(0, before['message_count'] - after['message_count']),
                'retained_paths': sorted(self.read), 'model_calls': 0
            })
        self.h._context_state = after

    def ask(self, messages, tools):
        from context_manager import manager
        managed = manager(self)
        if managed is not None:
            # Threshold-based prune/compact/rebuild with checkpoints (context_manager.py).
            if messages is self.messages and len(messages) > 2:
                messages = managed.prepare(messages, tools)
                usage = managed.budget.usage(messages, tools)
                self.h._context_state = usage
                if usage['input_tokens'] + int(os.environ.get('LOCAL_LLM_MAX_TOKENS', 4096)) > usage['max_context_tokens']:
                    raise RuntimeError('Context exceeds input plus reserved-output budget')
            return super().ask(messages, tools)
        from focused_context import enabled
        focused = enabled(self)
        if messages is self.messages and (len(messages) > 2 or focused):
            res = int(os.environ.get('LOCAL_LLM_MAX_TOKENS', 4096))
            cap = CAPACITY
            m = measure(messages, tools, reserved=res, capacity=cap)
            if m['pressure'] >= (FOCUSED_PRESSURE if focused else 0.8):
                self.fresh('context budget threshold')
                messages = self.messages
                tools = self.tools()
            if focused and measure(messages, tools, reserved=res, capacity=cap)['pressure'] > 1:
                raise RuntimeError('Context exceeds input plus reserved-output budget')
        return super().ask(messages, tools)

def extend_context(base):
    class ExtendedContext(ContextBudgetMixin, base):
        pass
    return ExtendedContext
