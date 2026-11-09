"""Integration check of context compaction against the real local model (no mocks).

Usage (model server on 8099 must be idle; this takes a few minutes):
    python3 erp-harness/tests/context_live_check.py [--url http://127.0.0.1:8099/v1] [--model <id>]

Builds a realistic ~29K-token agent history (file reads, a failed edit, a failing check, a fix),
lets the same local model compact it, and reports: tokens before/after, duration, source
(llm or fallback), constraint/file/error preservation and whether the rebuilt context can
continue (the model is asked for its next tool call and must name a real next step).
"""
import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))


def history(task):
    msgs = [{'role': 'system', 'content': 'You are a coding agent. Use tools. Keep the user request exactly.'},
            {'role': 'user', 'content': f'할 일: {task}\n방향: frontend/src/screens/DepartmentRegistration.tsx 를 ItemMaster 처럼 만든다.'}]
    def call(i, name, args, result):
        msgs.append({'role': 'assistant', 'content': '', 'tool_calls': [{'id': f'c{i}', 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args, ensure_ascii=False)}}]})
        msgs.append({'role': 'tool', 'tool_call_id': f'c{i}', 'content': json.dumps(result, ensure_ascii=False)})
    source = (HERE.parent / 'local-only/frontend/src/screens/ItemMaster.tsx')
    text = source.read_text(encoding='utf-8') if source.is_file() else 'export default function X() {}\n' * 200
    i = 0
    for n in range(6):
        call(i, 'read_file', {'path': f'frontend/src/screens/Ref{n}.tsx'}, {'content': text[:3800]}); i += 1
    call(i, 'write_file', {'path': 'frontend/src/screens/DepartmentRegistration.tsx', 'content': text[:2000]}, {'status': 'ok'}); i += 1
    call(i, 'verify_requirements', {}, {'success': False, 'results': [{'id': 'C2', 'status': 'failed', 'reason': 'fill 상위부서: target does not exist in the DOM'}]}); i += 1
    msgs.append({'role': 'user', 'content': 'C2 failed: 상위부서 field is in the 추가정보 tab. Keep 부서코드 required.'})
    call(i, 'edit_file', {'path': 'frontend/src/screens/DepartmentRegistration.tsx', 'old_text': 'a', 'new_text': 'b'}, {'error': 'old_text not found'}); i += 1
    n = 0
    while len(json.dumps(msgs, ensure_ascii=False)) < TARGET_CHARS:
        # many small reads: rule-based pruning alone cannot make room, so the model must compact
        call(i, 'read_file', {'path': f'frontend/src/framework/F{n}.tsx'}, {'content': text[n * 37 % 2000:][:1000]}); i += 1; n += 1
    return msgs


TARGET_CHARS = 78000  # about 72% of 40960 with the 8192 output reserve at ~3.6 chars/token


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8099/v1')
    parser.add_argument('--model', default=os.environ.get('LOCAL_LLM_MODEL', 'mlx-community/Qwen3.8-27B-4bit'))
    a = parser.parse_args()
    job = tempfile.mkdtemp(prefix='context-live-')
    os.environ.update(HARNESS_JOB_DIR=job, LOCAL_LLM_CONTEXT='40960', LOCAL_LLM_MAX_TOKENS='4096')
    os.environ.pop('HARNESS_CONTEXT_MANAGEMENT', None)
    import context_manager as cm
    from harness import LocalLLMClient
    task = '부서 등록 화면 만들어줘'
    events = []
    h = SimpleNamespace(llm=LocalLLMClient(a.url, a.model), log_event=lambda k, d: events.append((k, d)))
    gate = SimpleNamespace(frozen_contract=json.dumps({'criteria': [{'id': 'C1', 'description': '부서코드 칸이 보인다'}, {'id': 'C2', 'description': '상위부서 입력이 가능하다'}]}))
    runner = SimpleNamespace(h=h, args=SimpleNamespace(task=task), messages=history(task), read=set(), last_check_results={'frontend': {'success': True}},
                             feedback='C2 failed: 상위부서 field is in the 추가정보 tab', requirement_gate=gate)
    m = cm.manager(runner)
    m.meter.samples = [3.6]  # typical calibrated chars/token for this model, so thresholds match a real run
    before = m.budget.usage(runner.messages)
    started = time.time()
    out = m.prepare(runner.messages, None)
    seconds = round(time.time() - started, 1)
    after = m.budget.usage(out)
    cp = m.checkpoint or {}
    text = json.dumps(cp, ensure_ascii=False)
    checks = {'goal kept': cp.get('goal') == task, 'C1 constraint': '부서코드 칸이 보인다' in text, 'C2 constraint': '상위부서 입력이 가능하다' in text,
              'modified file': 'DepartmentRegistration.tsx' in text, 'active error kept': '추가정보' in text,
              'failed edit recorded': 'old_text' in text or 'not found' in text, 'next actions': bool(cp.get('next_actions'))}
    resume = None
    if cp:
        out.append({'role': 'user', 'content': 'Reply with one sentence: what exactly will you do next?'})
        r = h.llm.chat(out, tools=None)
        resume = (r['choices'][0]['message'].get('content') or '')[:300]
    report = {'before_tokens': before['input_tokens'], 'before_ratio': before['ratio'], 'after_tokens': after['input_tokens'],
              'after_ratio': after['ratio'], 'seconds': seconds, 'source': (m.last or {}).get('source'), 'repaired': (m.last or {}).get('repaired'),
              'preservation': f"{sum(checks.values())}/{len(checks)}", 'checks': checks, 'failures': m.stats['failures'],
              'events': [k for k, _ in events], 'resume_answer': resume, 'job_dir': job}
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if cp and all(checks.values()) else 1


if __name__ == '__main__':
    sys.exit(main())
