"""What a request is doing right now, for the platform's monitor: the steps so far, what the model is writing as it writes it,
each check as it passes or fails. Kept in memory (the harness runs inside the platform's process, one request at a time per
project) and read by the platform while the request runs; nothing here changes what the run does."""
import threading
import time

_lock = threading.Lock()
_runs = {}          # project slug -> the run being watched (kept after it ends, until the next one starts)
MODEL_NAMES = {'matches-request': '요청과 맞는지 모델이 확인', 'removed-on-purpose': '빠진 항목이 일부러인지 모델이 확인'}


def _slug():
    try:
        from sites import site
        return site().slug
    except Exception:
        return 'default'


def _run():
    return _runs.get(_slug())


def begin(goal, queue=None):
    with _lock:
        _runs[_slug()] = {'goal': goal, 'queue': queue, 'started': time.time(), 'ended': None, 'ok': None, 'said': '', 'steps': [], 'model': None, 'checks': [], 'calls': 0, 'tokens': 0}


class Stopped(Exception):
    """The person pressed stop: the run ends where it is (what it applied is taken back like any failure)."""


def stop(slug=None):
    """Asked from the platform's stop button: the next step, check or piece of the model's answer ends the run - and a model answer
    being read or written is cut off at once (its connection closed)."""
    with _lock:
        run = _runs.get(slug or _slug())
        if not run or run['ended']:
            return False
        run['_stop'] = True
        response = run.get('_response')
    if response is not None:
        try:
            response.close()
        except Exception:
            pass
    return True


def stopping():
    """Raises once where the run is when stop was pressed; after that the run's own clean-up (taking back what it applied) goes on."""
    with _lock:
        run = _run()
        if not run or run.get('_stop') is not True:
            return
        run['_stop'] = 'raised'
    raise Stopped('중지했습니다.')


def attach(response):
    with _lock:
        run = _run()
        if run:
            run['_response'] = response


def step(title, detail=''):
    """A new step starts (the one before it ends here, unless it already did)."""
    stopping()
    with _lock:
        run = _run()
        if not run:
            return
        now = time.time()
        for item in run['steps']:
            if item['state'] == 'running':
                item.update(state='done', ended=now)
        run['steps'].append({'title': title, 'detail': detail, 'state': 'running', 'started': now, 'ended': None})


def end_step(state='done', detail=None):
    with _lock:
        run = _run()
        if run and run['steps'] and run['steps'][-1]['state'] == 'running':
            run['steps'][-1].update(state=state, ended=time.time(), **({'detail': detail} if detail is not None else {}))


def model_start(name, model):
    title = MODEL_NAMES.get(name) or ('모델이 정의를 씀' if name == 'define-1' else f"모델이 정의를 고쳐 씀 ({name.rsplit('-', 1)[-1]}번째)" if name.startswith('define-') else f'모델: {name}')
    step(title)
    with _lock:
        run = _run()
        if run:
            run['calls'] += 1
            run['model'] = {'name': name, 'model': model, 'title': title, 'started': time.time(), 'ended': None, 'first': None, 'text': '', 'thinking': '', 'tokens': 0, 'chunks': 0}


def model_chunk(text='', thinking=''):
    with _lock:
        run = _run()
        if run and run['model']:
            if not run['model']['chunks']:
                run['model']['first'] = time.time()        # before this the model was reading its input
            run['model']['text'] += text
            run['model']['thinking'] += thinking
            run['model']['chunks'] += 1


def model_end(usage=None):
    with _lock:
        run = _run()
        if run and run['model']:
            tokens = (usage or {}).get('completion_tokens') or run['model']['chunks']
            run['model'].update(ended=time.time(), tokens=tokens)
            run['tokens'] += tokens
    end_step()


def check(description, passed, detail=''):
    stopping()
    with _lock:
        run = _run()
        if run:
            run['checks'].append({'description': description, 'passed': bool(passed), 'detail': '' if passed else str(detail)[:300], 'at': time.time(),
                                  'step': run['steps'][-1]['title'] if run['steps'] else ''})


def finish(ok, said=''):
    with _lock:
        run = _run()
        if run:
            run.pop('_response', None)
    end_step()
    with _lock:
        run = _run()
        if run:
            run.update(ended=time.time(), ok=bool(ok), said=said)


def snapshot(slug=None, tail=6000):
    """The run as the monitor shows it. The model's text is cut to its last part (the screen shows where it is writing)."""
    with _lock:
        run = _runs.get(slug or _slug())
        if not run:
            return None
        out = {key: value for key, value in run.items() if key not in ('model', 'checks', 'steps') and not key.startswith('_')}
        out['stopping'] = bool(run.get('_stop')) and not run['ended']
        out['steps'] = [dict(item) for item in run['steps']]
        out['checks'] = {'total': len(run['checks']), 'passed': sum(1 for item in run['checks'] if item['passed']), 'recent': run['checks'][-40:],
                         'failed': [item for item in run['checks'] if not item['passed']][-20:]}
        model = run['model']
        if model:
            out['model'] = {key: value for key, value in model.items() if key not in ('text', 'thinking')}
            out['model'].update(chars=len(model['text']), text=model['text'][-tail:], thinking=model['thinking'][-tail:])
        out['now'] = time.time()
        return out
