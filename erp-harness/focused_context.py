"""Opt-in focused context and bounded nested-handler edits; checks stay fixed."""
import json


def enabled(runner):
    return getattr(getattr(runner, 'args', None), 'context_profile', 'legacy') == 'focused'


def feedback(runner):
    text = runner.feedback
    if enabled(runner):
        try:
            report = json.loads(text)
            if isinstance(report, dict) and 'task' in report:
                text = json.dumps({k: v for k, v in report.items() if k != 'task'}, ensure_ascii=False)
        except (ValueError, TypeError):
            pass
    return text
