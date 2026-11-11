"""Acceptance criteria for the standard cases, built by the harness instead of written by the model.

A new registration API and a new registration screen always have the same shape. What differs is the
list of fields. So the model is asked for one small thing only, the field sheet (path, field names,
labels, which are required), and every check is derived from it mechanically:

  API     create -> list shows it -> update -> a blank required field is refused -> delete
  screen  the workspace, query panel, grid, editor and toolbar exist; required fields are in the editor
          (marked required) and in the grid

The screen checks are read-only because browser checks may not write to the running app; saving and
deleting are proven by the API checks. Anything that is not this standard shape returns None and the
model-written contract is used as before.
"""
import json
import os
import re
import time
from pathlib import Path

SHEETS = Path.home() / '.local/state/local-workshop/field-sheets'
RESERVED = {'id', 'createdBy', 'createdAt', 'updatedBy', 'updatedAt'}
PATH = re.compile(r'^/api/[a-z][a-z0-9-]{1,40}$')
NAME = re.compile(r'^[a-z][A-Za-z0-9]{0,39}$')


def _sheet_file(root, path):
    return SHEETS / Path(root).name / (path.strip('/').replace('/', '_') + '.json')


def existing_api_paths(root):
    paths = set()
    for source in (Path(root) / 'backend/src/main/java').rglob('*Controller.java'):
        match = re.search(r'@RequestMapping\("(/api/[^"]+)"\)', source.read_text(encoding='utf-8', errors='replace'))
        if match:
            paths.add(match.group(1))
    return paths


def validate_sheet(sheet, taken=()):
    """The field sheet in canonical form, or ValueError with what to fix."""
    if not isinstance(sheet, dict):
        raise ValueError('Answer with one JSON object {"path": ..., "fields": [...]}')
    path = sheet.get('path')
    if not isinstance(path, str) or not PATH.fullmatch(path):
        raise ValueError('path must look like /api/companies (lower-case plural English noun, no trailing slash)')
    if path in taken:
        raise ValueError(f'{path} already exists; this task adds a NEW API, choose the path of the new resource')
    fields = sheet.get('fields')
    if not isinstance(fields, list) or not 1 <= len(fields) <= 20:
        raise ValueError('fields must be a list of 1 to 20 fields')
    out, seen = [], set()
    for field in fields:
        if not isinstance(field, dict):
            raise ValueError('each field is an object {name, label, required, sample}')
        name, label, sample = field.get('name'), field.get('label'), field.get('sample')
        if not isinstance(name, str) or not NAME.fullmatch(name):
            raise ValueError(f'field name {name!r} must be camelCase English letters/digits (e.g. companyName)')
        if name in RESERVED:
            raise ValueError(f'{name} is managed by the framework; leave it out')
        if name in seen:
            raise ValueError(f'field {name} is listed twice')
        seen.add(name)
        if not isinstance(label, str) or not label.strip() or len(label) > 30:
            raise ValueError(f'field {name} needs a short Korean label')
        if not isinstance(sample, str) or not sample.strip() or len(sample) > 40:
            raise ValueError(f'field {name} needs a short sample value as a string')
        out.append({'name': name, 'label': label.strip(), 'required': field.get('required') is True, 'sample': sample.strip()})
    if not any(field['required'] for field in out):
        raise ValueError('mark at least the main name or code field as "required": true')
    if sum(field['required'] for field in out) > max(2, len(out) // 2):
        raise ValueError('only fields a record cannot exist without are required (usually the name and/or code); the rest are optional')
    return {'path': path, 'fields': out}


def api_criteria(sheet):
    """create -> list -> update -> refuse blank -> delete, in this order on a fresh database (first id is 1)."""
    path, fields = sheet['path'], sheet['fields']
    key = next(field for field in fields if field['required'])
    body = {field['name']: field['sample'] for field in fields}
    changed = dict(body, **{key['name']: key['sample'] + ' 수정'})
    blank = dict(body, **{key['name']: ''})
    return [
        {'id': 'C1', 'requirement_id': 'R1', 'description': f"등록: POST {path} 가 저장하고 {key['label']} 을(를) 돌려준다",
         'check': {'op': 'api', 'method': 'POST', 'path': path, 'status': 201, 'body': body, 'json_path': [key['name']], 'equals': key['sample']}},
        {'id': 'C2', 'requirement_id': 'R1', 'description': f"조회: GET {path} 목록에 방금 등록한 자료가 있다",
         'check': {'op': 'api', 'method': 'GET', 'path': path, 'status': 200, 'json_path': [0, key['name']], 'equals': key['sample']}},
        {'id': 'C3', 'requirement_id': 'R1', 'description': f"수정: PUT {path}/1 이 {key['label']} 을(를) 바꾼다",
         'check': {'op': 'api', 'method': 'PUT', 'path': f'{path}/1', 'status': 200, 'body': changed, 'json_path': [key['name']], 'equals': changed[key['name']]}},
        {'id': 'C4', 'requirement_id': 'R1', 'description': f"필수 항목 {key['label']}({key['name']}) 이(가) 빈 값이면 400 으로 거절한다",
         'check': {'op': 'api', 'method': 'POST', 'path': path, 'status': 400, 'body': blank}},
        {'id': 'C5', 'requirement_id': 'R1', 'description': f"삭제: DELETE {path}/1 이 204 로 지운다",
         'check': {'op': 'api', 'method': 'DELETE', 'path': f'{path}/1', 'status': 204}},
        {'id': 'C6', 'requirement_id': 'R1', 'description': f"지운 자료는 더 수정할 수 없다: PUT {path}/1 이 404 로 답한다",
         'check': {'op': 'api', 'method': 'PUT', 'path': f'{path}/1', 'status': 404, 'body': changed}},
    ]


EDITOR = 'form[data-ui="record-editor"]'
GRID = '[data-ui="record-grid"]'
TOOLBAR = '[role="toolbar"][aria-label="업무 버튼"]'


def screen_criteria(sheet):
    required = [field for field in sheet['fields'] if field['required']]
    criteria = [
        ('화면 틀(BusinessWorkspace)이 있다', {'op': 'visible', 'selector': '[data-ui="business-workspace"]'}),
        ('조회 조건 영역이 있다', {'op': 'visible', 'selector': 'form[data-ui="query-panel"]'}),
        ('결과 그리드가 있다', {'op': 'visible', 'selector': GRID}),
        ('편집 패널이 있다', {'op': 'visible', 'selector': EDITOR}),
    ]
    for label in ('조회', '신규', '저장', '삭제'):
        criteria.append((f'공통 버튼 {label} 이(가) 있다', {'op': 'visible', 'selector': f'{TOOLBAR} >> role=button[name="{label}"]'}))
    for field in required:
        label = field['label']
        # The label carries the required mark (" *"), so the field is found by a non-exact label match.
        criteria.append((f"편집 패널에 필수 항목 {label} 입력칸이 있다", {'op': 'visible', 'selector': f'{EDITOR} >> internal:label="{label}"i'}))
        criteria.append((f"{label} 은(는) 필수 표시(*)가 있다", {'op': 'text', 'selector': f'{EDITOR} label:has-text("{label}")', 'contains': '*'}))
        criteria.append((f"그리드에 {label} 열이 있다", {'op': 'text', 'selector': GRID, 'contains': label}))
    return [{'id': f'C{index + 1}', 'requirement_id': 'R1', 'description': description, 'check': check}
            for index, (description, check) in enumerate(criteria)]


def sheet_note(sheet, screen=False):
    """What the author is told: the same names, labels and required marks the checks use."""
    rows = ', '.join(f"{field['name']}({field['label']}{', 필수' if field['required'] else ''})" for field in sheet['fields'])
    if screen:
        return (f"\n항목표(검사가 이 이름과 라벨을 그대로 쓴다): API {sheet['path']} / {rows}. 라벨은 표의 한국어를 그대로 쓰고, 필수 항목은 "
                "required:true 와 group:'basic' 으로 둔다. 그리드에는 적어도 필수 항목 열을 같은 라벨로 넣는다.\n")
    return (f"\n항목표(검사가 이 경로와 이름을 그대로 쓴다): {sheet['path']} / {rows}. JSON 필드 이름은 표의 영문 이름과 정확히 같게 한다. "
            "POST 는 201 과 저장된 자료, GET 은 목록 배열, PUT /{id} 는 200 과 수정된 자료, DELETE /{id} 는 204, "
            "필수 항목이 비어 있으면 400 으로 답한다(품목 API 와 같은 방식).\n")


SHEET_PROMPT = '''새로 만들 등록 API의 항목표를 JSON 하나로만 답하라. 설명이나 코드 블록 표시는 쓰지 않는다.
형식: {"path": "/api/<영문 소문자 복수형>", "fields": [{"name": "<camelCase 영문>", "label": "<한국어 이름>", "required": true|false, "sample": "<예시 값 문자열>"}]}
규칙:
- 요청과 방향에 나온 항목만 넣는다. id 와 등록/수정자·일시는 프레임워크가 관리하므로 넣지 않는다.
- required 는 그 값 없이는 자료가 성립하지 않는 항목(보통 이름이나 코드 하나)에만 true 를 준다. 나머지는 false.
- sample 은 그 항목에 들어갈 만한 짧은 문자열 값이다.
- 이미 있는 API 경로(%s)는 쓰지 않는다.
요청: %s
방향: %s'''


def ask_sheet(runner, taken):
    task, approach = str(runner.args.task), os.environ.get('HARNESS_TASK_APPROACH', '').strip()
    messages = [{'role': 'system', 'content': 'JSON only'},
                {'role': 'user', 'content': SHEET_PROMPT % (', '.join(sorted(taken)) or '없음', task, approach[:800] or '없음')}]
    error = ''
    for attempt in range(3):
        response = runner.ask(messages=list(messages), tools=[])
        text = str(response.get('content') or '')
        try:
            found = re.search(r'\{.*\}', text, re.S)
            return validate_sheet(json.loads(found.group(0)) if found else None, taken)
        except (ValueError, AttributeError) as problem:
            error = str(problem)
            runner.h.log_event('requirement.sheet_rejected', {'attempt': attempt + 1, 'error': error[:300]})
            messages = messages[:2] + [{'role': 'assistant', 'content': text[:2000]},
                                       {'role': 'user', 'content': f'고쳐서 JSON 전체를 다시 답하라: {error}'}]
    raise ValueError('field sheet unavailable: ' + error)


def _is_new_api(runner):
    modes = set(getattr(runner, 'modes', ()) or ())
    task = str(runner.args.task)
    return 'backend' in modes and not ({'frontend', 'framework'} & modes) \
        and re.search(r'API|엔티티|테이블|컨트롤러|entity|controller', task, re.I) and not re.search(r'테스트|test|fixture|수정|변경|추가해|바꿔|고쳐', task, re.I)


def _unused_sheet(root):
    """The newest saved sheet whose API exists and is not used by any screen yet: the API the new screen is for."""
    folder = SHEETS / Path(root).name
    screens = '\n'.join(path.read_text(encoding='utf-8', errors='replace') for path in (Path(root) / 'frontend/src/screens').glob('*.tsx'))
    apis = existing_api_paths(root)
    for file in sorted(folder.glob('*.json'), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            sheet = validate_sheet(json.loads(file.read_text(encoding='utf-8')))
        except (ValueError, OSError):
            continue
        if sheet['path'] in apis and sheet['path'] not in screens:
            return sheet
    return None


def build(runner, new_screen_reference=''):
    """(raw contract, kind) for a standard task, else None. Sets runner._field_sheet_note for the author's brief."""
    if os.environ.get('HARNESS_STANDARD_CONTRACT') == '0':
        return None
    root, task = runner.h.workspace.root, str(runner.args.task)
    if '\n' in task.strip():
        return None  # several request clauses: not the plain standard case
    import requirement_contract
    base = {'version': 1, 'task': task, 'requirements': requirement_contract.requirements(task)}
    if _is_new_api(runner):
        sheet = ask_sheet(runner, existing_api_paths(root))
        file = _sheet_file(root, sheet['path'])
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(dict(sheet, task=task, saved_at=time.strftime('%Y-%m-%dT%H:%M:%S')), ensure_ascii=False, indent=1), encoding='utf-8')
        runner._field_sheet_note = sheet_note(sheet)
        return dict(base, criteria=api_criteria(sheet)), 'standard-api', sheet
    if new_screen_reference and 'backend' not in (getattr(runner, 'modes', ()) or ()):
        sheet = _unused_sheet(root)
        if sheet:
            runner._field_sheet_note = sheet_note(sheet, screen=True)
            return dict(base, criteria=screen_criteria(sheet)), 'standard-screen', sheet
    return None
