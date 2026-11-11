"""Checks derived from a definition. Nobody writes scenarios: each thing a definition can say brings its own.

  entity            create -> appears in the list -> update -> delete -> gone
  required field    a blank value is refused
  optional fields   may all be left out
  number/date/code  a wrong kind of value is refused
  ref field         a missing target is refused; a target that is in use cannot be deleted, and can once it is free
  search field      filters the list
  screen            workspace, query panel, grid, editor, toolbar; every field is in the editor; required ones are marked and in the grid

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
        body = {item['name']: sample(item, framework, made) for item in definition['fields'] if item['required']}
        row = framework.ok('POST', f'/api/data/{target}', body)
        made.append((target, row['id']))
        return row['id']
    return f"{field['label']} 시험"


class Report:
    def __init__(self):
        self.results = []

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


def screen_checks(title, definition, record_to, app):
    """Open the screen in a real browser (read-only) and look for what the definition promises."""
    sys.path.insert(0, str(HARNESS))
    import standard_contract
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
