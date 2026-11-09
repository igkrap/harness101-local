"""Run a fixed task set through the task queue and record success, time and model usage.

Each task starts from the same source: after a task finishes, files it changed are restored from its
own change record (failed runs already restore themselves). Results: bench/results-<stamp>.json/.md
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

BASE = 'http://127.0.0.1:5293'
STATE = Path(__file__).resolve().parents[1] / 'state'
PROJECT = Path(__file__).resolve().parents[2] / 'local-only'

TASKS = [
    ('T1', '쉬움·문구', "품목 등록 화면 결과 그리드의 '비고' 열 제목을 '메모'로 바꿔줘"),
    ('T2', '쉬움~중간·필드', "품목 등록 화면 조회 조건에 '규격' 입력을 추가해줘"),
    ('T3', '중간·검증', "품목 등록 화면 편집에서 '규격'을 필수 입력으로 바꿔줘"),
    ('T4', '중간~어려움·새 동작', "품목 등록 화면 조회 조건에 '조건 초기화' 버튼을 추가해서 누르면 조회 조건 입력값이 모두 비워지게 해줘"),
]


def call(path, body=None):
    data = None if body is None else json.dumps(body).encode()
    headers = {'Content-Type': 'application/json'}
    if body is not None:
        headers['X-Platform-Token'] = call('/api/state')['token']
    req = urllib.request.Request(BASE + path, data, headers, method='POST' if body is not None else 'GET')
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def events(job):
    path = STATE / job / 'events.jsonl'
    return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []


def restore(job):
    """Put back what a (successful) job changed, only if the file is still exactly its result."""
    restored = []
    folder = STATE / job / 'changes'
    for record in folder.glob('*.json'):
        if record.name == 'index.json':
            continue
        d = json.loads(record.read_text())
        target = PROJECT / d['path']
        current = target.read_text() if target.exists() else None
        if current != (d['after'] if d['after_exists'] else None):
            continue
        if d['before_exists']:
            target.write_text(d['before'])
        elif target.exists():
            target.unlink()
        restored.append(d['path'])
    return restored


def summarize(task, queue, wall):
    item = (queue.get('items') or [{}])[0]
    job = item.get('job_id')
    ev = events(job) if job else []
    responses = [e for e in ev if e['type'] == 'model.response']
    verifications = [e for e in ev if e['type'] == 'verification.finished']
    last_ver = verifications[-1]['data'].get('results', []) if verifications else []
    reason = ''
    for e in reversed(ev):
        if e['type'] in ('autonomy.conflict', 'autonomy.stalled', 'run.error', 'autonomy.error'):
            reason = str(e['data'].get('error') or e['data'].get('reason') or '')[:300]
            break
    if not reason and last_ver:
        reason = '; '.join(f"{r['id']}:{r['status']}" for r in last_ver if not str(r.get('id', '')).startswith('system:'))
    return {
        'id': task[0], 'level': task[1], 'goal': task[2], 'queue': queue['id'], 'job': job,
        'status': queue['status'], 'items': len(queue.get('items') or []),
        'wall_minutes': round(wall / 60, 1), 'plan_seconds': queue.get('plan_seconds'),
        'model_calls': len(responses), 'accepted_edits': sum(e['type'] == 'autonomy.accepted' for e in ev),
        'verifications': len(verifications), 'criteria': [(r.get('id'), r.get('status')) for r in last_ver],
        'reason': reason,
        'framework_changed': any('FRAMEWORK_CHANGED' in json.dumps(e['data'], ensure_ascii=False) for e in ev),
    }


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--repeat=')]
    repeat = next((int(a.split('=')[1]) for a in sys.argv[1:] if a.startswith('--repeat=')), 1)
    only = set(args)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    out = Path(__file__).with_name(f'results-{stamp}.json')
    results = []
    for task in [t for _ in range(repeat) for t in TASKS]:
        if only and task[0] not in only:
            continue
        while call('/api/state').get('workspace_busy'):
            time.sleep(10)
        started = time.time()
        queue = call('/api/queues', {'goal': task[2], 'rounds': 40, 'origin': 'bench'})
        while True:
            time.sleep(15)
            queue = call(f"/api/queues/{queue['id']}")
            if queue['status'] not in ('planning', 'running', 'stopping'):
                break
        result = summarize(task, queue, time.time() - started)
        if result['job'] and result['status'] == 'succeeded':
            result['restored_after_success'] = restore(result['job'])
        results.append(result)
        out.write_text(json.dumps(results, ensure_ascii=False, indent=1))
        print(json.dumps(result, ensure_ascii=False), flush=True)
    lines = ['| # | 난도 | 결과 | 시간(분) | 분리(초) | 모델 호출 | 기준 | 사유 |', '|---|---|---|---|---|---|---|---|']
    for r in results:
        lines.append(f"| {r['id']} | {r['level']} | {r['status']} | {r['wall_minutes']} | {r['plan_seconds']} | {r['model_calls']} | "
                     f"{' '.join(f'{a}:{b}' for a, b in r['criteria'])} | {r['reason'][:80]} |")
    out.with_suffix('.md').write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
