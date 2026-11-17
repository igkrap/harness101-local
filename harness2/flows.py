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
  - the ledger moves exactly once by what entered or left;
  - a follow-up that should move an earlier record's status ("다 입고되면 발주 완료") did.
Every change of a screen in a flow, and every undo, is judged by the flows it touches; a change that breaks one is taken back.
"""
import json
import re
from pathlib import Path

import checks
from checks import Report, sample, fit, _line, _computed, sweep, held

QUANTITY = 10
META = ('id', 'status', 'statusLabel', 'createdBy', 'createdAt', 'updatedBy', 'updatedAt', '_names', '_files', '_ledger')


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
               if (item['definition'].get('fields') and not any(item['definition'].get(part) for part in ('summary', 'dashboard', 'over', 'calendar', 'tree', 'take', 'ledgerView')))
               or (item['definition'].get('over') and item['definition']['over'].get('actions'))}      # a work screen where a record takes its next step
    keys, problems = [], []
    for name in names:
        word = name.strip()
        exact = [key for key, one in keeping.items() if word in (key, one.get('title'), _titled(one))]
        loose = [key for key, one in keeping.items() if word and word in one.get('title', '')]
        found = exact or loose
        if len(found) == 1:
            keys.append(found[0])
        else:
            problems.append(f'"{word}": ' + ('그런 화면이 없습니다' if not found else '여러 화면이 맞습니다 - ' + ', '.join(keeping[key]['title'] for key in found)))
    return keys, problems


def _link(known, earlier, later):
    """The limit of `later` against `earlier` and the field of `later` that points at the earlier record."""
    for limit in known[later].get('limits') or []:
        if limit['entity'] == earlier and 'id' in limit['entityBy']:
            return limit, limit['by'][limit['entityBy'].index('id')]
    return None, None


def _expansion(known, earlier, later):
    """`earlier` makes the `later` records by itself from master data when it is registered (a work order → its planned issues from
    the BOM): the expansion, and the field of `later` that points back at the earlier record."""
    for effect in known[earlier].get('effects') or []:
        part = effect.get('expand')
        if effect.get('on') == 'create' and part and part.get('into') == later:
            part = dict(part)
            if isinstance(part.get('quantity'), dict):          # as written: {"into", "line", "times"}
                part.update(quantityInto=part['quantity'].get('into'), quantityLine=part['quantity'].get('line'), quantityTimes=part['quantity'].get('times'))
            pointer = next((into for into, come in (part.get('set') or {}).items() if come == 'id'), None)
            if pointer:
                return part, pointer
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
    # Work screens are steps of the record they open (a report received → assigned → confirmed): stages of the same entity fold into one,
    # and its records are walked through those screens' actions where the flow names them.
    plan = []
    for key in stages:
        entity = (known[key].get('over') or {}).get('entity') or key
        if not plan or plan[-1][0] != entity:
            plan.append((entity, []))
        if known[key].get('over'):
            plan[-1][1].append(key)
    walks = dict(plan)
    stages = [entity for entity, _ in plan]
    # A first stage the next one only chooses from (master data: a facility a report is about) is not a stage records flow out of.
    if len(stages) >= 2 and not _link(known, stages[0], stages[1])[0] and not _expansion(known, stages[0], stages[1])[0]:
        chooser = next((field for field in known[stages[1]].get('fields', []) if (field.get('ref') or {}).get('entity') == stages[0]), None)
        if chooser:
            report.add(f"{title(stages[0])} 은(는) {title(stages[1])} 이(가) 고르는 기준 정보다 ({chooser['label']})", True)
            stages = stages[1:]

    def walk(entity, records):
        """Take the records through the work screens the flow names for this entity, as a person would: each screen lists them and its
        action moves them on."""
        out = list(records)
        for key in walks.get(entity, []):
            part = known[key]['over']
            status = known[entity].get('status') or {}
            labels = {value['code']: value['label'] for value in status.get('values', [])}
            if part.get('statuses'):         # the steps between are taken on the record's own screen first, as a person would
                out = [one if one.get('status') in part['statuses'] else _bring(framework, entity, known[entity], one, part['statuses']) for one in out]
            listed = {row['id'] for row in framework.ok('GET', f'/api/over/{key}?_limit=1000')}
            if not report.add(f"{title(key)}: 앞 단계의 {title(entity)} 이(가) 이 화면에 보인다", all(one['id'] in listed for one in out),
                              f"보이지 않는 건 {[one['id'] for one in out if one['id'] not in listed]} (상태 {[labels.get(one.get('status'), one.get('status')) for one in out]})"):
                continue
            moved = []
            for one in out:
                step = next((action for action in status.get('actions', []) if action['name'] in part['actions'] and one.get('status') in action['from']
                             and not re.search(r'취소|반려|거절|거부|돌려', action['label'])), None)
                if not step:
                    report.add(f"{title(key)}: 이 화면에서 {title(entity)} 을(를) 다음으로 넘기는 동작이 있다", False, f"상태 {labels.get(one.get('status'), one.get('status'))} 에서 할 동작이 없습니다")
                    moved.append(one)
                    continue
                code, answer = framework.call('POST', f"/api/over/{key}/{one['id']}/actions/{step['name']}")
                report.add(f"{title(key)}: {step['label']} 하면 {labels.get(step['to'], step['to'])} 상태가 된다", code == 200 and answer.get('status') == step['to'], f'{code} {answer}')
                moved.append(answer if code == 200 else one)
            out = moved
        return out
    newest = lambda key: max([row['id'] for row in framework.ok('GET', f'/api/data/{key}?_sort=id&_desc=true&_limit=1')] or [0])
    takes = {(checks.take_of(one, key)['from'], checks.take_of(one, key)['entity']): key for key, one in known.items() if checks.take_of(one, key)}
    stored = [key for key, one in known.items() if one.get('fields')]
    start = max([newest(key) for key in stored] or [0])        # ids come from one sequence: anything after this was made during the run
    try:
        first_limit, _ = _link(known, stages[0], stages[1]) if len(stages) > 1 else (None, None)
        expansion, _ = _expansion(known, stages[0], stages[1]) if len(stages) > 1 else (None, None)
        if len(stages) > 1 and not report.add(f"{title(stages[1])} 이(가) {title(stages[0])} 에서 이어진다 ({'기준 정보로 저절로 만들어짐' if expansion and not first_limit else '수량 한도'})",
                          first_limit is not None or expansion is not None, '두 화면을 잇는 한도(limits)도, 등록하면 저절로 만들어지는 길(expand)도 없습니다'):
            return report
        root = known[stages[0]]
        body = {field['name']: sample(field, framework, made) for field in root['fields'] if not _computed(field)}
        if root.get('lines'):
            body['lines'] = [_line(root['lines']['fields'], framework, made, QUANTITY)]
        body = fit(body, root, framework, made)
        expected = {stages[0]: QUANTITY}
        if first_limit and not first_limit.get('field'):       # followed once: one record goes on as one
            expected[stages[0]] = 1
        elif first_limit:
            holder = body['lines'][0] if root.get('lines') and first_limit['entityField'] in body['lines'][0] else body
            holder[first_limit['entityField']] = QUANTITY
        elif expansion:
            # the master data it draws on, valid on any day: one record (one pair of a BOM, or a master with two lines)
            master = known[expansion['from']]
            if expansion.get('quantityTimes'):
                body[expansion['quantityTimes']] = QUANTITY
            given = {field['name']: sample(field, framework, made) for field in master['fields'] if not _computed(field)}
            if master.get('lines'):
                given['lines'] = [_line(master['lines']['fields'], framework, made, 2 + index) for index in range(2)]
            for theirs, mine in expansion['match'].items():
                given[theirs] = body.get(mine)
            given = fit(given, master, framework, made)
            for theirs, mine in expansion['match'].items():
                given[theirs] = body.get(mine)
            if master.get('effective'):
                given[master['effective']['from']] = '2000-01-01'
                if master['effective'].get('to'):
                    given[master['effective']['to']] = None
            code, kept = framework.call('POST', f"/api/data/{expansion['from']}", given)
            if not report.add(f"준비: {title(expansion['from'])} 에 맞는 기준 정보를 둔다", code == 201, f'{code} {kept}'):
                return report
            made.append((expansion['from'], kept['id']))
            per = [float(line.get(expansion['quantityLine']) or 0) for line in (kept.get('lines') if master.get('lines') else [kept])]
            expected[stages[1]] = sum(per) * (QUANTITY if expansion.get('quantityTimes') else 1)
            expected['_count'] = len(per)
        code, record = framework.call('POST', f'/api/data/{stages[0]}', body)
        if not report.add(f"시작: {title(stages[0])} 한 건" + (f"({QUANTITY})" if (first_limit and first_limit.get('field')) or expansion else '') + "을 등록한다", code == 201, f'{code} {record}'):
            return report
        made.append((stages[0], record['id']))
        # what each stage holds once the starting record stands (what was made to set it up - the work order behind a requirement - is not
        # the flow's doing): anything newer that is not on the path came from a second way
        before = {key: newest(key) for key in stages}
        current, previous = walk(stages[0], [record]), stages[0]
        moved = {}
        for later in stages[1:]:
            limit, pointer = _link(known, previous, later)
            grown, grown_pointer = _expansion(known, previous, later)
            if limit is None and grown is not None and previous == stages[0]:
                # made by itself from master data when the earlier record was registered: as many as the master has, at line quantity × this one
                rows = [row for row in framework.ok('GET', f'/api/data/{later}?{grown_pointer}={record["id"]}&_limit=1000') if _value(row, grown_pointer) == record['id']]
                for one in rows:
                    made.append((later, one['id']))
                total = sum(_quantity(one, grown['quantityInto']) for one in rows) if grown.get('quantityInto') else 0
                report.add(f"{title(previous)} → {title(later)}: 등록하면 {title(grown['from'])} 기준으로 {expected['_count']}건이 저절로 생기고 수량은 {expected[later]:g} (줄 수량 × {QUANTITY})",
                           len(rows) == expected['_count'] and abs(total - expected[later]) < 1e-9, f'생긴 것 {len(rows)}건, 수량 {total:g}')
                if not rows:
                    return report
                current, previous = rows, later
                continue
            if not report.add(f"{title(later)} 이(가) {title(previous)} 을(를) 가리켜 이어진다", limit is not None,
                              '한도(limits)가 없어 어느 건에서 왔는지 알 수 없습니다' + (' (기준 정보로 저절로 만드는 길은 흐름의 첫 단계에서만 판정한다)' if grown else '')):
                return report
            want = expected.get(previous, QUANTITY)
            ids = [one['id'] for one in current]

            def mine():
                rows = []
                for record_id in ids:
                    rows += [row for row in framework.ok('GET', f'/api/data/{later}?{pointer}={record_id}&_limit=1000') if _value(row, pointer) == record_id]
                return rows
            take = takes.get((previous, later))
            if take and checks.take_of(known[take], take).get('statuses'):        # the earlier records first stand where the take-over screen lists them
                current = [_bring(framework, previous, known[previous], framework.ok('GET', f"/api/data/{previous}/{one['id']}"), checks.take_of(known[take], take)['statuses']) for one in current]
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
                part = known[later].get('ledger')
                if part and part['direction'] in ('out', 'move'):
                    for row in open_rows:
                        spot = checks.taken_place(row, checks.take_of(known[take], take), limit, part['place'], values)
                        item = (row.get('unit') or {}).get(dict(zip(limit['by'], limit['entityBy'])).get(part['thing'], part['thing'])) or row['head'].get(dict(zip(limit['by'], limit['entityBy'])).get(part['thing'], part['thing']))
                        if item and spot and held(framework, item, spot) < row['remaining']:
                            framework.ok('POST', '/api/system/ledger/adjust', {'thingEntity': part['thingEntity'], 'thingId': item, 'placeEntity': part['placeEntity'], 'placeId': spot, 'quantity': row['remaining'], 'unitCost': 100})
                code, answer = framework.call('POST', f'/api/take/{take}', {'values': values, 'rows': rows})
                if not report.add(f"{title(previous)} → {title(later)}: 이어받기 화면({known[take]['title']})으로 넘긴다", code == 200 and rows, f'{code} {answer}' if code != 200 else f'넘길 줄 {len(rows)}개'):
                    return report
                existing, route = mine(), '이어받기'
            if not report.add(f"{title(previous)} → {title(later)}: 넘어가는 길이 있다", bool(existing), '자동 처리도 이어받기 화면도 없습니다 - 흐름이 여기서 끊깁니다'):
                return report
            for one in existing:
                made.append((later, one['id']))
            if not limit.get('field'):         # followed once: each earlier record goes on as exactly one
                expected[later] = len(current)
                report.add(f"{title(later)}: {title(previous)} 한 건에 한 건씩 이어진다 ({route})", len(existing) == len(current), f'{title(previous)} {len(current)}건 → {title(later)} {len(existing)}건')
            else:
                total = sum(_quantity(one, limit['field']) for one in existing)
                expected[later] = want
                report.add(f"{title(later)}: {title(previous)} 의 수량({want:g})이 그대로 넘어온다 ({route})", abs(total - want) < 1e-9, f'넘어온 수량 {total:g}')
            if take:          # nothing left behind, and no second way: the take-over list shows nothing more for these records
                still = [row for row in framework.ok('GET', f'/api/take/{take}') if row['sourceId'] in ids]
                report.add(f"{title(previous)} → {title(later)}: 넘긴 뒤 이어받기 목록에 남은 것이 없다" + (' (자동으로 만들어졌는데 손으로 또 넘길 길이 열려 있으면 두 번 처리됩니다)' if route == '자동 처리' else ''),
                           not still, f"남은 줄 {[(row['sourceId'], row['remaining']) for row in still]}")
            part = known[later].get('ledger')
            if part:
                sign = {'in': 1, 'out': -1}.get(part['direction'])
                full = [framework.ok('GET', f"/api/data/{later}/{one['id']}") for one in existing]
                net = sum(float(move['quantity']) * (1 if move['direction'] == 'IN' else -1) for one in full for move in one.get('_ledger') or [])
                if sign:
                    moved[later] = net
                    report.add(f"{title(later)}: 수량이 한 번만 {'늘어난다' if sign > 0 else '줄어든다'} ({want:g})", abs(net - sign * want) < 1e-9, f'움직인 수량 {net:g}')
                elif part['direction'] == 'move':
                    report.add(f"{title(later)}: 위치 이동은 수량 합계를 바꾸지 않는다", abs(net) < 1e-9, f'움직인 수량 합 {net:g}')
            current, previous = walk(later, existing), later
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
        # the root instruction finished early (closed, cancelled ...): nothing that came of it goes on further down the flow
        root_status = root.get('status') or {}
        takes_in = {(checks.take_of(one, key)['from'], checks.take_of(one, key)['entity']): key for key, one in known.items() if checks.take_of(one, key)}
        for ending in [one for one in root_status.get('actions', []) if len(stages) > 1 and one['to'] in (root_status.get('closed') or []) and root_status.get('initial') in one['from']]:
            code, again = framework.call('POST', f'/api/data/{stages[0]}', dict(body))
            if code != 201:
                report.add(f"{title(stages[0])} 을(를) {ending['label']} 해 보려고 한 건 더 등록한다", False, f'{code} {again}')
                continue
            made.append((stages[0], again['id']))
            limit2, pointer2 = _link(known, stages[0], stages[1])
            grown2, grown_pointer2 = _expansion(known, stages[0], stages[1])
            pointer2 = pointer2 or grown_pointer2
            children = [row['id'] for row in framework.ok('GET', f'/api/data/{stages[1]}?{pointer2}={again["id"]}&_limit=1000') if _value(row, pointer2) == again['id']] if pointer2 else []
            for child in children:
                made.append((stages[1], child))
            code, answer = framework.call('POST', f"/api/data/{stages[0]}/{again['id']}/actions/{ending['name']}")
            if not report.add(f"{title(stages[0])}: {ending['label']} 할 수 있다", code == 200, f'{code} {answer}'):
                continue
            left = []
            for (source, target), take in takes_in.items():
                if source == stages[0] and target in stages:
                    left += [f"{known[take]['title']}: {title(stages[0])} {row['sourceId']}" for row in framework.ok('GET', f'/api/take/{take}') if row.get('sourceId') == again['id']]
                if source == stages[1] and target in stages and children:
                    left += [f"{known[take]['title']}: {title(stages[1])} {row['sourceId']}" for row in framework.ok('GET', f'/api/take/{take}') if row.get('sourceId') in children]
            report.add(f"{title(stages[0])} 을(를) {ending['label']} 하면 그 뒤 단계로 더 이어지지 않는다 (이어받기 목록에서 빠진다)", not left,
                       '아직 넘길 수 있게 남은 것: ' + ', '.join(left[:5]))
    except Exception as problem:
        report.add('흐름을 끝까지 돌린다', False, str(problem)[:300])
    finally:
        # what the run's records made by themselves on the way (the requirements a set-up work order expanded into) goes too:
        # every record this account made after the start, in any screen, oldest first so the newest are removed first
        who = next((one.get('createdBy') for key, record in made[:1] for one in [framework.ok('GET', f'/api/data/{key}/{record}')]), None)
        if who:
            known_rows = set(made)
            extra = sorted((row['id'], key) for key in stored for row in framework.ok('GET', f'/api/data/{key}?_sort=id&_desc=true&_limit=200')
                           if row['id'] > start and row.get('createdBy') == who and (key, row['id']) not in known_rows)
            made = sorted(made + [(key, record) for record, key in extra], key=lambda pair: pair[1])
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
