"""Acceptance criteria for the standard cases, built by the harness instead of written by the model.

A new registration API and a new registration screen always have the same shape. What differs is the
list of fields. So the model is asked for one small thing only, the field sheet (path, field names,
labels, which are required), and every check is derived from it mechanically:

  API     create -> list shows it -> update -> a blank required field is refused -> optional fields may be omitted -> delete
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


def known_refs(root):
    """{api path: saved sheet} of the registration APIs another record may point to."""
    apis, out = existing_api_paths(root), {}
    for file in (SHEETS / Path(root).name).glob('*.json'):
        try:
            sheet = validate_sheet(json.loads(file.read_text(encoding='utf-8')))
        except (ValueError, OSError):
            continue
        if sheet['path'] in apis:
            out[sheet['path']] = sheet
    return out


def validate_sheet(sheet, taken=(), refs=None, few_required=False):
    """The field sheet in canonical form, or ValueError with what to fix.

    refs: the APIs a field may point to ({path: sheet}); None accepts any ref (re-reading a saved sheet)."""
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
        ref = field.get('ref')
        if ref is not None:
            if not isinstance(ref, dict) or not isinstance(ref.get('path'), str) or not PATH.fullmatch(ref['path']) or not isinstance(ref.get('label'), str) \
                    or not NAME.fullmatch(ref['label']):
                raise ValueError(f'field {name}: ref must be {{"path": "/api/<existing>", "label": "<field of that record to show>"}}')
            if refs is not None:
                if ref['path'] not in refs:
                    raise ValueError(f"field {name}: ref path {ref['path']} is not an existing registration API; choose one of {sorted(refs) or 'none (leave ref out)'}")
                names = [item['name'] for item in refs[ref['path']]['fields']]
                if ref['label'] not in names:
                    raise ValueError(f"field {name}: ref label must be a field of {ref['path']}: {names}")
            if not name.endswith('Id'):
                raise ValueError(f'field {name} points to another record; name it <target>Id (e.g. departmentId)')
            out.append({'name': name, 'label': label.strip(), 'required': field.get('required') is True, 'sample': '1', 'ref': {'path': ref['path'], 'label': ref['label']}})
            continue
        if not isinstance(sample, str) or not sample.strip() or len(sample) > 40:
            raise ValueError(f'field {name} needs a short sample value as a string')
        kind = field.get('type', 'text')
        if kind not in ('text', 'number', 'date'):
            raise ValueError(f'field {name}: type must be "text", "number" or "date"')
        if kind == 'number' and not re.fullmatch(r'\d{1,9}', sample.strip()):
            raise ValueError(f'field {name} is a number: its sample must be a whole number like "10"')
        if kind == 'date' and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', sample.strip()):
            raise ValueError(f'field {name} is a date: its sample must look like "2026-01-15"')
        item = {'name': name, 'label': label.strip(), 'required': field.get('required') is True, 'sample': sample.strip()}
        if kind != 'text':
            item['type'] = kind
        out.append(item)
    if not any(field['required'] and 'ref' not in field for field in out):
        raise ValueError('mark at least the main name or code field as "required": true')
    # Only for a sheet the model invents: when the user asks for a field to be required, that is their decision.
    if few_required and sum(field['required'] for field in out) > max(2, len(out) // 2):
        raise ValueError('only fields a record cannot exist without are required (usually the name and/or code); the rest are optional')
    return {'path': path, 'fields': out}


def api_criteria(sheet, refs=None):
    """create -> list -> update -> refuse blank -> optional fields omitted -> delete, in this order on a fresh
    database (first id is 1). Records a field points to are created first, from their own sheets."""
    path, fields = sheet['path'], sheet['fields']
    key = next(field for field in fields if field['required'] and 'ref' not in field)
    value = lambda field: 1 if 'ref' in field else int(field['sample']) if field.get('type') == 'number' else field['sample']
    body = {field['name']: value(field) for field in fields}
    changed = dict(body, **{key['name']: key['sample'] + ' 수정'})
    blank = dict(body, **{key['name']: ''})
    # Only the required fields, with distinct values so a unique column cannot be the reason for a refusal.
    minimal = {field['name']: (1 if 'ref' in field else field['sample'] + ' 2') for field in fields if field['required']}
    before = []
    for target in dict.fromkeys(field['ref']['path'] for field in fields if 'ref' in field):
        other = (refs or {}).get(target)
        if other is None or any('ref' in item and item['required'] for item in other['fields']):
            raise ValueError(f'{target} cannot be prepared for the checks (no saved sheet, or it needs another record itself)')
        first = next(item for item in other['fields'] if item['required'] and 'ref' not in item)
        before.append({'id': f'P{len(before) + 1}', 'requirement_id': 'R1', 'description': f"준비: 고를 대상 {target} 자료를 하나 만든다(id 1)",
                       'check': {'op': 'api', 'method': 'POST', 'path': target, 'status': 201,
                                 'body': {item['name']: item['sample'] for item in other['fields'] if item['required'] and 'ref' not in item},
                                 'json_path': [first['name']], 'equals': first['sample']}})
    return before + [
        {'id': 'C1', 'requirement_id': 'R1', 'description': f"등록: POST {path} 가 저장하고 {key['label']} 을(를) 돌려준다",
         'check': {'op': 'api', 'method': 'POST', 'path': path, 'status': 201, 'body': body, 'json_path': [key['name']], 'equals': key['sample']}},
        {'id': 'C2', 'requirement_id': 'R1', 'description': f"조회: GET {path} 목록에 방금 등록한 자료가 있다",
         'check': {'op': 'api', 'method': 'GET', 'path': path, 'status': 200, 'json_path': [0, key['name']], 'equals': key['sample']}},
        *[{'id': f'C2_{index + 2}', 'requirement_id': 'R1', 'description': f"저장 확인: 목록의 {field['label']}({field['name']}) 값이 보낸 값과 같다",
           'check': {'op': 'api', 'method': 'GET', 'path': path, 'status': 200, 'json_path': [0, field['name']], 'equals': value(field)}}
          for index, field in enumerate(item for item in fields if item is not key)],
        {'id': 'C3', 'requirement_id': 'R1', 'description': f"수정: PUT {path}/1 이 {key['label']} 을(를) 바꾼다",
         'check': {'op': 'api', 'method': 'PUT', 'path': f'{path}/1', 'status': 200, 'body': changed, 'json_path': [key['name']], 'equals': changed[key['name']]}},
        {'id': 'C4', 'requirement_id': 'R1', 'description': f"필수 항목 {key['label']}({key['name']}) 이(가) 빈 값이면 400 으로 거절한다",
         'check': {'op': 'api', 'method': 'POST', 'path': path, 'status': 400, 'body': blank}},
        {'id': 'C4b', 'requirement_id': 'R1', 'description': "선택 항목은 비워도 저장된다: 필수 항목만 보낸 POST 가 201 이다",
         'check': {'op': 'api', 'method': 'POST', 'path': path, 'status': 201, 'body': minimal, 'json_path': [key['name']], 'equals': minimal[key['name']]}},
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
    optional = [field for field in sheet['fields'] if not field['required']]
    if optional:
        steps = [{'action': 'click', 'selector': '[data-ui="tabbed-panel"] >> role=tab[name="추가정보"]'}]
        steps += [{'action': 'expect_visible', 'selector': f'{EDITOR} >> internal:label="{field["label"]}"i'} for field in optional]
        criteria.append(('선택 항목(' + ', '.join(field['label'] for field in optional) + ')은 편집 패널의 추가정보 탭에 있다', {'op': 'scenario', 'steps': steps}))
    return [{'id': f'C{index + 1}', 'requirement_id': 'R1', 'description': description, 'check': check}
            for index, (description, check) in enumerate(criteria)]


def sheet_note(sheet, screen=False):
    """What the author is told: the same names, labels and required marks the checks use."""
    def row(field):
        text = f"{field['name']}({field['label']}{', 필수' if field['required'] else ''}{', 숫자' if field.get('type') == 'number' else ', 날짜' if field.get('type') == 'date' else ''}"
        if 'ref' in field:
            text += f", {field['ref']['path']} 에서 고름"
        return text + ')'
    rows = ', '.join(row(field) for field in sheet['fields'])
    refs = [field for field in sheet['fields'] if 'ref' in field]
    if screen:
        note = (f"\n항목표(검사가 이 이름과 라벨을 그대로 쓴다): API {sheet['path']} / {rows}. 라벨은 표의 한국어를 그대로 쓴다. 필수 항목은 "
                "required:true 와 group:'basic', 선택 항목은 group:'extra'(추가정보 탭)로 둔다. 그리드에는 적어도 필수 항목 열을 같은 라벨로 넣는다. "
                "숫자 항목은 type:'integer' 로 두고 저장할 때 Number(값) 또는 null 을 보낸다. 날짜 항목은 placeholder:'2026-01-15' 인 글자 입력으로 둔다.\n")
        for field in refs:
            note += (f"{field['label']} 은(는) 다른 화면의 자료에서 고르는 항목이다: 필드에 lookup:{{api:'{field['ref']['path']}',label:'{field['ref']['label']}'}} 를 주고, "
                     f"그리드에는 const x=useLookup({{api:'{field['ref']['path']}',label:'{field['ref']['label']}'}}) 의 x.name(row.{field['name']}) 로 이름을 보여 준다. "
                     f"저장할 때는 Number(values.{field['name']}) || null 을 보낸다(useLookup 은 '../framework' 에서 import).\n")
        return note
    note = (f"\n항목표(검사가 이 경로와 이름을 그대로 쓴다): {sheet['path']} / {rows}. JSON 필드 이름은 표의 영문 이름과 정확히 같게 한다. "
            "POST 는 201 과 저장된 자료, GET 은 목록 배열, PUT /{id} 는 200 과 수정된 자료, DELETE /{id} 는 204, "
            "필수 항목이 비어 있으면 400 으로 답한다(품목 API 와 같은 방식). 선택 항목의 열은 NULL 을 허용한다. "
            "숫자 항목은 INTEGER 열과 Integer 필드, 날짜 항목은 DATE 열과 java.time.LocalDate 필드(JSON 은 \"2026-01-15\" 형태), 그 밖은 글자다. "
            "보낸 모든 항목을 저장하고 응답과 목록에 그대로 돌려준다.\n")
    for field in refs:
        column = re.sub(r'(?<!^)(?=[A-Z])', '_', field['name']).lower()
        note += (f"{field['name']} 은(는) {field['ref']['path']} 자료의 id 를 담는다: 열은 {column} BIGINT, 엔티티 필드는 Long {field['name']}, "
                 "외래키(REFERENCES) 제약은 걸지 않는다.\n")
    return note


SHEET_PROMPT = '''새로 만들 등록 API의 항목표를 JSON 하나로만 답하라. 설명이나 코드 블록 표시는 쓰지 않는다.
형식: {"path": "/api/<영문 소문자 복수형>", "fields": [{"name": "<camelCase 영문>", "label": "<한국어 이름>", "required": true|false, "sample": "<예시 값 문자열>"}]}
규칙:
- 요청과 방향에 나온 항목만 넣는다. id 와 등록/수정자·일시는 프레임워크가 관리하므로 넣지 않는다.
- required 는 그 값 없이는 자료가 성립하지 않는 항목(보통 이름이나 코드 하나)에만 true 를 준다. 나머지는 false.
- sample 은 그 항목에 들어갈 만한 짧은 문자열 값이다. 수량·순서·금액 같은 숫자 항목은 "type": "number"(sample 은 "10" 같은 정수), 날짜 항목은 "type": "date"(sample 은 "2026-01-15")를 넣고, 글자 항목은 type 을 쓰지 않는다.
- 다른 등록 자료에서 고르는 항목(예: 사원의 부서)은 글자로 입력받지 않는다. name 을 <대상>Id 로 하고 "ref": {"path": "<대상 API 경로>", "label": "<그 자료에서 보여 줄 항목 name>"} 를 넣는다(sample 은 생략). 고를 수 있는 대상: %s
- 이미 있는 API 경로(%s)는 쓰지 않는다.
요청: %s
방향: %s'''


def ask_sheet(runner, taken, refs=None):
    task, approach = str(runner.args.task), os.environ.get('HARNESS_TASK_APPROACH', '').strip()
    refs = refs or {}
    targets = '; '.join(f"{path} (항목: {', '.join(item['name'] + '=' + item['label'] for item in sheet['fields'])})" for path, sheet in sorted(refs.items()))
    messages = [{'role': 'system', 'content': 'JSON only'},
                {'role': 'user', 'content': SHEET_PROMPT % (targets or '없음', ', '.join(sorted(taken)) or '없음', task, approach[:800] or '없음')}]
    error = ''
    for attempt in range(3):
        response = runner.ask(messages=list(messages), tools=[])
        text = str(response.get('content') or '')
        try:
            found = re.search(r'\{.*\}', text, re.S)
            return validate_sheet(json.loads(found.group(0)) if found else None, taken, refs, few_required=True)
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
        and re.search(r'API|엔티티|테이블|컨트롤러|entity|controller', task, re.I) \
        and not re.search(r'테스트|test|fixture|수정|변경|추가|삭제|제거|바꿔|바꾸|고쳐|고치|필드|항목|컬럼|열을|열 ', task, re.I)


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


UPDATE_PROMPT = '''이미 있는 등록 API를 고치는 요청이다. 아래는 지금의 항목표다. 요청을 반영해 고친 항목표 전체를 JSON 하나로만 답하라.
- path 는 바꾸지 않는다. 요청이 말하지 않은 항목의 name/label/required 는 그대로 둔다.
- 요청이 어떤 항목을 선택 항목으로(또는 필수로) 바꾸라고 하면 그 항목의 required 만 바꾼다. 항목 추가·삭제 요청이면 그만큼만 고친다.
지금의 항목표: %s
요청: %s
방향(참고용, 틀릴 수 있음): %s'''


def _matching_sheet(root, task):
    """The one saved sheet of an existing API this task talks about (by the resource's Korean name or its path noun)."""
    apis, found = existing_api_paths(root), []
    for file in (SHEETS / Path(root).name).glob('*.json'):
        try:
            raw = json.loads(file.read_text(encoding='utf-8'))
            sheet = validate_sheet(raw)
        except (ValueError, OSError):
            continue
        if sheet['path'] not in apis:
            continue
        words = [word for word in re.split(r'\s+', str(raw.get('task', ''))) if word and word not in ('API', '등록', '화면', '관리')][:1]
        noun = sheet['path'].rsplit('/', 1)[-1]
        if any(word in task for word in words) or noun in task.lower() or noun.rstrip('s') in task.lower():
            found.append(sheet)
    return found[0] if len(found) == 1 else None


def ask_updated_sheet(runner, current):
    task, approach = str(runner.args.task), os.environ.get('HARNESS_TASK_APPROACH', '').strip()
    messages = [{'role': 'system', 'content': 'JSON only'},
                {'role': 'user', 'content': UPDATE_PROMPT % (json.dumps(current, ensure_ascii=False), task, approach[:600] or '없음')}]
    error = ''
    for attempt in range(3):
        response = runner.ask(messages=list(messages), tools=[])
        text = str(response.get('content') or '')
        try:
            found = re.search(r'\{.*\}', text, re.S)
            sheet = validate_sheet(json.loads(found.group(0)) if found else None)
            if sheet['path'] != current['path']:
                raise ValueError(f"path must stay {current['path']}")
            return sheet
        except (ValueError, AttributeError) as problem:
            error = str(problem)
            runner.h.log_event('requirement.sheet_rejected', {'attempt': attempt + 1, 'error': error[:300]})
            messages = messages[:2] + [{'role': 'assistant', 'content': text[:2000]},
                                       {'role': 'user', 'content': f'고쳐서 JSON 전체를 다시 답하라: {error}'}]
    raise ValueError('updated field sheet unavailable: ' + error)


def _baseline(runner, criteria):
    """Run the API checks on the code as it is now: which fail, and why (the observed answers and root causes)."""
    import uuid
    import backend_contract_gate
    out = Path(os.environ.get('TMPDIR', '/tmp')) / ('standard-baseline-' + uuid.uuid4().hex)
    report = backend_contract_gate.verify(runner.h.checker, criteria, str(out))
    return [result for result in report.get('results', []) if result.get('status') != 'passed']


def resource_files(root, path):
    """The files that make up an existing registration API: controller, entity, repository, the migration creating its table."""
    root, files = Path(root), []
    for controller in (root / 'backend/src/main/java').rglob('*Controller.java'):
        if f'@RequestMapping("{path}")' not in controller.read_text(encoding='utf-8', errors='replace'):
            continue
        stem = controller.stem[:-len('Controller')]
        for name in (controller.name, stem + '.java', stem + 'Repository.java'):
            if (controller.parent / name).is_file():
                files.append((controller.parent / name).relative_to(root).as_posix())
        entity = controller.parent / (stem + '.java')
        table = re.search(r'@Table\s*\(\s*name\s*=\s*"([^"]+)"', entity.read_text(encoding='utf-8', errors='replace')) if entity.is_file() else None
        if table:
            creating = [m for m in sorted((root / 'backend/src/main/resources/db/migration').glob('V*.sql'),
                                          key=lambda item: int(re.match(r'V(\d+)', item.name).group(1)))
                        if re.search(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"?' + re.escape(table.group(1)) + r'\b', m.read_text(encoding='utf-8', errors='replace'), re.I)]
            if creating:
                files.append(creating[-1].relative_to(root).as_posix())  # the latest one is the table as it is now
        break
    return files


def next_migration(root):
    versions = [int(m.group(1)) for p in (Path(root) / 'backend/src/main/resources/db/migration').glob('V*.sql') for m in [re.match(r'V(\d+)__', p.name)] if m]
    return max(versions, default=0) + 1


def likely_fix(root, failing):
    """A concrete suggestion when the observed root cause has an obvious remedy."""
    text = ' '.join(str(f.get('reason')) for f in failing)
    match = re.search(r'null value in column "(\w+)" of relation "(\w+)" violates not-null constraint', text)
    if match:
        column, table = match.groups()
        return (f'가장 가능성 높은 수정: {table}.{column} 열이 NULL 을 허용하지 않는 것이 원인이다. 새 마이그레이션 파일 '
                f'backend/src/main/resources/db/migration/V{next_migration(root)}__{table}_{column}_optional.sql 을 write_file 로 만들고 내용은 '
                f'"ALTER TABLE {table} ALTER COLUMN {column} DROP NOT NULL;" 로 한다.\n')
    return ''


def screen_api(root, title):
    """(screen file, API path) of the existing screen with this title, from its meta and its apiFetch calls."""
    for path in sorted((Path(root) / 'frontend/src/screens').glob('*.tsx')):
        source = path.read_text(encoding='utf-8', errors='replace')
        meta = re.search(r'\bexport\s+const\s+meta\s*=\s*\{([^{}]{0,1000})\}', source)
        if not meta or not re.search(r"\btitle\s*:\s*(['\"])" + re.escape(title) + r'\1', meta.group(1)):
            continue
        api = re.search(r'apiFetch\(\s*[`\'"](/api/[a-z][a-z0-9-]*)', source)
        return path.relative_to(root).as_posix(), api.group(1) if api else None
    return None, None


def _screen_baseline(runner, title, criteria):
    """Run the screen checks on the screen as it is now (read-only, in a real browser); the ones that fail."""
    import subprocess
    import uuid
    data = {'open_screen': title, 'contract': {'criteria': criteria, 'requirements': []},
            'preview_url': os.environ.get('HARNESS_VERIFICATION_PREVIEW_URL') or os.environ.get('HARNESS_PREVIEW_URL') or '', 'api_url': '',
            'output_dir': str(Path(os.environ.get('TMPDIR', '/tmp')) / ('standard-screen-baseline-' + uuid.uuid4().hex)),
            'allow_browser_writes': False, 'allow_api_writes': False}
    script = Path(__file__).resolve().with_name('react_layout_inspector.cjs')
    done = subprocess.run(['node', str(script)], input=json.dumps(data), text=True, capture_output=True, timeout=180)
    return [result for result in json.loads(done.stdout).get('results', []) if result.get('status') != 'passed']


def build(runner, new_screen_reference=''):
    """(raw contract, kind) for a standard task, else None. Sets runner._field_sheet_note for the author's brief."""
    if os.environ.get('HARNESS_STANDARD_CONTRACT') == '0':
        return None
    root, task = runner.h.workspace.root, str(runner.args.task)
    if '\n' in task.strip():
        return None  # several request clauses: not the plain standard case
    import requirement_contract
    base = {'version': 1, 'task': task, 'requirements': requirement_contract.requirements(task)}
    modes = set(getattr(runner, 'modes', ()) or ())
    about_existing = _matching_sheet(root, task) if 'backend' in modes and not ({'frontend', 'framework'} & modes) else None
    # A request that names a resource which already has an API changes that API; it never creates another one.
    if _is_new_api(runner) and not about_existing:
        refs = known_refs(root)
        sheet = ask_sheet(runner, existing_api_paths(root), refs)
        criteria = api_criteria(sheet, refs)
        file = _sheet_file(root, sheet['path'])
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(dict(sheet, task=task, saved_at=time.strftime('%Y-%m-%dT%H:%M:%S')), ensure_ascii=False, indent=1), encoding='utf-8')
        import schema_state
        table = sheet['path'].rsplit('/', 1)[-1].replace('-', '_')
        runner._field_sheet_note = (sheet_note(sheet) + f"새 테이블 {table} 을(를) 새 V{next_migration(root)}__ 마이그레이션에서 CREATE TABLE 로 만든다. "
                                    + schema_state.note(root) + '\n')
        return dict(base, criteria=criteria), 'standard-api', sheet
    if 'backend' in modes and not ({'frontend', 'framework'} & modes):
        # A change to an existing registration API: the same standard checks, for the sheet as the request wants it.
        # They are used only if at least one fails on the current code - then they describe the fix; otherwise the
        # request is about something the standard checks do not cover and the model-written contract is used.
        current = about_existing
        if current:
            sheet = ask_updated_sheet(runner, current)
            criteria = api_criteria(sheet, known_refs(root))
            failing = _baseline(runner, criteria)
            runner.h.log_event('requirement.standard_baseline', {'path': sheet['path'], 'failing': [f.get('id') for f in failing], 'model_calls': 0})
            if failing and not all(f.get('status') == 'unverified' for f in failing):
                file = _sheet_file(root, sheet['path'])
                file.write_text(json.dumps(dict(sheet, task=json.loads(file.read_text(encoding='utf-8')).get('task', task), saved_at=time.strftime('%Y-%m-%dT%H:%M:%S')),
                                           ensure_ascii=False, indent=1), encoding='utf-8')
                facts = '\n'.join(f"- {f.get('id')}: {str(f.get('reason'))[:600]}" for f in failing[:4])
                added = [field for field in sheet['fields'] if field['name'] not in {old['name'] for old in current['fields']}]
                files = resource_files(root, sheet['path'])
                if isinstance(getattr(runner, 'read', None), set):
                    runner.read.update(files)  # given to the author as CURRENT FILE blocks
                runner._field_sheet_note = (sheet_note(sheet) + '지금 코드에서 실패하는 검사와 관찰된 원인(이것을 고친다; 방향 설명보다 이 관찰이 정확하다):\n' + facts
                                            + '\n' + likely_fix(root, failing)
                                            + (('새로 추가할 항목: ' + ', '.join(f"{field['name']}({field['label']})" for field in added) + f". 이 API({sheet['path']})의 기존 테이블에 열을 더하고(ALTER TABLE ... ADD COLUMN), "
                                                '엔티티·요청 본문·저장 코드에 같은 이름으로 반영한다. 새 API나 새 테이블을 만들지 않는다.\n') if added else '')
                                            + f'이미 적용된 마이그레이션은 고칠 수 없으므로 테이블 변경은 새 V{next_migration(root)}__ 마이그레이션(ALTER TABLE)으로 한다. '
                                            + ('관련 파일은 CURRENT FILE 로 이미 주어져 있다: ' + ', '.join(files) + '. 다시 읽지 말고 바로 고친다.\n' if files else '\n'))
                return dict(base, criteria=criteria), 'standard-api-change', sheet
        return None
    if not new_screen_reference and 'backend' not in modes and ({'frontend', 'framework'} & modes):
        # A change to an existing registration screen: the standard screen checks for the sheet as the request wants
        # it, used only if some fail on the screen as it is now (otherwise the request is about something else).
        from task_sources import task_screen_title
        title = task_screen_title(root, task)
        file, api = screen_api(root, title) if title else (None, None)
        current = known_refs(root).get(api) if api else None
        if current:
            sheet = ask_updated_sheet(runner, current)
            description = {c['id']: c['description'] for c in screen_criteria(sheet)}
            criteria = screen_criteria(sheet)
            failing = _screen_baseline(runner, title, criteria)
            runner.h.log_event('requirement.standard_baseline', {'screen': title, 'failing': [f.get('id') for f in failing], 'model_calls': 0})
            if failing and not all(f.get('status') == 'unverified' for f in failing):
                sheet_file = _sheet_file(root, sheet['path'])
                sheet_file.write_text(json.dumps(dict(sheet, task=json.loads(sheet_file.read_text(encoding='utf-8')).get('task', task),
                                                      saved_at=time.strftime('%Y-%m-%dT%H:%M:%S')), ensure_ascii=False, indent=1), encoding='utf-8')
                if isinstance(getattr(runner, 'read', None), set) and file:
                    runner.read.add(file)
                facts = '\n'.join(f"- {f.get('id')} {description.get(f.get('id'), '')}" for f in failing[:8])
                runner._field_sheet_note = (sheet_note(sheet, screen=True) + f'고칠 화면 파일은 {file} 하나다. 지금 화면에서 통과하지 못하는 검사(이것을 고친다):\n' + facts
                                            + '\n화면 파일의 행 타입, toRow, 필드 정의(editFields), 그리드 열(gridColumns), 저장 payload 를 항목표에 맞게 고친다. '
                                            '이 파일은 짧으므로 AST 편집 대신 고친 파일 전체를 write_file 로 한 번에 다시 쓴다(지금 내용은 CURRENT FILE 로 주어져 있다). '
                                            '항목 하나를 더할 때는 위 다섯 곳 모두에 넣어야 타입 오류가 나지 않는다. 다른 파일은 건드리지 않는다.\n')
                return dict(base, criteria=criteria), 'standard-screen-change', sheet
        return None
    if new_screen_reference and 'backend' not in (getattr(runner, 'modes', ()) or ()):
        sheet = _unused_sheet(root)
        if sheet:
            runner._field_sheet_note = sheet_note(sheet, screen=True)
            return dict(base, criteria=screen_criteria(sheet)), 'standard-screen', sheet
    return None
