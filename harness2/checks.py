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
        row = framework.ok('POST', f'/api/data/{target}', body)
        made.append((target, row['id']))
        return row['id']
    return f"{field['label']} 시험" + (str(next(_serial)) if field.get('unique') else '')


def _computed(field):
    return bool(field.get('formula') or field.get('sum') or field.get('type') == 'serial')


LEFTOVER = []


def sweep(framework, made):
    """Delete the sample rows, newest first. Returns the ones that could not be deleted yet (a row a locked
    trial document still points at goes once the trial definition is removed)."""
    left = []
    for entity, record in reversed(made):
        code, _ = framework.call('DELETE', f'/api/data/{entity}/{record}')
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
        return body

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
        code, answer = post(minimal)
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
                row = framework.ok('POST', api, body)
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
            user = framework.ok('POST', f"/api/data/{rule['entity']}", pointer)
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
    if rich(definition):
        criteria = document_screen_criteria(definition)
    else:
        sheet = {'path': '/api/x', 'fields': [{'name': field['name'], 'label': field['label'], 'required': field['required'], 'sample': 'x'} for field in definition['fields']]}
        criteria = standard_contract.screen_criteria(sheet)
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
