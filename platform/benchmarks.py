"""Measurement: a set of plain requests run in order on a project made for the occasion, so a change of the framework, the parts'
description or the model can be judged by numbers instead of by impression.

A set is a name and its requests (one per line, in the order a person would ask them; the last may register a business flow).
A run makes a throwaway project, puts the requests through the same queue a person's requests go through (one at a time, the stop
button and the live view work as always), keeps for every request how it ended and what it took, and removes the project at the
end. Runs are kept with what they ran on (model, framework version, the model's instructions) so two runs can be set side by side.
"""
import hashlib
import json
import threading
import time
import uuid

import sites

ROOT = sites.ROOT / 'platform/state/benchmarks'
SETS = ROOT / 'sets.json'
RUNS = ROOT / 'runs'
OUTCOMES = ('첫 시도 통과', '재시도 후 완료', '요청대로 안 됨', '점검 실패', '확인 못 함', '부품 없음', '중지', '오류')
_lock = threading.Lock()
_current = {'run': None, 'stop': False}


def _read(path, empty):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return empty


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    temporary.replace(path)


def _now():
    return time.strftime('%Y/%m/%d %H:%M:%S')


# ---- sets -------------------------------------------------------------------------------------------------------------------------

def save_set(body):
    name = str(body.get('name') or '').strip()
    text = body.get('requests')
    requests = [line.strip() for line in (text.splitlines() if isinstance(text, str) else text or []) if str(line).strip()]
    if not name or len(name) > 40:
        raise ValueError('측정 묶음 이름을 1~40자로 적으세요.')
    if not 1 <= len(requests) <= 40:
        raise ValueError('요청 문장을 한 줄에 하나씩, 1~40개 적으세요.')
    with _lock:
        sets = _read(SETS, [])
        found = next((item for item in sets if item['id'] == body.get('id')), None)
        if found:
            found.update(name=name, requests=requests, changed=_now())
        else:
            found = {'id': uuid.uuid4().hex[:10], 'name': name, 'requests': requests, 'created': _now()}
            sets.append(found)
        _write(SETS, sets)
    return found


def delete_set(set_id):
    with _lock:
        sets = _read(SETS, [])
        _write(SETS, [item for item in sets if item['id'] != set_id])
    return {'deleted': set_id}


# ---- runs -------------------------------------------------------------------------------------------------------------------------

def _summary(run):
    items = run['items']
    counts = {outcome: sum(1 for item in items if item.get('outcome') == outcome) for outcome in OUTCOMES}
    timed = [item['seconds'] for item in items if item.get('seconds')]
    return {'id': run['id'], 'set': run['set'], 'name': run['name'], 'started': run['started'], 'ended': run.get('ended'), 'state': run['state'],
            'total': len(run['requests']), 'done': len(items), 'counts': counts,
            'passed': counts['첫 시도 통과'] + counts['재시도 후 완료'], 'first_try': counts['첫 시도 통과'],
            'invented': sum(item.get('invented', 0) for item in items), 'average': round(sum(timed) / len(timed)) if timed else None,
            'versions': run.get('versions', {})}


def listing():
    sets = _read(SETS, [])
    runs = [_read(path, None) for path in sorted(RUNS.glob('*.json'), reverse=True)] if RUNS.is_dir() else []
    runs = [_summary(run) for run in runs if run]
    return {'sets': sets, 'runs': runs, 'running': _current['run'], 'outcomes': list(OUTCOMES)}


def run_detail(run_id):
    run = _read(RUNS / f'{run_id}.json', None)
    if not run:
        raise ValueError('그 측정 기록이 없습니다.')
    return {**run, 'summary': _summary(run)}


def _versions(hub):
    out = {}
    try:
        import sys
        harness = str(sites.ROOT / 'harness2')
        if harness not in sys.path:
            sys.path.insert(0, harness)
        import define
        import llm
        out['instructions'] = hashlib.md5(define.PROMPT.encode('utf-8')).hexdigest()[:10]
        out['model'] = llm.model_id()
    except Exception as problem:
        out['note'] = str(problem)[:120]
    try:
        import framework_update
        out['framework'] = framework_update.version()
    except Exception:
        pass
    return out


def _outcome(queue, result, live_state):
    """How a request ended, in the words the measurement counts."""
    status, error = (result or {}).get('status'), str((result or {}).get('error') or '')
    if queue['status'] == 'stopped' or error.startswith('중지'):
        return '중지'
    if status in ('applied', 'flow') and (status != 'flow' or result.get('ok')):
        return '재시도 후 완료' if 'first_try' in result else '첫 시도 통과'
    if status == 'needs-part':
        return '부품 없음'
    if '맞춰 보지 못해' in error:
        return '확인 못 함'
    if (result or {}).get('unmet'):
        return '요청대로 안 됨'
    if status in ('failed', 'flow'):
        return '점검 실패'
    return '오류'


def _invented(live_state):
    """How often the plan was sent back for bringing in what the request did not say (or the result for differing from it)."""
    steps = (live_state or {}).get('steps') or []
    return sum(1 for step in steps if str(step.get('detail') or '').startswith(('단계 문장이 요청에 없는 것을 덧붙였다', '요청과 다르다')))


def start(hub, set_id):
    with _lock:
        if _current['run']:
            raise RuntimeError('이미 측정이 돌고 있습니다.')
        chosen = next((item for item in _read(SETS, []) if item['id'] == set_id), None)
        if not chosen:
            raise ValueError('그 측정 묶음이 없습니다.')
        if hub.busy() or any(app.queues.active() for app in list(hub.apps.values())):
            raise RuntimeError('실행 중인 요청이 끝난 뒤에 측정할 수 있습니다.')
        run_id = time.strftime('%Y%m%d-%H%M%S')
        run = {'id': run_id, 'set': chosen['id'], 'name': chosen['name'], 'requests': list(chosen['requests']), 'items': [],
               'started': _now(), 'state': '준비 중', 'versions': {}}
        _write(RUNS / f'{run_id}.json', run)
        _current.update(run=run_id, stop=False)
    threading.Thread(target=_go, args=(hub, run), daemon=True).start()
    return _summary(run)


def stop():
    if not _current['run']:
        raise RuntimeError('돌고 있는 측정이 없습니다.')
    _current['stop'] = True
    return {'stopping': _current['run']}


def _go(hub, run):
    import projects
    path = RUNS / f"{run['id']}.json"
    record, stopped = None, False
    slug = 'bench-' + run['id'].replace('-', '')[-8:]
    try:
        run['versions'] = _versions(hub)
        run['state'] = '프로젝트 만드는 중'
        _write(path, run)
        record = projects.create(hub, {'title': f"측정 {run['name']}"[:40], 'slug': slug, 'kind': 'business'})
        run['project'] = slug
        app = hub.resolve(record['id'])
        for index, request in enumerate(run['requests'], 1):
            if _current['stop']:
                stopped = True
                break
            run['state'] = f"{index}/{len(run['requests'])} 요청 중"
            _write(path, run)
            while hub.busy() or any(one.queues.active() for one in list(hub.apps.values())):      # (a person's request anywhere goes first)
                time.sleep(3)
            started = time.time()
            queue = app.queues.create({'goal': request, 'origin': 'measurement'})
            while True:
                time.sleep(3)
                if _current['stop'] and queue and app.queues.get(queue['id'])['status'] in ('planning', 'running'):
                    try:
                        app.queues.stop(queue['id'])
                    except Exception:
                        pass
                current = app.queues.get(queue['id'])
                if current['status'] not in ('planning', 'running', 'stopping'):
                    break
            import live
            state = live.snapshot(slug)
            result = current.get('definition_result') or {}
            run['items'].append({'request': request, 'outcome': _outcome(current, result, state), 'seconds': round(time.time() - started),
                                 'calls': (state or {}).get('calls'), 'tokens': (state or {}).get('tokens'), 'checks': result.get('checks'),
                                 'invented': _invented(state), 'said': str(current.get('detail') or '')[:600], 'queue': current['id']})
            _write(path, run)
            if current['status'] == 'stopped':          # stopped from the live view: the measurement stops with it
                stopped = True
                break
        run['state'] = '멈춤' if stopped or _current['stop'] else '끝남'
    except Exception as problem:
        run['state'] = '오류'
        run['error'] = str(problem)[:400]
    finally:
        if record is not None:
            try:
                projects.remove(hub, record['id'], slug)
            except Exception as problem:
                run['cleanup'] = '측정용 프로젝트를 지우지 못했습니다: ' + str(problem)[:200]
        run['ended'] = _now()
        _write(path, run)
        with _lock:
            _current.update(run=None, stop=False)
