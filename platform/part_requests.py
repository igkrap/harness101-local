"""Parts the framework does not have yet, asked for by requests the model could not answer with the parts there are.

The framework's parts are the same for every project (platform/base), so the list is the platform's, not a project's. A request
that needs a missing part is not forced into the nearest part: the model names the part it would need and why, the person is told
so, and the part lands here - one line per part, counted each time it is asked for again - for a person to decide (made / not made).
"""
import json
import re
import threading
import time
import uuid

import sites

PATH = sites.ROOT / 'platform/state/part-requests.json'
STATES = ('대기', '만듦', '안 함')
_lock = threading.Lock()


def _read():
    try:
        return json.loads(PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []


def _write(items):
    PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = PATH.with_suffix('.tmp')
    temporary.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding='utf-8')
    temporary.replace(PATH)


def _same(text):
    return re.sub(r'[\s.,·()"\'「」]+', '', text or '')


def add(part, why, request, project=''):
    """One more request for a part: a part asked for before (same words) counts up and keeps the new request beside the old ones."""
    part, why = str(part or '').strip()[:200], str(why or '').strip()[:300]
    if not part:
        return None
    now = time.strftime('%Y/%m/%d %H:%M:%S')
    with _lock:
        items = _read()
        for item in items:
            if _same(item['part']) == _same(part) and item['state'] == '대기':
                item['count'] += 1
                item['last'] = now
                item['asks'] = (item['asks'] + [{'when': now, 'project': project, 'request': request[:300], 'why': why}])[-20:]
                _write(items)
                return item
        item = {'id': uuid.uuid4().hex[:12], 'part': part, 'state': '대기', 'count': 1, 'first': now, 'last': now,
                'asks': [{'when': now, 'project': project, 'request': request[:300], 'why': why}]}
        items.append(item)
        _write(items)
        return item


def listing():
    with _lock:
        items = _read()
    order = {state: index for index, state in enumerate(STATES)}
    items = sorted(items, key=lambda item: item['last'], reverse=True)        # newest first, then by state and how often asked
    return sorted(items, key=lambda item: (order.get(item['state'], 9), -item['count']))


def decide(item_id, state):
    if state not in STATES:
        raise ValueError('상태는 ' + ' / '.join(STATES) + ' 중 하나입니다.')
    with _lock:
        items = _read()
        for item in items:
            if item['id'] == item_id:
                item['state'] = state
                item['decided'] = time.strftime('%Y/%m/%d %H:%M:%S')
                _write(items)
                return item
    raise ValueError('그 부품 요청이 없습니다.')
