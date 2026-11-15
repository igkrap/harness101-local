"""Business flows: what the business is, kept apart from the screens that carry it out.

A flow is a chain of screens a quantity travels through - 발주 → 출발 → 도착 → 수입검사 → 입고. It is registered in plain words
("업무 흐름 등록: 발주서 → 출발 → 도착 → 입고") and kept in the project's release/flows.json, beside the screen definitions and
in the same git. The screens say HOW each step is done (a take-over screen, an automatic follow-up); the flow says WHAT must
come of it. That is why it can judge a change no single screen's checks can see: "arrival creates the receipt by itself" while
the screen that takes receipts over from arrivals is still there would receive the goods twice.

Judging a flow = running it end to end on records made for the occasion, with the screens as they are now:
  - every step is reachable: the next stage's records appear by themselves (an effect), or a take-over screen makes them;
  - the quantity arrives whole at every stage - not more (a second way doubled it), not less (a way lost some);
  - nothing is left open behind: the take-over list of the step before shows nothing more for these records;
  - stock moves exactly once by what entered or left;
  - a follow-up that should move an earlier record's status ("다 입고되면 발주 완료") did.
Every change of a screen in a flow, and every undo, is judged by the flows it touches; a change that breaks one is taken back.
"""
import json
import re
from pathlib import Path

import checks
from checks import Report, sample, fit, _line, _computed, sweep, stock_of

QUANTITY = 10
META = ('id', 'status', 'statusLabel', 'createdBy', 'createdAt', 'updatedBy', 'updatedAt', '_names', '_files', '_stock')


def _file():
    from framework import site
    return Path(site().root) / 'release' / 'flows.json'


def load():
    path = _file()
    try:
        return json.loads(path.read_text(encoding='utf-8')).get('flows', []) if path.is_file() else []
    except ValueError:
        return []


def save(flows):
    path = _file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'flows': flows}, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


def _titled(definition):
    return re.sub(r'\s*(등록|관리|입력)$', '', definition.get('title', ''))


def resolve(names, framework):
    """Screen keys for the names of a flow's stages: a screen's key, its title, or its title without 등록 - screens that keep records only."""
    keeping = {item['key']: item['definition'] for item in framework.definitions()
               if item['definition'].get('fields') and not any(item['definition'].get(part) for part in ('summary', 'dashboard', 'over', 'calendar', 'tree', 'take', 'stockView'))}
    keys, problems = [], []
    for name in names:
        word = name.strip()
        exact = [key for key, one in keeping.items() if word in (key, one.get('title'), _titled(one))]
        loose = [key for key, one in keeping.items() if word and word in one.get('title', '')]
        found = exact or loose
        if len(found) == 1:
            keys.append(found[0])
        else:
            problems.append(f'"{word}": ' + ('그런 등록 화면이 없습니다' if not found else '여러 화면이 맞습니다 - ' + ', '.join(keeping[key]['title'] for key in found)))
    return keys, problems


def _link(known, earlier, later):
    """The limit of `later` against `earlier` and the field of `later` that points at the earlier record."""
    for limit in known[later].get('limits') or []:
        if limit['entity'] == earlier and 'id' in limit['entityBy']:
            return limit, limit['by'][limit['entityBy'].index('id')]
    return None, None


def _value(record, name):
    if name in record:
        return record.get(name)
    lines = record.get('lines') or []
    return lines[0].get(name) if lines and isinstance(lines[0], dict) else None


def _quantity(record, field):
    lines = record.get('lines')
    if lines and any(field in line for line in lines):
        return sum(float(line.get(field) or 0) for line in lines)
    return float(record.get(field) or 0)


def _bring(framework, key, definition, record, wanted):
    """Walk a record through its status actions until it stands in one of the wanted statuses (as a person would)."""
    status = definition.get('status') or {}
    for _ in range(5):
        if not wanted or record.get('status') in wanted:
            return record                       # ('__end__' is never a status: walk on as far as the actions go)
        step = next((action for action in status.get('actions', []) if record.get('status') in action['from'] and action['to'] in wanted), None) \
            or next((action for action in status.get('actions', []) if record.get('status') in action['from'] and action['to'] not in ('CANCELED', 'CANCELLED')
                     and not re.search(r'취소|반려|거절', action['label'])), None)
        if not step:
            return record
        code, answer = framework.call('POST', f"/api/data/{key}/{record['id']}/actions/{step['name']}")
        if code != 200:
            return record
        record = answer
    return record


def simulate(flow, framework):
    """Run the flow end to end and judge it. Everything made is removed again."""
    report, made = Report(), []
    known = {item['key']: item['definition'] for item in framework.definitions()}
    stages = flow['stages']
    missing = [key for key in stages if key not in known]
    if missing:
        report.add(f"흐름의 화면이 모두 있다", False, '없는 화면: ' + ', '.join(missing))
        report.leftover = []
        return report
    title = lambda key: known[key].get('title', key)
    newest = lambda key: max([row['id'] for row in framework.ok('GET', f'/api/data/{key}?_sort=id&_desc=true&_limit=1')] or [0])
    before = {key: newest(key) for key in stages}        # what each stage held before the run: anything newer that is not on the path came from elsewhere
    takes = {(one['take']['from'], one['take']['entity']): key for key, one in known.items() if one.get('take')}
    try:
        first_limit, _ = _link(known, stages[0], stages[1])
        if not report.add(f"{title(stages[1])} 이(가) {title(stages[0])} 의 수량을 한도로 이어진다", first_limit is not None, '두 화면을 잇는 한도(limits)가 없습니다'):
            return report
        root = known[stages[0]]
        body = {field['name']: sample(field, framework, made) for field in root['fields'] if not _computed(field)}
        if root.get('lines'):
            body['lines'] = [_line(root['lines']['fields'], framework, made, QUANTITY)]
        body = fit(body, root, framework, made)
        holder = body['lines'][0] if root.get('lines') and first_limit['entityField'] in body['lines'][0] else body
        holder[first_limit['entityField']] = QUANTITY
        code, record = framework.call('POST', f'/api/data/{stages[0]}', body)
        if not report.add(f"시작: {title(stages[0])} 한 건({QUANTITY})을 등록한다", code == 201, f'{code} {record}'):
            return report
        made.append((stages[0], record['id']))
        current, previous = [record], stages[0]
        moved = {}
        for later in stages[1:]:
            limit, pointer = _link(known, previous, later)
            if not report.add(f"{title(later)} 이(가) {title(previous)} 을(를) 가리켜 이어진다", limit is not None, '한도(limits)가 없어 어느 건에서 왔는지 알 수 없습니다'):
                return report
            ids = [one['id'] for one in current]

            def mine():
                rows = []
                for record_id in ids:
                    rows += [row for row in framework.ok('GET', f'/api/data/{later}?{pointer}={record_id}&_limit=1000') if _value(row, pointer) == record_id]
                return rows
            take = takes.get((previous, later))
            if take and known[take]['take'].get('statuses'):        # the earlier records first stand where the take-over screen lists them
                current = [_bring(framework, previous, known[previous], framework.ok('GET', f"/api/data/{previous}/{one['id']}"), known[take]['take']['statuses']) for one in current]
            existing = mine()
            if not existing and not take:         # no take-over screen: the earlier records are carried on as a person would (their status actions), which may make the next ones
                current = [_bring(framework, previous, known[previous], framework.ok('GET', f"/api/data/{previous}/{one['id']}"), ['__end__']) for one in current]
                existing = mine()
            route = '자동 처리' if existing else ''
            if not existing and take:
                shape = framework.ok('GET', f'/api/take/{take}/shape')
                open_rows = [row for row in framework.ok('GET', f'/api/take/{take}') if row['sourceId'] in ids]
                values = {field['name']: sample(field, framework, made) for field in known[later]['fields'] if field['name'] in shape.get('ask', []) and not _computed(field)}
                rows = [{'sourceId': row['sourceId'], 'line': row['line'], 'quantity': row['remaining'],
                         'values': {field['name']: sample(field, framework, made) for field in shape.get('askLines') or [] if field.get('required')}} for row in open_rows]
                part = known[later].get('stock')
                if part and part['direction'] in ('out', 'move'):
                    house = values.get(part['warehouse'])
                    for row in open_rows:
                        item = (row.get('unit') or {}).get(dict(zip(limit['by'], limit['entityBy'])).get(part['item'], part['item'])) or row['head'].get(dict(zip(limit['by'], limit['entityBy'])).get(part['item'], part['item']))
                        if item and house and stock_of(framework, item, house) < row['remaining']:
                            framework.ok('POST', '/api/system/stock/adjust', {'itemEntity': part['itemEntity'], 'itemId': item, 'warehouseEntity': part['warehouseEntity'], 'warehouseId': house, 'quantity': row['remaining'], 'unitCost': 100})
                code, answer = framework.call('POST', f'/api/take/{take}', {'values': values, 'rows': rows})
                if not report.add(f"{title(previous)} → {title(later)}: 이어받기 화면({known[take]['title']})으로 넘긴다", code == 200 and rows, f'{code} {answer}' if code != 200 else f'넘길 줄 {len(rows)}개'):
                    return report
                existing, route = mine(), '이어받기'
            if not report.add(f"{title(previous)} → {title(later)}: 넘어가는 길이 있다", bool(existing), '자동 처리도 이어받기 화면도 없습니다 - 흐름이 여기서 끊깁니다'):
                return report
            for one in existing:
                made.append((later, one['id']))
            total = sum(_quantity(one, limit['field']) for one in existing)
            report.add(f"{title(later)}: {title(previous)} 의 수량({QUANTITY})이 그대로 넘어온다 ({route})", abs(total - QUANTITY) < 1e-9, f'넘어온 수량 {total:g}')
            if take:          # nothing left behind, and no second way: the take-over list shows nothing more for these records
                still = [row for row in framework.ok('GET', f'/api/take/{take}') if row['sourceId'] in ids]
                report.add(f"{title(previous)} → {title(later)}: 넘긴 뒤 이어받기 목록에 남은 것이 없다" + (' (자동으로 만들어졌는데 손으로 또 넘길 길이 열려 있으면 두 번 처리됩니다)' if route == '자동 처리' else ''),
                           not still, f"남은 줄 {[(row['sourceId'], row['remaining']) for row in still]}")
            part = known[later].get('stock')
            if part:
                sign = {'in': 1, 'out': -1}.get(part['direction'])
                full = [framework.ok('GET', f"/api/data/{later}/{one['id']}") for one in existing]
                net = sum(float(move['quantity']) * (1 if move['direction'] == 'IN' else -1) for one in full for move in one.get('_stock') or [])
                if sign:
                    moved[later] = net
                    report.add(f"{title(later)}: 재고가 한 번만 {'늘어난다' if sign > 0 else '줄어든다'} ({QUANTITY})", abs(net - sign * QUANTITY) < 1e-9, f'움직인 수량 {net:g}')
                elif part['direction'] == 'move':
                    report.add(f"{title(later)}: 창고 이동은 재고 합계를 바꾸지 않는다", abs(net) < 1e-9, f'움직인 수량 합 {net:g}')
            current, previous = existing, later
        # records the run made that are not on the path: a second way that does not point back (a shipment made by itself, unlinked)
        on_path = {(key, record) for key, record in made}
        for key in stages:
            strays = [row['id'] for row in framework.ok('GET', f'/api/data/{key}?_sort=id&_desc=true&_limit=200') if row['id'] > before[key] and (key, row['id']) not in on_path]
            made.extend((key, record) for record in strays)
            report.add(f"{title(key)}: 흐름 밖에서 따로 생긴 자료가 없다 (같은 일이 두 번 처리되지 않는다)", not strays, f'흐름의 건을 가리키지 않는 {title(key)} {len(strays)}건이 생겼습니다')
        # follow-ups: an earlier record that should have moved on once everything arrived
        for later in stages:
            for effect in known[later].get('effects') or []:
                fill = effect.get('fill')
                if not fill or fill['entity'] not in stages:
                    continue
                target = known[fill['entity']]
                action = next((one for one in (target.get('status') or {}).get('actions', []) if one['name'] == fill['action']), None)
                records = [one for key, one in made if key == fill['entity']]
                if action and records:
                    now = framework.ok('GET', f"/api/data/{fill['entity']}/{records[0]}")
                    names = {value['code']: value['label'] for value in target['status']['values']}
                    report.add(f"{title(fill['entity'])}: 수량이 다 차면 {names.get(action['to'], action['to'])} 상태가 된다", now.get('status') == action['to'], f"지금 상태 {names.get(now.get('status'), now.get('status'))}")
    except Exception as problem:
        report.add('흐름을 끝까지 돌린다', False, str(problem)[:300])
    finally:
        report.leftover = sweep(framework, made)
    return report


def touching(keys, framework, flows=None):
    """The flows a change of these screens can affect: those that hold them, or whose two stages a changed take-over screen joins."""
    known = {item['key']: item['definition'] for item in framework.definitions()}
    out = []
    for flow in load() if flows is None else flows:
        pairs = set(zip(flow['stages'], flow['stages'][1:]))
        for key in keys:
            take = (known.get(key) or {}).get('take')
            if key in flow['stages'] or (take and (take['from'], take['entity']) in pairs):
                out.append(flow)
                break
    return out


def judge(keys, framework):
    """Every flow the change touches, run end to end. Returns (all passed, the results, lines of plain words)."""
    results, lines, passed = [], [], True
    for flow in touching(keys, framework):
        report = simulate(flow, framework)
        results += [dict(item, description=f"[업무 흐름 {flow['name']}] {item['description']}") for item in report.results]
        if not report.passed:
            passed = False
            lines.append(f"업무 흐름 '{flow['name']}' 이(가) 맞지 않습니다: " + '; '.join(item['description'] + ' - ' + str(item.get('detail', ''))[:160] for item in report.results if not item['passed']))
    return passed, results, lines


def handle(request, framework):
    """'업무 흐름 등록: A → B → C' / '업무 흐름 삭제: <이름>' / '업무 흐름 보기'. Returns a result for run.say()."""
    text = request.split(':', 1)[1].strip() if ':' in request else ''
    flows = load()
    if '삭제' in request.split(':', 1)[0]:
        kept = [flow for flow in flows if flow['name'] != text]
        if len(kept) == len(flows):
            return {'status': 'flow', 'ok': False, 'lines': [f'그런 업무 흐름이 없습니다: {text}. 있는 흐름: ' + (', '.join(flow['name'] for flow in flows) or '없음')]}
        save(kept)
        return {'status': 'flow', 'ok': True, 'changed': True, 'lines': [f'업무 흐름을 지웠습니다: {text}']}
    if '보기' in request.split(':', 1)[0] or not text:
        return {'status': 'flow', 'ok': True, 'lines': [f"{flow['name']}: " + ' → '.join(flow['stages']) for flow in flows] or ['등록된 업무 흐름이 없습니다.']}
    names = [part for part in re.split(r'\s*(?:→|->|>|⇒)\s*', text) if part.strip()]
    if len(names) < 2:
        return {'status': 'flow', 'ok': False, 'lines': ['업무 흐름은 화면 이름을 화살표로 이어 적습니다. 예: 업무 흐름 등록: 발주서 → 입고']}
    keys, problems = resolve(names, framework)
    if problems:
        return {'status': 'flow', 'ok': False, 'lines': ['업무 흐름의 화면을 찾지 못했습니다:'] + ['  - ' + problem for problem in problems]}
    flow = {'name': ' → '.join(names), 'stages': keys}
    report = simulate(flow, framework)
    lines = [f"업무 흐름: {flow['name']}", f"끝까지 돌려 본 검사 {len(report.results)}개 중 {sum(1 for item in report.results if item['passed'])}개 통과"]
    lines += [('  ✓ ' if item['passed'] else '  ✗ ') + item['description'] + ('' if item['passed'] else ' - ' + str(item.get('detail', ''))[:200]) for item in report.results]
    if not report.passed:
        lines.append('등록하지 않았습니다. 지금 화면들로는 이 흐름이 끝까지 맞게 흐르지 않습니다.')
        return {'status': 'flow', 'ok': False, 'lines': lines, 'results': report.results}
    save([one for one in flows if one['name'] != flow['name']] + [flow])
    lines.append('등록했습니다. 이 흐름에 든 화면을 바꾸거나 되돌릴 때마다 이 흐름을 끝까지 다시 돌려 봅니다.')
    return {'status': 'flow', 'ok': True, 'changed': True, 'lines': lines, 'results': report.results}
