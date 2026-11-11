"""A request in plain words -> a definition the framework accepts.

The model writes the definition; the framework judges it. A refusal comes back to the model in the
framework's own words. The prompt is built from what the framework says it can do, so a new field
type or screen type added to the framework is available here without changing this file.
"""
import json
import re

import llm

PROMPT = '''업무 시스템의 화면을 "정의"로 만든다. 코드를 쓰지 않는다. 아래 요청을 읽고 정의를 JSON 하나로만 답하라(설명, 코드 블록 표시 없이).

형식:
{"action": "create" 또는 "change", "key": "<자료 이름: 영문 소문자, 단수형, 예 customer>", "definition": {"title": "<화면 이름>", "keywords": ["<찾을 때 칠 낱말>", ...],
 "fields": [{"name": "<camelCase 영문>", "label": "<화면에 보이는 한국어 이름>", "type": "<항목 종류>", "required": true|false, "search": true|false, ...}]}}

프레임워크가 지원하는 것:
%(capabilities)s

이미 있는 자료(정의):
%(existing)s

규칙:
- 요청이 이미 있는 자료를 고치는 것이면 action 은 "change", key 는 그 자료의 key 이고, definition 에는 고친 뒤의 전체를 적는다(요청이 말하지 않은 항목은 그대로 둔다).
- 새 자료면 action 은 "create" 이고 key 는 이미 있는 key 와 겹치지 않게 한다.
- 요청이 항목을 정해 주지 않았으면 그 업무에서 흔히 쓰는 항목으로 정한다(5~8개).
- required 는 그 값 없이는 자료가 성립하지 않는 항목(보통 이름이나 코드)에만 true. 적어도 하나의 글자(text) 항목은 required 여야 한다.
- search 는 조회 조건으로 쓸 항목(1~3개)에 true.
- 다른 자료에서 고르는 항목(예: 사원의 부서)은 글자로 받지 말고 type "ref" 와 "ref": {"entity": "<그 자료의 key>", "label": "<보여 줄 항목 name>"} 로 한다. 이미 있는 자료만 가리킬 수 있다.
- 단위·구분·상태처럼 정해진 값 중에서 고르는 항목은 type "code" 와 "codeGroup": "<공통 코드 그룹>" 으로 한다. 있는 그룹만 쓴다. 맞는 그룹이 없으면 글자(text)로 둔다.
- id 와 등록·수정자/일시는 프레임워크가 관리하므로 넣지 않는다.

요청: %(request)s'''


def _existing(framework):
    lines = []
    for item in framework.definitions():
        definition = item['definition']
        fields = ', '.join(f"{field['name']}({field['label']}, {field['type']}{', 필수' if field['required'] else ''})" for field in definition['fields'])
        lines.append(f"- key {item['key']} / 화면 이름 {definition['title']} / 항목: {fields}")
    return '\n'.join(lines) or '(없음)'


def _json(text):
    found = re.search(r'\{.*\}', text, re.S)
    if not found:
        raise ValueError('JSON 객체가 없다')
    return json.loads(found.group(0))


def write(request, framework, record_to, trial_prefix='trial_'):
    """Returns {'action', 'key', 'definition'} that the framework has accepted (as a trial draft)."""
    capabilities = framework.capabilities()
    shown = {key: capabilities[key] for key in ('screenTypes', 'fieldTypes', 'builtInRules', 'codeGroups') if key in capabilities}
    messages = [{'role': 'system', 'content': 'JSON only'},
                {'role': 'user', 'content': PROMPT % {'capabilities': json.dumps(shown, ensure_ascii=False, indent=1), 'existing': _existing(framework), 'request': request}}]
    known = {item['key'] for item in framework.definitions()}
    error = ''
    for attempt in range(1, 4):
        answer = llm.ask(messages, record_to, f'define-{attempt}')
        try:
            proposal = _json(answer)
            action, key, definition = proposal.get('action'), proposal.get('key'), proposal.get('definition')
            if action not in ('create', 'change') or not isinstance(key, str) or not isinstance(definition, dict):
                raise ValueError('action(create|change), key, definition 이 모두 있어야 한다')
            if action == 'change' and key not in known:
                raise ValueError(f'change 인데 {key} 라는 자료가 없다. 있는 자료: {sorted(known)}')
            if action == 'create' and key in known:
                raise ValueError(f'{key} 는 이미 있다. 그 자료를 고치는 요청이면 action 을 change 로, 새 자료면 다른 key 를 쓴다')
            # The framework is the judge: the definition is saved as a trial draft; a refusal is its message.
            framework.save_definition(trial_prefix + key, definition, 'DRAFT')
            return {'action': action, 'key': key, 'definition': definition}
        except Exception as problem:  # a refusal of any kind goes back to the model once more
            error = str(problem)
            messages = messages[:2] + [{'role': 'assistant', 'content': answer[:3000]},
                                       {'role': 'user', 'content': f'받아들여지지 않았다: {error}\n고쳐서 JSON 전체를 다시 답하라.'}]
    raise RuntimeError('정의를 만들지 못했습니다: ' + error)
