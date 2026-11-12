"""Checks derived from a definition. Nobody writes scenarios: each thing a definition can say brings its own.

  entity            create -> appears in the list -> update -> delete -> gone
  required field    a blank value is refused
  optional fields   may all be left out
  number/date/code  a wrong kind of value is refused
  ref field         a missing target is refused; a target that is in use cannot be deleted, and can once it is free
  search field      filters the list
  screen            workspace, query panel, grid, editor, toolbar; every field is in the editor; required ones are marked and in the grid
  document          numbering, a line is needed, computed line values and header totals, status start, each action and its refusal, locked statuses
  blocking rule     refused (with its message) while a row points here; allowed again once that row is gone

Everything runs against a trial copy of the definition (a draft the menus never show), and every row a
check creates is removed again, also when a check fails.
"""
import json
import subprocess
import sys
import uuid
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[1] / 'erp-harness'


def sample(field, framework, made):
    """A value of the right kind for this field; for a ref, a freshly made row of the target (remembered in made)."""
    kind = field.get('type', 'text')
    if kind == 'number':
        return 10
    if kind == 'date':
        return '2026-01-15'
    if kind == 'code':
        codes = framework.codes(field['codeGroup'])
        return codes[0]['code'] if codes else None
    if kind == 'ref':
        target = field['ref']['entity']
        definition = next(item['definition'] for item in framework.definitions() if item['key'] == target)
        body = {item['name']: sample(item, framework, made) for item in definition['fields'] if item.get('required')}
        if definition.get('lines'):      # a document cannot exist without a line
            body['lines'] = [_line(definition['lines']['fields'], framework, made, 1)]
        row = framework.ok('POST', f'/api/data/{target}', body)
        made.append((target, row['id']))
        return row['id']
    return f"{field['label']} 시험"


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


def data_checks(key, definition, framework):
    """Run the data rules of this definition against /api/data/<key>."""
    report, made, api = Report(), [], f'/api/data/{key}'
    fields = definition['fields']
    main = next(field for field in fields if field['required'] and field.get('type', 'text') == 'text')
    try:
        body = {field['name']: sample(field, framework, made) for field in fields}
        status, row = framework.call('POST', api, body)
        if not report.add('등록: 모든 항목을 채워 저장된다', status == 201, f'{status} {row}'):
            return report
        made.append((key, row['id']))
        wrong = [field['label'] for field in fields if body[field['name']] is not None and row.get(field['name']) != body[field['name']]]
        report.add('저장 확인: 보낸 값이 항목마다 그대로 돌아온다', not wrong, f'다르게 저장된 항목: {wrong}')
        status, rows = framework.call('GET', api)
        report.add('조회: 목록에 방금 등록한 자료가 있다', status == 200 and any(item['id'] == row['id'] for item in rows), f'{status}')
        for field in [item for item in fields if item.get('search') and item.get('type', 'text') == 'text']:
            _, hit = framework.call('GET', f"{api}?{field['name']}={body[field['name']]}")
            _, miss = framework.call('GET', f"{api}?{field['name']}=없는값zzqq")
            report.add(f"조회 조건 {field['label']}: 맞는 값은 찾고 없는 값은 못 찾는다", any(item['id'] == row['id'] for item in hit or []) and not miss, f'hit={len(hit or [])} miss={len(miss or [])}')
        changed = dict(body, **{main['name']: body[main['name']] + ' 수정'})
        status, updated = framework.call('PUT', f"{api}/{row['id']}", changed)
        report.add(f"수정: {main['label']} 을(를) 바꿀 수 있다", status == 200 and updated.get(main['name']) == changed[main['name']], f'{status} {updated}')
        for field in [item for item in fields if item['required']]:
            status, answer = framework.call('POST', api, dict(body, **{field['name']: '' if field.get('type', 'text') == 'text' else None}))
            if status == 201:
                made.append((key, answer['id']))
            report.add(f"필수 항목 {field['label']}: 비우면 거절된다", status == 400, f'{status} {answer}')
        status, minimal = framework.call('POST', api, {field['name']: body[field['name']] for field in fields if field['required']})
        if status == 201:
            made.append((key, minimal['id']))
        report.add('선택 항목은 모두 비워도 저장된다', status == 201, f'{status} {minimal}')
        wrong_values = {'number': '열 개', 'date': '1월 15일', 'code': '없는코드zz', 'ref': 999999999}
        for field in [item for item in fields if item.get('type', 'text') in wrong_values]:
            status, answer = framework.call('POST', api, dict(body, **{field['name']: wrong_values[field['type']]}))
            if status == 201:
                made.append((key, answer['id']))
            report.add(f"{field['label']}: 맞지 않는 값({wrong_values[field['type']]})은 거절된다", status == 400, f'{status} {answer}')
        for field in [item for item in fields if item.get('type') == 'ref']:
            target, target_id = field['ref']['entity'], body[field['name']]
            status, answer = framework.call('DELETE', f'/api/data/{target}/{target_id}')
            report.add(f"{field['label']}: 쓰이고 있는 대상 자료는 삭제가 거절된다", status == 409, f'{status} {answer}')
        status, _ = framework.call('DELETE', f"{api}/{row['id']}")
        report.add('삭제: 자료를 지울 수 있다', status == 204, f'{status}')
        status, _ = framework.call('PUT', f"{api}/{row['id']}", changed)
        report.add('지운 자료는 더 수정할 수 없다', status == 404, f'{status}')
    finally:
        for entity, record in reversed(made):   # the rows the checks made, newest first so users go before their targets
            framework.call('DELETE', f'/api/data/{entity}/{record}')
    return report


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
            body[field['name']] = number
            number = number * 100 + 50     # e.g. quantity 3 -> price 350
        else:
            body[field['name']] = sample(field, framework, made)
    return body


def document_checks(key, definition, framework):
    """A document: numbering, lines, computed amounts and totals, status actions, locked statuses."""
    report, made, api = Report(), [], f'/api/data/{key}'
    fields, lines, status = definition['fields'], definition['lines']['fields'], definition.get('status')
    plain = [field for field in fields if not (field.get('formula') or field.get('sum') or field['type'] == 'serial')]

    def new_body():
        body = {field['name']: sample(field, framework, made) for field in plain}
        body['lines'] = [_line(lines, framework, made, 3), _line(lines, framework, made, 2)]
        return body

    def create():
        status_code, row = framework.call('POST', api, new_body())
        if status_code == 201:
            made.append((key, row['id']))
        return status_code, row
    try:
        body = new_body()
        for line in body['lines']:                      # values the server must ignore and compute itself
            for field in lines:
                if field.get('formula'):
                    line[field['name']] = 1
        code, row = framework.call('POST', api, body)
        if not report.add('등록: 머리와 명세 두 줄을 채워 저장된다', code == 201, f'{code} {row}'):
            return report
        made.append((key, row['id']))
        for field in [item for item in lines if item.get('formula')]:
            expected = [_calc(field['formula'], {name: line.get(name) for name in line}) for line in body['lines']]
            got = [line.get(field['name']) for line in row['lines']]
            report.add(f"계산: 명세의 {field['label']} = {field['formula']} (보낸 값은 무시된다)", got == expected, f'기대 {expected}, 실제 {got}')
        for field in [item for item in fields if item.get('sum')]:
            expected = sum(line.get(field['sum']) or 0 for line in row['lines'])
            report.add(f"합계: 머리의 {field['label']} 은(는) 명세 {field['sum']} 의 합이다", row.get(field['name']) == expected, f"기대 {expected}, 실제 {row.get(field['name'])}")
        for field in [item for item in fields if item['type'] == 'serial']:
            code2, second = create()
            first, next_one = str(row.get(field['name'])), str(second.get(field['name'])) if code2 == 201 else ''
            report.add(f"채번: {field['label']} 이(가) {field['prefix']}- 로 시작하고 문서마다 다르게 이어진다",
                       first.startswith(field['prefix'] + '-') and next_one.startswith(field['prefix'] + '-') and next_one > first, f'{first}, {next_one}')
        code, rows = framework.call('GET', api)
        report.add('조회: 목록에 방금 등록한 문서가 있다', code == 200 and any(item['id'] == row['id'] for item in rows), f'{code}')
        code, answer = framework.call('POST', api, dict(new_body(), lines=[]))
        report.add('명세가 한 줄도 없으면 거절된다', code == 400, f'{code} {answer}')
        for field in [item for item in plain if item['required']]:
            code, answer = framework.call('POST', api, dict(new_body(), **{field['name']: None}))
            if code == 201:
                made.append((key, answer['id']))
            report.add(f"머리 필수 항목 {field['label']}: 비우면 거절된다", code == 400, f'{code} {answer}')
        for field in [item for item in lines if item['required']]:
            broken = new_body()
            broken['lines'][0][field['name']] = None
            code, answer = framework.call('POST', api, broken)
            if code == 201:
                made.append((key, answer['id']))
            report.add(f"명세 필수 항목 {field['label']}: 비우면 거절된다", code == 400, f'{code} {answer}')
        changed = new_body()
        code, updated = framework.call('PUT', f"{api}/{row['id']}", changed)
        report.add('수정: 문서를 고쳐 저장할 수 있다 (번호는 그대로)', code == 200 and all(updated.get(f['name']) == row.get(f['name']) for f in fields if f['type'] == 'serial'), f'{code} {updated}')
        if status:
            report.add(f"상태: 새 문서는 {status['values'][0]['label'] if status['initial'] == status['values'][0]['code'] else status['initial']} 상태로 시작한다",
                       row.get('status') == status['initial'], f"{row.get('status')}")
            for action in status['actions']:
                if status['initial'] in action['from']:
                    _, fresh = create()
                    code, after = framework.call('POST', f"{api}/{fresh['id']}/actions/{action['name']}")
                    report.add(f"동작 {action['label']}: {status['initial']} 상태에서 되고 {action['to']} 상태가 된다", code == 200 and after.get('status') == action['to'], f'{code} {after}')
                    if action['to'] not in action['from']:
                        code, again = framework.call('POST', f"{api}/{fresh['id']}/actions/{action['name']}")
                        report.add(f"동작 {action['label']}: 이미 {action['to']} 상태면 거절된다", code == 409, f'{code} {again}')
                    if action['to'] in status.get('locked', []):
                        code, answer = framework.call('PUT', f"{api}/{fresh['id']}", new_body())
                        report.add(f"{action['to']} 상태의 문서는 수정이 거절된다", code == 409, f'{code} {answer}')
        code, _ = framework.call('DELETE', f"{api}/{row['id']}")
        report.add('삭제: 문서를 지울 수 있다', code == 204, f'{code}')
    finally:
        report.leftover = sweep(framework, made)
    return report


def rule_checks(key, definition, framework):
    """Each blocking rule, on the published entity: blocked while a row points here, allowed once it is gone."""
    report, made, api = Report(), [], f'/api/data/{key}'
    document = definition.get('type') == 'document'
    try:
        for rule in definition.get('rules', []):
            other = next(item['definition'] for item in framework.definitions() if item['key'] == rule['entity'])

            def target():
                if document:
                    body = {field['name']: sample(field, framework, made) for field in definition['fields'] if not (field.get('formula') or field.get('sum') or field['type'] == 'serial')}
                    body['lines'] = [_line(definition['lines']['fields'], framework, made, 2)]
                else:
                    body = {field['name']: sample(field, framework, made) for field in definition['fields'] if field['required']}
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
                       for field in other['fields'] if field['required'] or field['name'] == rule['field']}
            if other.get('lines'):
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


def document_screen_criteria(definition):
    import standard_contract
    editor, table, toolbar = '[data-ui="document-editor"]', '[data-ui="document-lines"]', '[role="toolbar"][aria-label="업무 버튼"]'
    items = [('화면 틀이 있다', {'op': 'visible', 'selector': '[data-ui="business-workspace"]'}),
             ('조회 조건 영역이 있다', {'op': 'visible', 'selector': 'form[data-ui="query-panel"]'}),
             ('문서 목록이 있다', {'op': 'visible', 'selector': '[data-ui="record-grid"]'}),
             ('문서 편집 영역이 있다', {'op': 'visible', 'selector': editor}),
             ('명세 표가 있다', {'op': 'visible', 'selector': table})]
    for label in ('조회', '신규', '저장', '삭제'):
        items.append((f'공통 버튼 {label} 이(가) 있다', {'op': 'visible', 'selector': f'{toolbar} >> role=button[name="{label}"]'}))
    for field in definition['fields']:
        if field.get('formula') or field.get('sum') or field['type'] == 'serial':
            items.append((f"머리에 {field['label']} 이(가) 보인다", {'op': 'text', 'selector': editor, 'contains': field['label']}))
        else:
            items.append((f"머리에 {field['label']} 입력칸이 있다", {'op': 'visible', 'selector': f'{editor} >> {standard_contract.by_label(field["label"])}'}))
        items.append((f"목록에 {field['label']} 열이 있다", {'op': 'text', 'selector': '[data-ui="record-grid"]', 'contains': field['label']}))
    for field in definition['lines']['fields']:
        items.append((f"명세 표에 {field['label']} 열이 있다", {'op': 'text', 'selector': table, 'contains': field['label']}))
    return [{'id': f'C{index + 1}', 'requirement_id': 'R1', 'description': description, 'check': check} for index, (description, check) in enumerate(items)]


def screen_checks(title, definition, record_to, app):
    """Open the screen in a real browser (read-only) and look for what the definition promises."""
    sys.path.insert(0, str(HARNESS))
    import standard_contract
    if definition.get('type') == 'document':
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
