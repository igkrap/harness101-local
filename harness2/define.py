"""A request in plain words -> a definition the framework accepts.

The model writes the definition; the framework judges it. A refusal comes back to the model in the
framework's own words. The prompt is built from what the framework says it can do, so a new field
type or screen type added to the framework is available here without changing this file.
"""
import json
import re

import llm

PROMPT = '''업무 시스템의 화면을 "정의"로 만든다. 코드를 쓰지 않는다. 아래 요청을 읽고 답을 JSON 하나로만 하라(설명, 코드 블록 표시 없이).

답의 형식: {"action": "create" 또는 "change", "key": "<자료 이름: 영문 소문자, 단수형, 예 customer, sales_order>", "definition": <정의>}

프레임워크 안내 (정의의 모양과 쓸 수 있는 것):
%(guide)s
프레임워크가 지원하는 목록:
%(capabilities)s

이미 있는 자료(정의):
%(existing)s

규칙:
- 요청이 이미 있는 자료를 고치는 것이면 action 은 "change", key 는 그 자료의 key 이고, definition 에는 고친 뒤의 전체를 적는다(요청이 말하지 않은 부분은 그대로 둔다).
- 새 자료면 action 은 "create" 이고 key 는 이미 있는 key 와 겹치지 않게 한다.
- 요청이 항목을 정해 주지 않았으면 그 업무에서 흔히 쓰는 항목으로 정한다(머리 5~8개, 명세 3~5개).
- required 는 그 값 없이는 자료가 성립하지 않는 항목에만 true.
- search 는 조회 조건으로 쓸 머리 항목(1~3개)에 true.
- 다른 자료에서 고르는 항목(거래처, 품목, 부서 ...)은 글자로 받지 말고 ref 로 한다. 이미 있는 자료만 가리킬 수 있고, ref.label 과 fill 의 값은 그 자료에 실제로 있는 항목 name 이어야 한다(위 '이미 있는 자료' 참고).
- 정해진 값 중에서 고르는 항목은 code 로 하되 있는 공통 코드 그룹만 쓴다. 맞는 그룹이 없으면 글자(text)로 둔다.
- "~하면 ~못 하게" 같은 요청은 rules 로 적는다. 규칙이 가리키는 자료와 항목은 이미 있어야 한다.
- id, 상태, 등록·수정자/일시는 프레임워크가 관리하므로 항목으로 넣지 않는다(상태는 definition.status 로).
- 정의로 할 수 없는 요청이면 {"action": "other", "reason": "<이유 한 줄>"} 로만 답한다. 해당하는 경우: 아래 '코드로 만든 화면'을 고치는 요청, 로그인·메뉴·권한·디자인 같은 시스템 요청, 집계·보고서.

코드로 만든 화면(정의가 아니라서 여기서 고칠 수 없음): %(code_screens)s

요청: %(request)s'''


def _fields(fields):
    def one(field):
        extra = field['type'] + (f"→{field['ref']['entity']}" if field.get('ref') else '') + (', 필수' if field['required'] else '') \
            + (', 계산' if field.get('formula') or field.get('sum') else '')
        return f"{field['name']}({field['label']}, {extra})"
    return ', '.join(one(field) for field in fields)


def _existing(framework):
    lines = []
    for item in framework.definitions():
        definition = item['definition']
        text = f"- key {item['key']} / {definition.get('type', 'master')} / 화면 이름 {definition['title']} / 항목: {_fields(definition['fields'])}"
        if definition.get('lines'):
            text += f" / 명세({definition['lines']['label']}): {_fields(definition['lines']['fields'])}"
        if definition.get('status'):
            text += ' / 상태: ' + ', '.join(f"{value['code']}={value['label']}" for value in definition['status']['values']) \
                + ' / 동작: ' + ', '.join(f"{action['name']}({action['label']})" for action in definition['status']['actions'])
        if definition.get('rules'):
            text += ' / 규칙: ' + '; '.join(rule['message'] for rule in definition['rules'])
        lines.append(text)
    return '\n'.join(lines) or '(없음)'


def code_screens():
    """Titles of the screens that exist as code files (they are changed by the code route, not by definitions)."""
    from pathlib import Path
    titles = []
    for path in sorted((Path(__file__).resolve().parents[1] / 'local-only/frontend/src/screens').glob('*.tsx')):
        found = re.search(r"title:\s*'([^']+)'", path.read_text(encoding='utf-8', errors='replace'))
        if found and found.group(1) != '홈':
            titles.append(found.group(1))
    return titles


def _json(text):
    found = re.search(r'\{.*\}', text, re.S)
    if not found:
        raise ValueError('JSON 객체가 없다')
    return json.loads(found.group(0))


def complete(definition):
    """What the model may leave out, written out: the rest of the harness reads every field the same way."""
    groups = [definition.get('fields') or []] + ([definition['lines'].get('fields') or []] if isinstance(definition.get('lines'), dict) else [])
    for fields in groups:
        for field in fields:
            if isinstance(field, dict):
                field.setdefault('type', 'text')
                field.setdefault('required', False)
                field.setdefault('search', False)
    return definition


def write(request, framework, record_to, trial_prefix='trial_'):
    """Returns {'action', 'key', 'definition'} that the framework has accepted (as a trial draft)."""
    capabilities = framework.capabilities()
    shown = {key: capabilities[key] for key in ('screenTypes', 'fieldTypes', 'builtInRules', 'ruleTypes', 'codeGroups') if key in capabilities}
    messages = [{'role': 'system', 'content': 'JSON only'},
                {'role': 'user', 'content': PROMPT % {'guide': capabilities.get('guide', ''), 'capabilities': json.dumps(shown, ensure_ascii=False, indent=1), 'existing': _existing(framework), 'request': request,
                                                      'code_screens': ', '.join(code_screens()) or '(없음)'}}]
    known = {item['key'] for item in framework.definitions()}
    error = ''
    for attempt in range(1, 4):
        answer = llm.ask(messages, record_to, f'define-{attempt}')
        try:
            proposal = _json(answer)
            if proposal.get('action') == 'other':
                return {'action': 'other', 'reason': str(proposal.get('reason') or '')[:300]}
            action, key, definition = proposal.get('action'), proposal.get('key'), proposal.get('definition')
            if action not in ('create', 'change') or not isinstance(key, str) or not isinstance(definition, dict):
                raise ValueError('action(create|change), key, definition 이 모두 있어야 한다')
            if action == 'change' and key not in known:
                raise ValueError(f'change 인데 {key} 라는 자료가 없다. 있는 자료: {sorted(known)}')
            if action == 'create' and key in known:
                raise ValueError(f'{key} 는 이미 있다. 그 자료를 고치는 요청이면 action 을 change 로, 새 자료면 다른 key 를 쓴다')
            # The framework is the judge: the definition is saved as a trial draft; a refusal is its message.
            framework.save_definition(trial_prefix + key, {name: value for name, value in definition.items() if name != 'rules'}, 'DRAFT')
            return {'action': action, 'key': key, 'definition': complete(definition)}
        except Exception as problem:  # a refusal of any kind goes back to the model once more
            error = str(problem)
            messages = messages[:2] + [{'role': 'assistant', 'content': answer[:3000]},
                                       {'role': 'user', 'content': f'받아들여지지 않았다: {error}\n고쳐서 JSON 전체를 다시 답하라.'}]
    raise RuntimeError('정의를 만들지 못했습니다: ' + error)
