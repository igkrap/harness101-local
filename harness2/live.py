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


class Stopped(BaseException):
    """The person pressed stop: the run ends where it is (what it applied is taken back like any failure). Not an Exception: the
    `except Exception` on the way (a refusal sent back to the model, a check that could not be asked) must not swallow it - it was
    raised once only, so a swallowed stop was a stop lost and the run went on (and could apply). run.py catches it at the top."""


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
            import socket
            if getattr(response, 'sock', None) is not None:
                response.sock.shutdown(socket.SHUT_RDWR)      # wakes a read that is waiting for the model at once
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


LOG = None                     # the model server's log, where it says how far it has read (set from the platform's place)
_ratio = {'chars_per_token': 1.3}      # learned from each answer's usage: how many characters of input one token is


def _log():
    global LOG
    if LOG is None:
        try:
            from sites import ROOT
            LOG = ROOT / 'platform/state/qwen-model-server.log'
        except Exception:
            return None
    return LOG


def _read_progress(since):
    """How far the model server has read the input it was given at `since`: (done, total) tokens of what it reads anew
    (what it read before and kept is skipped, and is the input's beginning), or None."""
    import re as _re, datetime as _dt
    path = _log()
    if not path or not path.exists():
        return None
    with open(path, 'rb') as handle:
        handle.seek(0, 2)
        handle.seek(max(0, handle.tell() - 20000))
        tail = handle.read().decode('utf-8', 'replace').splitlines()
    for line in reversed(tail):
        found = _re.match(r'(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ - INFO - Prompt processing progress: (\d+)/(\d+)', line)
        if found:
            at = _dt.datetime.strptime(found.group(1), '%Y-%m-%d %H:%M:%S').timestamp()
            return (int(found.group(2)), int(found.group(3))) if at >= since - 2 else None
    return None


def _section(text, pos):
    """The heading of the part being read: the nearest line before it that looks like one."""
    import re as _re
    for line in reversed(text[:pos].splitlines()[-400:]):
        line = line.strip()
        if _re.fullmatch(r'[A-Z][A-Z0-9 /()&.,+-]{3,60}', line) or _re.fullmatch(r'\[[^\]]{2,40}\]', line) or (line.startswith(('■', '#')) and len(line) < 80) \
                or (line.endswith(':') and len(line) < 40):
            return line.strip('#[]: ')
    return ''


def model_start(name, model, messages=None):
    title = MODEL_NAMES.get(name) or ('모델이 정의를 씀' if name == 'define-1' else f"모델이 정의를 고쳐 씀 ({name.rsplit('-', 1)[-1]}번째)" if name.startswith('define-') else f'모델: {name}')
    step(title)
    with _lock:
        run = _run()
        if run:
            run['calls'] += 1
            given = '\n\n'.join(f"[{item.get('role')}]\n{item.get('content') or ''}" for item in messages or [])
            run['model'] = {'name': name, 'model': model, 'title': title, 'started': time.time(), 'ended': None, 'first': None, 'text': '', 'thinking': '', 'tokens': 0, 'chunks': 0,
                            '_input': given}


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
            if (usage or {}).get('prompt_tokens') and run['model'].get('_input'):
                _ratio['chars_per_token'] = max(0.5, min(4.0, len(run['model']['_input']) / usage['prompt_tokens']))
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
            out['model'] = {key: value for key, value in model.items() if key not in ('text', 'thinking') and not key.startswith('_')}
            out['model'].update(chars=len(model['text']), text=model['text'][-tail:], thinking=model['thinking'][-tail:], input_chars=len(model.get('_input') or ''))
            given = model.get('_input') or ''
            if given and not model['chunks'] and not model['ended']:          # still reading its input: where it is in it
                progress = _read_progress(model['started'])
                if progress:
                    done, total = progress
                    pos = max(0, min(len(given), int(len(given) - (total - done) * _ratio['chars_per_token'])))
                    out['model']['reading'] = {'done': done, 'total': total, 'skipped': max(0, int(len(given) / _ratio['chars_per_token']) - total),
                                               'pos': pos, 'section': _section(given, pos), 'before': given[max(0, pos - 2500):pos], 'after': given[pos:pos + 900]}
        out['now'] = time.time()
        return out
