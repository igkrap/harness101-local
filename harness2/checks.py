"""Checks derived from a definition. Nobody writes scenarios: each thing a definition can say brings its own.

  entity            create -> appears in the list -> update -> delete -> gone
  required field    a blank value is refused
  optional fields   may all be left out
  number/date/code  a wrong kind of value is refused
  ref field         a missing target is refused; a target that is in use cannot be deleted, and can once it is free
  search field      filters the list
  screen            workspace, query panel, grid, editor, toolbar; every field is in the editor; required ones are marked and in the grid
  parts             numbering, lines (count limits), computed values and totals, number ranges, uniqueness, status start, each action and its refusal, locked statuses
  blocking rule     refused (with its message) while a row points here; allowed again once that row is gone

Everything runs against a trial copy of the definition (a draft the menus never show), and every row a
check creates is removed again, also when a check fails.
"""
import itertools
import json
import subprocess
import sys
import uuid
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[1] / 'erp-harness'


_serial = itertools.count(1)


def _number(field, wanted):
    """A number of the wanted size, moved inside the field's allowed range."""
    low, high = field.get('min'), field.get('max')
    if low is not None and wanted < low:
        wanted = low
    if high is not None and wanted > high:
        wanted = high
    return int(wanted) if float(wanted).is_integer() else wanted


def sample(field, framework, made):
    """A value of the right kind for this field; for a ref, a freshly made row of the target (remembered in made)."""
    kind = field.get('type', 'text')
    if kind == 'number':
        return _number(field, 10 + (next(_serial) if field.get('unique') else 0))
    if kind == 'date':
        return '2026-01-15'
    if kind == 'code':
        codes = framework.codes(field['codeGroup'])
        return codes[0]['code'] if codes else None
    if kind == 'ref':
        target = field['ref']['entity']
        definition = next(item['definition'] for item in framework.definitions() if item['key'] == target)
        body = {item['name']: sample(item, framework, made) for item in definition['fields'] if item.get('required') and not _computed(item)}
        if definition.get('lines') and definition['lines'].get('min', 1) > 0:      # it cannot exist without a line
            body['lines'] = [_line(definition['lines']['fields'], framework, made, 1)]
        row = framework.ok('POST', f'/api/data/{target}', fit(body, definition, framework, made))
        made.append((target, row['id']))
        return row['id']
    return f"{field['label']} 시험" + (str(next(_serial)) if field.get('unique') else '')


def _shift(value, by):
    """A date or a number moved by some days / units."""
    if isinstance(value, str):
        import datetime
        return (datetime.date.fromisoformat(value) + datetime.timedelta(days=by)).isoformat()
    return value + by


def _units(body, in_lines):
    return (body.get('lines') or []) if in_lines else [body]


def fit(body, definition, framework, made, break_check=None):
    """Make a sample body obey the definition's own checks and limits (a sample of plain values would not: every date is
    the same day, and a limit allows nothing until the other entity holds a matching row). break_check: the one check to violate."""
    import datetime
    today = datetime.date.today().isoformat()
    for check in definition.get('checks') or []:
        for unit in _units(body, check.get('lines')):
            right = today if check['right'] == 'today' else unit.get(check['right'])
            if right is None:
                right = unit[check['right']] = '2026-01-15' if isinstance(unit.get(check['left']), str) or unit.get(check['left']) is None else 10
            keep = {'>': 1, '>=': 0, '<': -1, '<=': 0, '==': 0, '!=': 1}[check['op']]
            wrong = {'>': 0, '>=': -1, '<': 0, '<=': 1, '==': 1, '!=': 0}[check['op']]
            unit[check['left']] = _shift(right, wrong if check is break_check else keep)
    line_names = {field['name'] for field in (definition.get('lines') or {}).get('fields', [])}
    for limit in definition.get('limits') or []:
        other = next(item['definition'] for item in framework.definitions() if item['key'] == limit['entity'])
        pairs = list(zip(limit['by'], limit['entityBy']))
        if limit.get('lines'):
            if not body.get('lines'):
                continue
            body['lines'] = body['lines'][:1]         # one line, so the whole allowance can go to it
        unit = body['lines'][0] if limit.get('lines') else body
        via = next((mine for mine, theirs in pairs if theirs == 'id'), None)
        holder = lambda name: unit if limit.get('lines') and name in line_names else body
        if via and holder(via).get(via):
            row = framework.ok('GET', f"/api/data/{limit['entity']}/{holder(via)[via]}")
        else:                                           # nothing points at the other entity: make the row that gives the allowance
            given = {item['name']: sample(item, framework, made) for item in other['fields'] if item.get('required') and not _computed(item)}
            if other.get('lines') and (other['lines'].get('min', 1) > 0 or limit.get('entityLines')):
                given['lines'] = [_line(other['lines']['fields'], framework, made, 1)]
            row = framework.ok('POST', f"/api/data/{limit['entity']}", fit(given, other, framework, made))
            made.append((limit['entity'], row['id']))
        theirs_unit = (row.get('lines') or [{}])[0] if limit.get('entityLines') else row
        value_of = lambda name: row['id'] if name == 'id' else theirs_unit.get(name) if name in theirs_unit else row.get(name)
        for mine, theirs in pairs:
            holder(mine)[mine] = value_of(theirs)
        unit[limit['field']] = value_of(limit['entityField']) or 0
    return body


def _computed(field):
    return bool(field.get('formula') or field.get('sum') or field.get('type') == 'serial')


LEFTOVER = []


def sweep(framework, made):
    """Delete the sample rows, newest first. Returns the ones that could not be deleted yet (a row a locked
    trial document still points at goes once the trial definition is removed)."""
    left = []
    for entity, record in reversed(made):
        code, _ = framework.call('DELETE', f'/api/data/{entity}/{record}')
        if code == 409:      # locked, or held by a rule: the checks' own rows may be removed all the same (what others point at still may not)
            code, _ = framework.call('DELETE', f'/api/data/{entity}/{record}?force=true')
        if code not in (204, 404):
            left.append((entity, record))
    left.reverse()
    LEFTOVER.extend(left)      # the run sweeps these once more after the trial definition is gone
    return left


class Report:
    def __init__(self):
        self.results = []
        self.leftover = []

    def add(self, description, passed, detail=''):
        self.results.append({'description': description, 'passed': bool(passed), 'detail': '' if passed else str(detail)[:400]})
        return bool(passed)

    @property
    def passed(self):
        return all(result['passed'] for result in self.results)


def _calc(formula, values):
    """The framework's formula language, evaluated here independently (only numbers, names, + - * / and parentheses)."""
    import re
    if not re.fullmatch(r'[A-Za-z0-9+\-*/(). ]+', formula):
        raise ValueError('formula: ' + formula)
    return eval(formula, {'__builtins__': {}}, dict(values))   # noqa: S307 - characters are restricted above


def _line(fields, framework, made, quantity):
    """One line with sample values; number fields get distinct, easy numbers so sums and products are telling."""
    body, number = {}, quantity
    for field in fields:
        if field.get('formula'):
            continue
        if field.get('type') == 'number':
            body[field['name']] = _number(field, number)
            number = number * 100 + 50     # e.g. quantity 3 -> price 350
        else:
            body[field['name']] = sample(field, framework, made)
    return body


def record_checks(key, definition, framework):
    """Every data rule the definition states, tried against /api/data/<key>. A screen is its parts, and so are its
    checks: fields always; numbering, lines, computed values, ranges, uniqueness, status only where the definition has them."""
    report, made, api = Report(), [], f'/api/data/{key}'
    fields, lines, status = definition['fields'], definition.get('lines'), definition.get('status')
    line_fields = lines['fields'] if lines else []
    low, high = (lines.get('min', 1), lines.get('max')) if lines else (0, None)
    plain = [field for field in fields if not _computed(field)]
    usual = 0 if not lines else max(low, 1) if high == 1 else max(low, 2) if high is None else min(max(low, 2), high)

    def new_body(count=None):
        body = {field['name']: sample(field, framework, made) for field in plain}
        if lines:
            body['lines'] = [_line(line_fields, framework, made, 3 - index % 2) for index in range(usual if count is None else count)]
        return fit(body, definition, framework, made) if count is None else body      # the line-count tests keep their count

    def post(body):
        code, answer = framework.call('POST', api, body)
        if code == 201:
            made.append((key, answer['id']))
        return code, answer

    def refused(description, body, expected=400):
        code, answer = post(body)
        report.add(description, code == expected, f'{code} {answer}')
    try:
        body = new_body()
        sent = json.loads(json.dumps(body))
        for line in sent.get('lines', []):                 # values the server must ignore and work out itself
            for field in line_fields:
                if field.get('formula'):
                    line[field['name']] = 1
        code, row = post(sent)
        if not report.add('등록: 항목' + ('과 줄 표' if lines else '') + '를 채워 저장된다', code == 201, f'{code} {row}'):
            return report
        wrong = [field['label'] for field in plain if body[field['name']] is not None and row.get(field['name']) != body[field['name']]]
        report.add('저장 확인: 보낸 값이 항목마다 그대로 돌아온다', not wrong, f'다르게 저장된 항목: {wrong}')
        for field in [item for item in line_fields if item.get('formula')]:
            expected = [_calc(field['formula'], line) for line in body['lines']]
            got = [line.get(field['name']) for line in row.get('lines', [])]
            report.add(f"계산: 줄의 {field['label']} = {field['formula']} (보낸 값은 무시된다)", got == expected, f'기대 {expected}, 실제 {got}')
        for field in [item for item in fields if item.get('sum')]:
            expected = sum(line.get(field['sum']) or 0 for line in row.get('lines', []))
            report.add(f"합계: {field['label']} 은(는) 줄의 {field['sum']} 을(를) 더한 값이다", row.get(field['name']) == expected, f"기대 {expected}, 실제 {row.get(field['name'])}")
        for field in [item for item in fields if item.get('formula')]:
            expected = _calc(field['formula'], {name: value for name, value in row.items() if isinstance(value, (int, float))})
            report.add(f"계산: {field['label']} = {field['formula']}", row.get(field['name']) == expected, f"기대 {expected}, 실제 {row.get(field['name'])}")
        for field in [item for item in fields if item.get('type') == 'serial']:
            code2, second = post(new_body())
            first, following = str(row.get(field['name'])), str(second.get(field['name'])) if code2 == 201 else ''
            report.add(f"채번: {field['label']} 이(가) {field['prefix']}- 로 시작하고 건마다 다르게 이어진다",
                       first.startswith(field['prefix'] + '-') and following.startswith(field['prefix'] + '-') and following > first, f'{first}, {following}')
        code, rows = framework.call('GET', api)
        report.add('조회: 목록에 방금 등록한 자료가 있다', code == 200 and any(item['id'] == row['id'] for item in rows), f'{code}')
        for field in [item for item in plain if item.get('search') and item.get('type', 'text') == 'text']:
            _, hit = framework.call('GET', f"{api}?{field['name']}={body[field['name']]}")
            _, miss = framework.call('GET', f"{api}?{field['name']}=없는값zzqq")
            report.add(f"조회 조건 {field['label']}: 맞는 값은 찾고 없는 값은 못 찾는다", any(item['id'] == row['id'] for item in hit or []) and not miss, f'hit={len(hit or [])} miss={len(miss or [])}')
        for field in [item for item in plain if item['required']]:
            refused(f"필수 항목 {field['label']}: 비우면 거절된다", dict(new_body(), **{field['name']: '' if field.get('type', 'text') == 'text' else None}))
        if usual:
            for field in [item for item in line_fields if item['required']]:
                broken = new_body()
                broken['lines'][0][field['name']] = None
                refused(f"줄의 필수 항목 {field['label']}: 비우면 거절된다", broken)
        minimal = {field['name']: value for field, value in ((field, sample(field, framework, made)) for field in plain if field['required'])}
        if lines and low > 0:
            minimal['lines'] = [{field['name']: value for field, value in ((field, _line([field], framework, made, 2)[field['name']]) for field in line_fields if field['required'])} for _ in range(low)]
        code, answer = post(fit(minimal, definition, framework, made))
        report.add('선택 항목은 모두 비워도 저장된다', code == 201, f'{code} {answer}')
        wrong_values = {'number': '열 개', 'date': '1월 15일', 'code': '없는코드zz', 'ref': 999999999}
        for field in [item for item in plain if item.get('type', 'text') in wrong_values]:
            refused(f"{field['label']}: 맞지 않는 값({wrong_values[field['type']]})은 거절된다", dict(new_body(), **{field['name']: wrong_values[field['type']]}))
        for where, group in (('', plain), ('줄의 ', [item for item in line_fields if not _computed(item)] if usual else [])):
            for field in group:
                for edge, value, word in (('min', None if field.get('min') is None else field['min'] - 1, '보다 작은'), ('max', None if field.get('max') is None else field['max'] + 1, '보다 큰')):
                    if value is None:
                        continue
                    broken = new_body()
                    (broken['lines'][0] if where else broken)[field['name']] = value
                    refused(f"{where}{field['label']}: {field[edge]:g} {word} 값({value:g})은 거절된다", broken)
        for check in definition.get('checks') or []:
            broken = fit(new_body(), definition, framework, made, break_check=check)
            code, answer = post(broken)
            report.add(f"비교 규칙: {check['left']} {check['op']} {check['right']} 을(를) 어기면 거절되고 안내가 나온다 ({check['message']})", code == 400 and (answer or {}).get('detail') == check['message'], f'{code} {answer}')
        for limit in definition.get('limits') or []:
            over = new_body()
            unit = over['lines'][0] if limit.get('lines') else over
            allowed = unit[limit['field']]
            unit[limit['field']] = allowed + 1
            code, answer = post(over)
            report.add(f"한도: {limit['field']} 이(가) {limit['entity']} 의 {limit['entityField']}({allowed:g}) 을(를) 넘으면 거절된다 ({limit['message']})",
                       code == 400 and str((answer or {}).get('detail', '')).startswith(limit['message']), f'{code} {answer}')
            within = new_body()
            code, answer = post(within)
            report.add(f"한도: 꼭 그만큼({(within['lines'][0] if limit.get('lines') else within)[limit['field']]:g})은 저장된다", code == 201, f'{code} {answer}')
        for field in [item for item in plain if item.get('unique')]:
            refused(f"{field['label']}: 이미 있는 값은 거절된다", dict(new_body(), **{field['name']: row[field['name']]}))
        if lines:
            if low > 0:
                refused(f"줄 표: {low}줄보다 적으면 거절된다", new_body(low - 1))
            else:
                code, answer = post(new_body(0))
                report.add('줄 표: 한 줄도 없이 저장할 수 있다', code == 201, f'{code} {answer}')
            if high is not None:
                refused(f"줄 표: {high}줄보다 많으면 거절된다", new_body(high + 1))
        changed = new_body()
        code, updated = framework.call('PUT', f"{api}/{row['id']}", changed)
        same_number = all(updated.get(field['name']) == row.get(field['name']) for field in fields if field.get('type') == 'serial') if code == 200 else False
        kept = [field['label'] for field in plain if field.get('type', 'text') in ('text', 'number', 'date') and code == 200 and updated.get(field['name']) != changed[field['name']]]
        report.add('수정: 고쳐 저장하면 고친 값이 남는다' + (' (번호는 그대로)' if any(f.get('type') == 'serial' for f in fields) else ''), code == 200 and same_number and not kept, f'{code} {kept or updated}')
        if status:
            names = {value['code']: value['label'] for value in status['values']}
            report.add(f"상태: 새 자료는 {names.get(status['initial'], status['initial'])} 상태로 시작한다", row.get('status') == status['initial'], f"{row.get('status')}")
            for action in status['actions']:
                if status['initial'] not in action['from']:
                    continue                          # reached only through another action; that chain is not walked here
                _, fresh = post(new_body())
                code, after = framework.call('POST', f"{api}/{fresh['id']}/actions/{action['name']}")
                report.add(f"동작 {action['label']}: {names.get(status['initial'])} 상태에서 되고 {names.get(action['to'], action['to'])} 상태가 된다", code == 200 and after.get('status') == action['to'], f'{code} {after}')
                if action['to'] not in action['from']:
                    code, again = framework.call('POST', f"{api}/{fresh['id']}/actions/{action['name']}")
                    report.add(f"동작 {action['label']}: 이미 {names.get(action['to'], action['to'])} 상태면 거절된다", code == 409, f'{code} {again}')
                if action['to'] in status.get('locked', []):
                    code, answer = framework.call('PUT', f"{api}/{fresh['id']}", new_body())
                    report.add(f"{names.get(action['to'], action['to'])} 상태의 자료는 수정이 거절된다", code == 409, f'{code} {answer}')
        for field in [item for item in plain if item.get('type') == 'ref']:
            code, answer = framework.call('DELETE', f"/api/data/{field['ref']['entity']}/{changed[field['name']]}")
            report.add(f"{field['label']}: 쓰이고 있는 대상 자료는 삭제가 거절된다", code == 409, f'{code} {answer}')
        if not (status and status['initial'] in status.get('locked', [])):
            code, _ = framework.call('DELETE', f"{api}/{row['id']}")
            report.add('삭제: 자료를 지울 수 있다', code == 204, f'{code}')
            code, _ = framework.call('PUT', f"{api}/{row['id']}", changed)
            report.add('지운 자료는 더 수정할 수 없다', code == 404, f'{code}')
    finally:
        report.leftover = sweep(framework, made)
    return report


def _summary(part, source, rows):
    """A summary's numbers worked out here, independently of the framework, from the source rows as the data API gives them."""
    line_names = {field['name'] for field in (source.get('lines') or {}).get('fields', [])} if part.get('lines') else set()
    dates = {field['name'] for field in source['fields'] + (source.get('lines') or {}).get('fields', []) if field.get('type') == 'date'}
    groups, everything = {}, [[] for _ in part['values']]
    counts, total_units = {}, 0
    for row in rows:
        for unit in (row.get('lines') or []) if part.get('lines') else [row]:
            keys = []
            for group in part['groupBy']:
                if group['field'] == 'id':
                    keys.append(str(row['id']))
                    continue
                value = row.get('status') if group['field'] == 'status' and group['field'] not in line_names and not any(f['name'] == 'status' for f in source['fields']) \
                    else (unit if group['field'] in line_names else row).get(group['field'])
                text = '' if value is None else str(value)
                if group['field'] in dates and text:
                    text = text[:4] if group.get('by') == 'year' else text[:7] if (group.get('by') or 'month') == 'month' else text
                keys.append(text)
            key = tuple(keys)
            numbers = groups.setdefault(key, [[] for _ in part['values']])
            counts[key] = counts.get(key, 0) + 1
            total_units += 1
            for index, value in enumerate(part['values']):
                if value.get('between'):
                    import datetime
                    start, end = row.get(value['between'][0]), row.get(value['between'][1])
                    number = (datetime.date.fromisoformat(end) - datetime.date.fromisoformat(start)).days if start and end else None
                    if number is not None:
                        numbers[index].append(number)
                        everything[index].append(number)
                elif value.get('field'):
                    number = (unit if value['field'] in line_names else row).get(value['field'])
                    if isinstance(number, (int, float)):
                        numbers[index].append(number)
                        everything[index].append(number)

    def result(op, numbers, units):
        if op == 'count':
            return units
        if op == 'sum':
            return sum(numbers)          # nothing to add up is 0, not "no value"
        if not numbers:
            return None
        return {'sum': sum(numbers), 'avg': sum(numbers) / len(numbers), 'min': min(numbers), 'max': max(numbers)}[op]
    table = {key: [result(value['op'], numbers[index], counts[key]) for index, value in enumerate(part['values'])] for key, numbers in groups.items()}
    totals = [result(value['op'], everything[index], total_units) for index, value in enumerate(part['values'])]
    return table, totals


def _same(expected, got):
    return (expected is None and got is None) or (expected is not None and got is not None and abs(expected - got) < 0.001)


def summary_checks(key, definition, framework):
    """A summary screen: its groups, computed values, total line and conditions against the same numbers worked out here."""
    report, made, part = Report(), [], definition['summary']
    source = next(item['definition'] for item in framework.definitions() if item['key'] == part['entity'])
    try:
        # Two rows of the source made for the occasion, so there is something to gather even in an empty system.
        for _ in range(2):
            body = {field['name']: sample(field, framework, made) for field in source['fields'] if not _computed(field)}
            if source.get('lines'):
                body['lines'] = [_line(source['lines']['fields'], framework, made, 3), _line(source['lines']['fields'], framework, made, 2)][:source['lines'].get('max') or 2]
            row = framework.ok('POST', f"/api/data/{part['entity']}", fit(body, source, framework, made))
            made.append((part['entity'], row['id']))
        rows = framework.ok('GET', f"/api/data/{part['entity']}")

        plan = (part.get('compare') or {}).get('type') in ('plan', 'minus') and part['compare']
        minus = bool(plan) and plan['type'] == 'minus'
        planned = {}
        if plan:      # one plan row made for the occasion, then every plan row added up by the matching fields
            target = next(item['definition'] for item in framework.definitions() if item['key'] == plan['entity'])
            body = {field['name']: sample(field, framework, made) for field in target['fields'] if not _computed(field)}
            if target.get('lines'):
                body['lines'] = [_line(target['lines']['fields'], framework, made, 2)]
            made.append((plan['entity'], framework.ok('POST', f"/api/data/{plan['entity']}", fit(body, target, framework, made))['id']))
            for item in framework.ok('GET', f"/api/data/{plan['entity']}"):
                for unit in (item.get('lines') or []) if plan.get('lines') else [item]:
                    keys = []
                    for group, mine in zip(part['groupBy'], plan['groupBy']):
                        value = unit.get(mine) if plan.get('lines') and mine in unit else item.get(mine)
                        text = '' if value is None else str(value)
                        keys.append(text[:4] if group.get('by') == 'year' else text[:7] if group.get('by') == 'month' else text)
                    number = unit.get(plan['field']) if plan.get('lines') and plan['field'] in unit else item.get(plan['field'])
                    if isinstance(number, (int, float)):
                        planned[tuple(keys)] = planned.get(tuple(keys), 0) + number

        rows = framework.ok('GET', f"/api/data/{part['entity']}")      # read again: making the other side's sample may have made source rows too

        def earlier(key, by):
            if len(key) == 4:
                return str(int(key) - 1)
            year, month = int(key[:4]), int(key[5:7])
            return f'{year - 1}-{month:02d}' if by == 'year' else (f'{year - 1}-12' if month == 1 else f'{year}-{month - 1:02d}')

        def analysis(answer, table):
            """The comparison, share and ranking columns of the unfiltered answer."""
            mark, labels = part.get('compare'), [value['label'] for value in part['values']]
            of = labels.index(mark['value']) if mark and mark.get('value') in labels else 0
            groups = len(part['groupBy'])
            listed = {tuple(item.get(f'g{index}Key', '') for index in range(groups)): item for item in answer['rows']}
            actual = lambda key: (table[key][of] if key in table else 0) or 0
            if mark:
                wrong = []
                for key, item in listed.items():
                    base = planned.get(key, 0) if minus else planned.get(key) if plan else ((table[(earlier(key[0], mark['by']),) + key[1:]][of]) if (earlier(key[0], mark['by']),) + key[1:] in table else None)
                    rate = (None if actual(key) == 0 else base / actual(key) * 100) if minus and base is not None else None if not base else (actual(key) / base * 100 if plan else (actual(key) - base) / base * 100)
                    expected = (None, None, None) if base is None else (base, actual(key) - base, rate)
                    got = (item.get('c0'), item.get('c1'), item.get('c2'))
                    if not all((e is None and g is None) or (e is not None and g is not None and abs(e - g) < 0.02) for e, g in zip(expected, got)):
                        wrong.append((key, expected, got))
                kind = f"{mark.get('label')}·{mark.get('balance')}·진행률" if minus else '계획·차이·달성률' if plan else f"{mark.get('label') or '이전'}·증감·증감률"
                report.add(f'분석 틀: {kind} 이(가) 줄마다 맞다', not wrong, f'(묶음, 기대, 실제) {wrong[:4]}')
            if part.get('cumulative') and not part.get('top'):
                running, wrong = 0, []
                for item in answer['rows']:
                    running += item.get('v0') or 0
                    if abs((item.get('r0') or 0) - running) > 0.02:
                        wrong.append((item.get('g0'), running, item.get('r0')))
                report.add('분석 틀: 누계가 위에서부터 더한 값과 같다', not wrong, f'{wrong[:4]}')
            if part.get('share'):
                whole = sum(actual(key) for key in set(table) | set(planned))
                wrong = [(key, item.get('s0')) for key, item in listed.items() if whole and abs((item.get('s0') or 0) - actual(key) / whole * 100) > 0.02]
                report.add('분석 틀: 구성비가 줄마다 맞다 (전체 대비 %)', not wrong, f'{wrong[:4]}')
            if part.get('top'):
                order = [item.get('v0') or 0 for item in answer['rows']]
                best = sorted(((table[key][0] or 0) for key in table), reverse=True)[:part['top']]
                report.add(f"분석 틀: 큰 순서로 {part['top']}개까지만 나온다", len(order) <= part['top'] and order == sorted(order, reverse=True) and all(abs(a - b) < 0.001 for a, b in zip(order, best)), f'실제 {order}, 기대 {best}')

        def compare(label, query, chosen):
            code, answer = framework.call('GET', f'/api/summary/{key}' + query)
            if not report.add(f'{label}: 조회된다', code == 200, f'{code} {answer}'):
                return
            table, totals = _summary(part, source, chosen)
            groups = len(part['groupBy'])
            got = {tuple(item.get(f'g{index}Key', '') for index in range(groups)): [item.get(f'v{index}') for index in range(len(part['values']))] for item in answer['rows']}
            if not query:
                analysis(answer, table)
            if part.get('top') or (plan and query):
                # A ranking shows only its largest groups, and a plan under a condition is judged above: here, what is listed must be right.
                report.add(f'{label}: 나온 묶음이 모두 실제 자료에 있다', all(group in table or group in planned for group in got), f'{sorted(set(got) - set(table) - set(planned))}')
            else:
                wanted = set(table) | (set(planned) if plan and not minus else set())
                report.add(f'{label}: 묶음이 같다 ({len(wanted)}개)', set(got) == wanted, f'기대 {sorted(wanted)}, 실제 {sorted(got)}')
            for index, value in enumerate(part['values']):
                wrong = [(group, table[group][index], got[group][index]) for group in table if group in got and not _same(table[group][index], got[group][index])]
                report.add(f"{label}: {value['label']}({value['op']}) 값이 묶음마다 맞다", not wrong, f'(묶음, 기대, 실제) {wrong[:5]}')
                report.add(f"{label}: {value['label']} 의 합계 줄이 맞다", _same(totals[index], answer['totals'].get(f'v{index}')), f"기대 {totals[index]}, 실제 {answer['totals'].get(f'v{index}')}")
            if not query:
                names = [column['label'] for column in answer['columns']]
                wanted = [group['label'] for group in part['groupBy']] + [value['label'] for value in part['values']]
                report.add('열 이름이 정의와 같다', names[:len(wanted)] == wanted, f'{names}')
        compare('전체', '', rows)
        fields = {field['name']: field for field in source['fields']}
        for name in part.get('filters', []):
            if name == 'status':
                code = (source.get('status') or {}).get('initial')
                if code:
                    compare('조회 조건 상태', f'?status={code}', [row for row in rows if row.get('status') == code])
            elif fields.get(name, {}).get('type') == 'date':
                compare(f"조회 조건 {fields[name]['label']} 기간(지난 날짜만)", f'?{name}_to=2000-01-01', [row for row in rows if (row.get(name) or '9') <= '2000-01-01'])
                compare(f"조회 조건 {fields[name]['label']} 기간(전체)", f'?{name}_from=2000-01-01', [row for row in rows if (row.get(name) or '') >= '2000-01-01'])
            elif name in fields and fields[name].get('type') in ('ref', 'code'):
                value = rows[-1].get(name)
                if value is not None:
                    compare(f"조회 조건 {fields[name]['label']}", f'?{name}={value}', [row for row in rows if row.get(name) == value])
    finally:
        report.leftover = sweep(framework, made)
    return report


def over_checks(key, definition, framework):
    """A work screen: it lists only its statuses, takes only its actions, changes nothing else - tried on records made in the entity it is over."""
    report, made, part = Report(), [], definition['over']
    base = next(item['definition'] for item in framework.definitions() if item['key'] == part['entity'])
    status, api, own = base.get('status') or {}, f'/api/over/{key}', f"/api/data/{part['entity']}"
    names = {value['code']: value['label'] for value in status.get('values', [])}

    def fresh():
        body = {field['name']: sample(field, framework, made) for field in base['fields'] if not _computed(field)}
        if base.get('lines') and base['lines'].get('min', 1) > 0:
            body['lines'] = [_line(base['lines']['fields'], framework, made, 2)]
        row = framework.ok('POST', own, fit(body, base, framework, made))
        made.append((part['entity'], row['id']))
        return row
    try:
        row = fresh()
        code, rows = framework.call('GET', api)
        if not report.add('목록이 조회된다', code == 200, f'{code} {rows}'):
            return report
        if part.get('statuses'):
            shown = ', '.join(names.get(item, item) for item in part['statuses'])
            report.add(f'정한 상태({shown})의 건만 보인다', all(item.get('status') in part['statuses'] for item in rows), f"{sorted({item.get('status') for item in rows})}")
            inside = row.get('status') in part['statuses']
            report.add(f"방금 등록한 건({names.get(row.get('status'), row.get('status'))} 상태)이 목록에 {'있다' if inside else '없다'}", any(item['id'] == row['id'] for item in rows) == inside, '')
        code, answer = framework.call('POST', api, {})
        report.add('이 화면에서는 새로 등록할 수 없다', code in (403, 404, 405), f'{code} {answer}')
        code, answer = framework.call('DELETE', f"{api}/{row['id']}")
        report.add('이 화면에서는 지울 수 없다', code in (403, 404, 405), f'{code} {answer}')
        visible = not part.get('statuses') or row.get('status') in part['statuses']
        if visible:
            again = {name: value for name, value in row.items() if name not in ('id', 'status', 'statusLabel', 'createdBy', 'createdAt', 'updatedBy', 'updatedAt')}
            code, answer = framework.call('PUT', f"{api}/{row['id']}", again)
            report.add('내용을 고칠 수 있다' if part.get('edit') else '내용은 고칠 수 없다', code == (200 if part.get('edit') else 403), f'{code} {answer}')
        for action in status.get('actions', []):
            listed = action['name'] in part.get('actions', [])
            if row.get('status') not in action['from'] or not visible:
                continue
            target = fresh()
            if listed:
                code, after = framework.call('POST', f"{api}/{target['id']}/actions/{action['name']}")
                report.add(f"동작 {action['label']}: 이 화면에서 되고 {names.get(action['to'], action['to'])} 상태가 된다", code == 200 and after.get('status') == action['to'], f'{code} {after}')
                if part.get('statuses') and action['to'] not in part['statuses']:
                    code, _ = framework.call('GET', f"{api}/{target['id']}")
                    report.add(f"동작 {action['label']} 뒤에는 그 건이 이 화면에서 빠진다", code == 404, f'{code}')
            else:
                code, answer = framework.call('POST', f"{api}/{target['id']}/actions/{action['name']}")
                report.add(f"동작 {action['label']}: 이 화면의 동작이 아니라서 거절된다", code == 404, f'{code} {answer}')
            if action.get('separate'):
                other = fresh()
                code, answer = framework.call('POST', f"{own}/{other['id']}/actions/{action['name']}")
                report.add(f"동작 {action['label']}: 등록 화면에서는 거절된다 (이 화면에서만 한다)", code == 403, f'{code} {answer}')
    finally:
        report.leftover = sweep(framework, made)
    return report


def over_screen_criteria(definition):
    toolbar = '[role="toolbar"][aria-label="업무 버튼"]'
    items = [('화면 틀이 있다', {'op': 'visible', 'selector': '[data-ui="business-workspace"]'}),
             ('목록이 있다', {'op': 'visible', 'selector': '[data-ui="record-grid"]'}),
             ('내용을 보는 영역이 있다', {'op': 'visible', 'selector': '[data-ui="document-editor"]'}),
             ('공통 버튼 조회 이(가) 있다', {'op': 'visible', 'selector': f'{toolbar} >> role=button[name="조회"]'}),
             ('신규 버튼이 없다', {'op': 'absent', 'selector': f'{toolbar} >> role=button[name="신규"]'}),
             ('삭제 버튼이 없다', {'op': 'absent', 'selector': f'{toolbar} >> role=button[name="삭제"]'})]
    items.append(('저장 버튼이 있다' if definition['over'].get('edit') else '저장 버튼이 없다',
                  {'op': 'visible' if definition['over'].get('edit') else 'absent', 'selector': f'{toolbar} >> role=button[name="저장"]'}))
    return [{'id': f'C{index + 1}', 'requirement_id': 'R1', 'description': description, 'check': check} for index, (description, check) in enumerate(items)]


def dashboard_checks(key, definition, framework):
    """A dashboard stores nothing and computes nothing of its own: every panel must point at a summary that answers."""
    report = Report()
    known = {item['key']: item['definition'] for item in framework.definitions()}
    for panel in definition['dashboard']['panels']:
        code, answer = framework.call('GET', f"/api/summary/{panel['summary']}")
        report.add(f"패널 {panel['title']}: 집계 {panel['summary']} 이(가) 조회된다", code == 200, f'{code} {answer}')
        labels = [value['label'] for value in (known.get(panel['summary'], {}).get('summary') or {}).get('values', [])]
        report.add(f"패널 {panel['title']}: 그릴 값 {panel['value']} 이(가) 그 집계에 있다", panel['value'] in labels, f'{labels}')
    return report


def dashboard_screen_criteria(definition):
    panels = definition['dashboard']['panels']
    items = [('현황판 틀이 있다', {'op': 'visible', 'selector': '[data-ui="dashboard"]'}),
             ('새로 고침 버튼이 있다', {'op': 'visible', 'selector': '[data-ui="dashboard"] >> role=button[name="새로 고침"]'}),
             ('표가 없다 (차트 패널만 있다)', {'op': 'absent', 'selector': '[data-ui="dashboard"] [data-ui="record-grid"]'})]
    for index, panel in enumerate(panels):
        one = f'[data-ui="dashboard-panel"] >> nth={index}'
        items.append((f"패널 {index + 1}: 제목 {panel['title']} 이(가) 보인다", {'op': 'text', 'selector': one, 'contains': panel['title']}))
        inside = '[data-ui="stat-tiles"]' if panel['chart'] == 'figures' else f'[data-ui="chart"][data-kind="{panel["chart"]}"]'
        items.append((f"패널 {index + 1}: {'핵심 숫자' if panel['chart'] == 'figures' else panel['chart'] + ' 차트'}가 그려져 있다", {'op': 'visible', 'selector': f'{one} >> {inside}'}))
    return [{'id': f'C{index + 1}', 'requirement_id': 'R1', 'description': description, 'check': check} for index, (description, check) in enumerate(items)]


def summary_screen_criteria(definition):
    part, toolbar, grid = definition['summary'], '[role="toolbar"][aria-label="업무 버튼"]', '[data-ui="record-grid"]'
    items = [('화면 틀이 있다', {'op': 'visible', 'selector': '[data-ui="business-workspace"]'}),
             ('집계 표가 있다', {'op': 'visible', 'selector': grid})]
    if part.get('filters'):
        items.append(('조회 조건 영역이 있다', {'op': 'visible', 'selector': 'form[data-ui="query-panel"]'}))
    for label in ('조회', '엑셀', '출력'):
        items.append((f'공통 버튼 {label} 이(가) 있다', {'op': 'visible', 'selector': f'{toolbar} >> role=button[name="{label}"]'}))
    for column in part['groupBy'] + part['values']:
        items.append((f"표에 {column['label']} 열이 있다", {'op': 'text', 'selector': grid, 'contains': column['label']}))
    if part.get('chart'):
        kind = part['chart']['type']
        items.append((f"{part['chart']['value']} 차트({kind})가 있다", {'op': 'visible', 'selector': f'[data-ui="chart"][data-kind="{kind}"]'}))
    return [{'id': f'C{index + 1}', 'requirement_id': 'R1', 'description': description, 'check': check} for index, (description, check) in enumerate(items)]


def rule_checks(key, definition, framework):
    """Each blocking rule, on the published entity: blocked while a row points here, allowed once it is gone."""
    report, made, api = Report(), [], f'/api/data/{key}'
    document = bool(definition.get('lines')) and definition['lines'].get('min', 1) > 0
    try:
        for rule in definition.get('rules', []):
            other = next(item['definition'] for item in framework.definitions() if item['key'] == rule['entity'])

            def target():
                if document:
                    body = {field['name']: sample(field, framework, made) for field in definition['fields'] if not _computed(field)}
                    body['lines'] = [_line(definition['lines']['fields'], framework, made, 2)]
                else:
                    body = {field['name']: sample(field, framework, made) for field in definition['fields'] if field['required'] and not _computed(field)}
                row = framework.ok('POST', api, fit(body, definition, framework, made))
                made.append((key, row['id']))
                return row

            def attempt(row):
                if rule['action'] == 'delete':
                    return framework.call('DELETE', f"{api}/{row['id']}")
                if rule['action'] == 'update':
                    again = {name: value for name, value in row.items() if name not in ('id', 'status', 'statusLabel', 'createdBy', 'createdAt', 'updatedBy', 'updatedAt')}
                    return framework.call('PUT', f"{api}/{row['id']}", again)
                return framework.call('POST', f"{api}/{row['id']}/actions/{rule['action']}?check=true")   # ask only: the sample row stays deletable
            row = target()
            pointer = {field['name']: (row['id'] if field['name'] == rule['field'] else sample(field, framework, made))
                       for field in other['fields'] if (field['required'] or field['name'] == rule['field']) and not _computed(field)}
            if other.get('lines') and other['lines'].get('min', 1) > 0:
                pointer['lines'] = [_line(other['lines']['fields'], framework, made, 1)]
            user = framework.ok('POST', f"/api/data/{rule['entity']}", fit(pointer, other, framework, made))
            made.append((rule['entity'], user['id']))
            code, answer = attempt(row)
            report.add(f"규칙: {other['title']} 이(가) 있으면 {rule['action']} 이(가) 거절되고 안내가 나온다 ({rule['message']})",
                       code == 409 and (answer or {}).get('detail') == rule['message'], f'{code} {answer}')
            framework.call('DELETE', f"/api/data/{rule['entity']}/{user['id']}")
            code, answer = attempt(row)
            report.add(f"규칙: {other['title']} 을(를) 지우면 {rule['action']} 이(가) 다시 된다", code in (200, 204), f'{code} {answer}')
    finally:
        report.leftover = sweep(framework, made)
    return report


def effect_checks(key, definition, framework):
    """What follows by itself, on the published entity: the record that should appear does, with the values carried over;
    the record pointed at changes status. Everything made here is removed again (by force where a status locks it)."""
    report, made, api = Report(), [], f'/api/data/{key}'
    known = {item['key']: item['definition'] for item in framework.definitions()}
    status = definition.get('status') or {}
    line_names = [field['name'] for field in (definition.get('lines') or {}).get('fields', [])]

    def source(extra=None):
        body = {field['name']: sample(field, framework, made) for field in definition['fields'] if not _computed(field)}
        if definition.get('lines'):
            body['lines'] = [_line(definition['lines']['fields'], framework, made, 2)]
        body = fit(dict(body, **(extra or {})), definition, framework, made)
        row = framework.ok('POST', api, body)
        made.append((key, row['id']))
        return row

    def trigger(row, on):
        if on == 'create':
            return 201, row
        action = next(item for item in status['actions'] if item['name'] == on)
        if row.get('status') not in action['from']:        # one step first, when the action does not start from the first status
            step = next((item for item in status['actions'] if row.get('status') in item['from'] and item['to'] in action['from']), None)
            if step:
                framework.call('POST', f"{api}/{row['id']}/actions/{step['name']}")
        return framework.call('POST', f"{api}/{row['id']}/actions/{on}")
    try:
        for effect in definition.get('effects') or []:
            when = '등록하면' if effect['on'] == 'create' else next((item['label'] for item in status.get('actions', []) if item['name'] == effect['on']), effect['on']) + ' 하면'
            if effect.get('create'):
                make, other = effect['create'], known[effect['create']['entity']]
                before = {item['id'] for item in framework.ok('GET', f"/api/data/{make['entity']}")}
                row = source()
                code, answer = trigger(row, effect['on'])
                new = [item for item in framework.ok('GET', f"/api/data/{make['entity']}") if item['id'] not in before]
                for item in new:
                    made.append((make['entity'], item['id']))
                if not report.add(f"자동 처리: {when} {other['title']} 이(가) 한 건 만들어진다", code in (200, 201) and len(new) == 1, f'{code} {answer} / 새로 생긴 {len(new)}건'):
                    continue
                today = __import__('datetime').date.today().isoformat()
                wrong = [(into, new[0].get(into)) for into, come in make['set'].items()
                         if new[0].get(into) != (row['id'] if come == 'id' else today if come == 'today' else row.get(come))]
                report.add(f"자동 처리: 만들어진 {other['title']} 에 값이 그대로 옮겨진다 ({', '.join(make['set'])})", not wrong, f'다른 값 {wrong}')
                if make.get('lines'):
                    got = [[line.get(into) for into in make['lines']['set']] for line in new[0].get('lines', [])]
                    want = [[line.get(come) for come in make['lines']['set'].values()] for line in row.get('lines', [])]
                    report.add('자동 처리: 줄 표도 줄마다 옮겨진다', got == want, f'기대 {want}, 실제 {got}')
            else:
                act = effect['act']
                pointer = next(field for field in definition['fields'] if field['name'] == act['via'])
                other = known[pointer['ref']['entity']]
                wanted = next(item for item in other['status']['actions'] if item['name'] == act['action'])
                if effect['on'] == 'create':
                    # The record pointed at must already stand where the action starts, so it is made and brought there first.
                    pointed = sample(pointer, framework, made)
                    target = f"/api/data/{pointer['ref']['entity']}/{pointed}"
                    fresh = framework.ok('GET', target)
                    if fresh.get('status') not in wanted['from']:
                        step = next((item for item in other['status']['actions'] if fresh.get('status') in item['from'] and item['to'] in wanted['from']), None)
                        if step:
                            framework.call('POST', f"{target}/actions/{step['name']}")
                    row = source({act['via']: pointed})
                    code, answer = 201, row
                else:
                    row = source()
                    target = f"/api/data/{pointer['ref']['entity']}/{row[act['via']]}"
                    code, answer = trigger(row, effect['on'])
                after = framework.ok('GET', target)
                names = {value['code']: value['label'] for value in other['status']['values']}
                report.add(f"자동 처리: {when} 가리키는 {other['title']} 이(가) {names.get(wanted['to'], wanted['to'])} 상태가 된다 (그 동작을 할 수 있는 상태일 때)",
                           code in (200, 201) and (after.get('status') == wanted['to'] or after.get('status') not in wanted['from']), f"{code} / 지금 상태 {after.get('status')}")
    finally:
        report.leftover = sweep(framework, made)
    return report


def rich(definition):
    """The framework draws these with the screen that has a number line, status buttons and a lines table."""
    return bool(definition.get('lines') or definition.get('status') or any(field.get('type') == 'serial' for field in definition['fields']))


def document_screen_criteria(definition):
    import standard_contract
    editor, table, toolbar = '[data-ui="document-editor"]', '[data-ui="document-lines"]', '[role="toolbar"][aria-label="업무 버튼"]'
    items = [('화면 틀이 있다', {'op': 'visible', 'selector': '[data-ui="business-workspace"]'}),
             ('조회 조건 영역이 있다', {'op': 'visible', 'selector': 'form[data-ui="query-panel"]'}),
             ('목록이 있다', {'op': 'visible', 'selector': '[data-ui="record-grid"]'}),
             ('입력 영역이 있다', {'op': 'visible', 'selector': editor})]
    if definition.get('lines'):
        items.append(('줄 표가 있다', {'op': 'visible', 'selector': table}))
    if definition.get('status'):
        items.append(('목록에 상태 열이 있다', {'op': 'text', 'selector': '[data-ui="record-grid"]', 'contains': '상태'}))
    for label in ('조회', '신규', '저장', '삭제'):
        items.append((f'공통 버튼 {label} 이(가) 있다', {'op': 'visible', 'selector': f'{toolbar} >> role=button[name="{label}"]'}))
    for field in definition['fields']:
        if field.get('formula') or field.get('sum') or field['type'] == 'serial':
            items.append((f"입력 영역에 {field['label']} 이(가) 보인다", {'op': 'text', 'selector': editor, 'contains': field['label']}))
        else:
            items.append((f"입력 영역에 {field['label']} 입력칸이 있다", {'op': 'visible', 'selector': f'{editor} >> {standard_contract.by_label(field["label"])}'}))
        items.append((f"목록에 {field['label']} 열이 있다", {'op': 'text', 'selector': '[data-ui="record-grid"]', 'contains': field['label']}))
    for field in (definition.get('lines') or {}).get('fields', []):
        items.append((f"줄 표에 {field['label']} 열이 있다", {'op': 'text', 'selector': table, 'contains': field['label']}))
    return [{'id': f'C{index + 1}', 'requirement_id': 'R1', 'description': description, 'check': check} for index, (description, check) in enumerate(items)]


def screen_checks(title, definition, record_to, app):
    """Open the screen in a real browser (read-only) and look for what the definition promises."""
    sys.path.insert(0, str(HARNESS))
    import standard_contract
    if definition.get('over'):
        criteria = over_screen_criteria(definition)
    elif definition.get('dashboard'):
        criteria = dashboard_screen_criteria(definition)
    elif definition.get('summary'):
        criteria = summary_screen_criteria(definition)
    elif rich(definition):
        criteria = document_screen_criteria(definition)
    else:
        sheet = {'path': '/api/x', 'fields': [{'name': field['name'], 'label': field['label'], 'required': field['required'], 'sample': 'x'} for field in definition['fields']]}
        criteria = standard_contract.screen_criteria(sheet)
    if not definition.get('summary') and not definition.get('dashboard') and not definition.get('over'):
        criteria.append({'id': f'C{len(criteria) + 1}', 'requirement_id': 'R1', 'description': '한 건을 양식으로 뽑는 출력 버튼이 있다',
                         'check': {'op': 'visible', 'selector': '[role="toolbar"][aria-label="업무 버튼"] >> role=button[name="출력"]'}})
    out = Path(record_to) / 'browser'
    data = {'open_screen': title, 'contract': {'criteria': criteria, 'requirements': []}, 'preview_url': app + '/?drafts=1', 'api_url': '',
            'output_dir': str(out / uuid.uuid4().hex), 'allow_browser_writes': False, 'allow_api_writes': False}
    done = subprocess.run(['node', str(HARNESS / 'react_layout_inspector.cjs')], input=json.dumps(data), text=True, capture_output=True, timeout=240)
    report = Report()
    try:
        results = {result['id']: result for result in json.loads(done.stdout).get('results', [])}
    except ValueError:
        report.add('화면 확인을 실행한다', False, (done.stderr or done.stdout)[-300:])
        return report
    for criterion in criteria:
        result = results.get(criterion['id'], {})
        report.add('화면: ' + criterion['description'], result.get('status') == 'passed', result.get('reason', '결과 없음'))
    return report
