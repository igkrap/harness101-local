"""A request in plain words -> a definition the framework accepts.

The model writes the definition; the framework judges it. A refusal comes back to the model in the
framework's own words. The prompt is built from what the framework says it can do, so a new field
type or screen type added to the framework is available here without changing this file.
"""
import json
import re

import llm

PROMPT = '''업무 시스템의 화면을 "정의"로 만든다. 코드를 쓰지 않는다. 아래 요청을 읽고 답을 JSON 하나로만 하라(설명, 코드 블록 표시 없이).

답의 형식: {"action": "create" 또는 "change", "key": "<자료 이름: 영문 소문자·밑줄, 30자 이내, 예 customer, sales_order, order_balance_summary>", "definition": <정의>}

프레임워크 안내 (정의의 모양과 쓸 수 있는 것):
%(guide)s
프레임워크가 지원하는 목록:
%(capabilities)s

이미 있는 자료(정의):
%(existing)s

규칙:
- 요청이 이미 있는 자료를 고치는 것이면 {"action": "change", "key": "<그 자료의 key>"} 까지만 답한다(그러면 그 자료의 정의 전체를 받아서 고치게 된다).
- 새 자료면 action 은 "create" 이고 key 는 이미 있는 key 와 겹치지 않게 한다.
- 현황·합계·통계·차트처럼 이미 있는 자료를 모아서 보는 요청은 새 자료를 만들지 말고 집계 화면(summary)으로 한다. 모을 자료는 이미 있어야 한다.
- 현황판·대시보드처럼 차트만 모아 보는 요청은 dashboard 로 한다. 패널은 이미 있는 집계 화면만 가리킬 수 있으므로, 맞는 집계 화면이 있으면 그것을 쓰고 없으면 먼저 집계 화면을 만들어 달라고 한다(other 로 이유를 답한다).
- 잔량·미출하·미입고·재고처럼 한 자료에서 다른 자료를 뺀 나머지는 compare minus 로, 처리 기간·소요 일수는 values 의 between 으로, 누계는 cumulative 로 한다.
- 계획 대비·목표 대비·달성률은 compare plan 으로, 전월 대비·전년 대비·증감은 compare previous 로, 비중·점유율은 share 로, 순위·상위 N 은 top 으로 한다. 계획을 담은 자료가 없으면 이 요청으로는 그 등록 화면(예: 수주 계획 등록)부터 만든다.
- 요청이 항목을 정해 주지 않았으면 그 업무에서 흔히 쓰는 항목으로 정한다(5~8개, 줄 표가 있으면 줄 항목 3~5개).
- 번호(serial), 줄 표(lines), 상태(status)는 그 업무에 실제로 필요할 때만 붙인다. 요청이 개수나 범위를 말하면("하나만", "0~100") 그대로 적는다.
- required 는 그 값 없이는 자료가 성립하지 않는 항목에만 true.
- search 는 조회 조건으로 쓸 항목(1~3개, 줄 항목 제외)에 true.
- 다른 자료에서 고르는 항목(거래처, 품목, 부서 ...)은 글자로 받지 말고 ref 로 한다. 이미 있는 자료만 가리킬 수 있고, ref.label 과 fill 의 값은 그 자료에 실제로 있는 항목 name 이어야 한다(위 '이미 있는 자료' 참고).
- 정해진 값 중에서 고르는 항목은 code 로 하되 있는 공통 코드 그룹만 쓴다. 맞는 그룹이 없으면 글자(text)로 둔다.
- "~하면 ~못 하게" 같은 요청은 rules 로 적는다. 규칙이 가리키는 자료와 항목은 이미 있어야 한다.
- 한 건 안에서 두 값을 견주는 조건(날짜 순서 등)은 checks 로, 다른 자료의 수량을 넘지 못하게 하는 것(초과 출하·재고 부족 방지)은 limits 로, "~하면 자동으로 ~된다/만들어진다"는 effects 로 적는다. 그 규칙은 저장이 거절되어야 하는 자료, 일이 시작되는 자료의 정의에 붙인다(출하 수량 제한은 출하에, 수주 확정 시 출하 생성은 수주에).
- id, 상태, 등록·수정자/일시는 프레임워크가 관리하므로 항목으로 넣지 않는다(상태는 definition.status 로).
- 정의로 할 수 없는 요청이면 {"action": "other", "reason": "<이유 한 줄>"} 로만 답한다. 해당하는 경우: 아래 '코드로 만든 화면'을 고치는 요청, 로그인·메뉴·권한·디자인 같은 시스템 요청, 프레임워크 안내에 없는 동작.

코드로 만든 화면(정의가 아니라서 여기서 고칠 수 없음): %(code_screens)s

요청: %(request)s'''


def trial_name(key, prefix='trial_'):
    """The key of a trial copy: the prefix and the key, cut to the framework's 40 characters."""
    return (prefix + key)[:40]


def real(framework, trial_prefix='trial_'):
    """The definitions there really are: a trial copy left by an interrupted run is not one of them."""
    return [item for item in framework.definitions() if not item['key'].startswith(trial_prefix)]


def _fields(fields):
    def one(field):
        extra = field['type'] + (f"→{field['ref']['entity']}" if field.get('ref') else '') + (', 필수' if field['required'] else '') \
            + (', 계산' if field.get('formula') or field.get('sum') else '')
        return f"{field['name']}({field['label']}, {extra})"
    return ', '.join(one(field) for field in fields)


def _existing(framework):
    lines = []
    for item in real(framework):
        definition = item['definition']
        text = f"- key {item['key']} / 화면 이름 {definition['title']} / 항목: {_fields(definition['fields'])}"
        if definition.get('lines'):
            text += f" / 줄 표({definition['lines']['label']}): {_fields(definition['lines']['fields'])}"
        if definition.get('status'):
            text += ' / 상태: ' + ', '.join(f"{value['code']}={value['label']}" for value in definition['status']['values']) \
                + ' / 동작: ' + ', '.join(f"{action['name']}({action['label']})" for action in definition['status']['actions'])
        if definition.get('rules'):
            text += ' / 규칙: ' + '; '.join(rule['message'] for rule in definition['rules'])
        for part, label in (('checks', '비교 규칙'), ('limits', '한도')):
            if definition.get(part):
                text += f' / {label}: ' + '; '.join(rule['message'] for rule in definition[part])
        if definition.get('effects'):
            text += ' / 자동 처리: ' + '; '.join(f"{effect['on']}→" + (f"{effect['create']['entity']} 생성" if effect.get('create') else f"{effect['act']['via']}.{effect['act']['action']}") for effect in definition['effects'])
        if definition.get('dashboard'):
            text = f"- key {item['key']} / 화면 이름 {definition['title']} / 현황판: 패널 " + ', '.join(f"{panel['summary']}({panel['chart']})" for panel in definition['dashboard']['panels'])
        if definition.get('summary'):
            part = definition['summary']
            text = f"- key {item['key']} / 화면 이름 {definition['title']} / 집계 화면: {part['entity']}" + (' 의 줄 표' if part.get('lines') else '') + ' 을(를) ' \
                + ', '.join(group['field'] + (f"({group['by']})" if group.get('by') else '') for group in part['groupBy']) + ' (으)로 묶어 ' \
                + ', '.join(f"{value['label']}={value['op']}" + (f"({value['field']})" if value.get('field') else '') for value in part['values']) \
                + (f" / 차트 {part['chart']['type']}" if part.get('chart') else '') \
                + (f" / 계획 대비({part['compare']['entity']})" if (part.get('compare') or {}).get('type') == 'plan' else f" / {part['compare'].get('balance')}(− {part['compare']['entity']})" if (part.get('compare') or {}).get('type') == 'minus' else f" / 전기 대비({part['compare']['by']})" if part.get('compare') else '') \
                + (' / 구성비' if part.get('share') else '') + (f" / 상위 {part['top']}" if part.get('top') else '')
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
    definition.setdefault('fields', [])      # a summary screen has none of its own
    groups = [definition.get('fields') or []] + ([definition['lines'].get('fields') or []] if isinstance(definition.get('lines'), dict) else [])
    for fields in groups:
        for field in fields:
            if isinstance(field, dict):
                field.setdefault('type', 'text')
                field.setdefault('required', False)
                field.setdefault('search', False)
    return definition


def clean(definition):
    """A stored definition as one would write it: no key, no empty or default entries."""
    def field(item):
        out = {name: value for name, value in item.items() if not (value is None or value is False or value == [] or value == {}) or name == 'required'}
        if isinstance(out.get('ref'), dict):
            out['ref'] = {name: value for name, value in out['ref'].items() if value is not None}
        return out
    out = {name: value for name, value in definition.items() if name not in ('key', 'type') and value not in (None, [], {})}
    out['fields'] = [field(item) for item in definition.get('fields') or []]
    if definition.get('lines'):
        out['lines'] = {name: value for name, value in dict(definition['lines'], fields=[field(item) for item in definition['lines']['fields']]).items()
                        if value is not None and not (name == 'min' and value == 1)}
    return out


def differences(old, new):
    """What differs between two definitions, in plain words: (everything, the part that went missing)."""
    old, new = clean(complete(json.loads(json.dumps(old)))), clean(complete(json.loads(json.dumps(new))))
    notes, lost = [], []

    def note(text, missing=False):
        notes.append(text)
        if missing:
            lost.append(text)
    if old.get('title') != new.get('title'):
        note(f"화면 이름: {old.get('title')} → {new.get('title')}")
    for word in old.get('keywords', []):
        if word not in new.get('keywords', []):
            note(f'찾는 낱말 "{word}" 이(가) 없어짐', True)

    def compare(where, before, after):
        before, after = {item['name']: item for item in before}, {item['name']: item for item in after}
        for name, item in before.items():
            if name not in after:
                note(f"{where} 항목 {item['label']}({name}) 이(가) 없어짐", True)
                continue
            for part in sorted(set(item) | set(after[name])):
                if item.get(part) != after[name].get(part):
                    gone = part in item and part not in after[name]
                    note(f"{where} 항목 {item['label']} 의 {part}: {json.dumps(item.get(part), ensure_ascii=False)} → {json.dumps(after[name].get(part), ensure_ascii=False)}", gone)
        for name, item in after.items():
            if name not in before:
                note(f"{where} 항목 {item['label']}({name}) 이(가) 추가됨")
    compare('위쪽' if old.get('lines') or new.get('lines') else '', old['fields'], new['fields'])
    if old.get('lines') or new.get('lines'):
        if not new.get('lines'):
            note('줄 표가 통째로 없어짐', True)
        else:
            compare('줄', (old.get('lines') or {}).get('fields', []), new['lines']['fields'])
            for part in ('min', 'max'):
                if old.get('lines') and old['lines'].get(part) != new['lines'].get(part):
                    note(f"줄 수 {part}: {old['lines'].get(part)} → {new['lines'].get(part)}")
    before, after = old.get('status') or {}, new.get('status') or {}
    if before and not after:
        note('상태와 동작이 통째로 없어짐', True)
    elif before != after:
        for kind, name, label in (('values', 'code', '상태'), ('actions', 'name', '동작')):
            was, now = {item[name]: item for item in before.get(kind, [])}, {item[name]: item for item in after.get(kind, [])}
            for code, item in was.items():
                if code not in now:
                    note(f"{label} {item['label']} 이(가) 없어짐", True)
                elif item != now[code]:
                    note(f"{label} {item['label']} 이(가) 바뀜: {json.dumps(item, ensure_ascii=False)} → {json.dumps(now[code], ensure_ascii=False)}")
            for code, item in now.items():
                if code not in was:
                    note(f"{label} {item['label']} 이(가) 추가됨")
        if sorted(before.get('locked', [])) != sorted(after.get('locked', [])):
            note(f"수정·삭제를 막는 상태: {before.get('locked', [])} → {after.get('locked', [])}", bool(set(before.get('locked', [])) - set(after.get('locked', []))))
        if before.get('initial') != after.get('initial') and before:
            note(f"처음 상태: {before.get('initial')} → {after.get('initial')}")
    before, after = old.get('summary') or {}, new.get('summary') or {}
    if before or after:
        for part, name, label in (('groupBy', 'field', '묶는 기준'), ('values', 'label', '계산 열')):
            was, now = {item[name]: item for item in before.get(part, [])}, {item[name]: item for item in after.get(part, [])}
            for item in was:
                if item not in now:
                    note(f'{label} {item} 이(가) 없어짐', True)
                elif {k: v for k, v in was[item].items() if v is not None} != {k: v for k, v in now[item].items() if v is not None}:
                    note(f'{label} {item} 이(가) 바뀜: {json.dumps(was[item], ensure_ascii=False)} → {json.dumps(now[item], ensure_ascii=False)}')
            for item in now:
                if item not in was:
                    note(f'{label} {item} 이(가) 추가됨')
        for item in before.get('filters', []):
            if item not in after.get('filters', []):
                note(f'조회 조건 {item} 이(가) 없어짐', True)
        for item in after.get('filters', []):
            if item not in before.get('filters', []):
                note(f'조회 조건 {item} 이(가) 추가됨')
        for part, label in (('entity', '모으는 자료'), ('lines', '줄 표를 모으는지'), ('chart', '차트'), ('compare', '견주는 대상(계획·전기·빼는 자료)'), ('share', '구성비'), ('top', '순위'), ('cumulative', '누계')):
            if (before.get(part) or None) != (after.get(part) or None):
                note(f'{label}: {json.dumps(before.get(part), ensure_ascii=False)} → {json.dumps(after.get(part), ensure_ascii=False)}', part in ('chart', 'compare', 'share', 'top', 'cumulative') and bool(before.get(part)) and not after.get(part))
    if old.get('dashboard') or new.get('dashboard'):
        show = lambda panel: f"{panel.get('title') or panel['summary']}({panel['summary']}, {panel.get('chart')}, {panel.get('value')}, 너비 {panel.get('width', 1)})"
        was, now = [show(panel) for panel in (old.get('dashboard') or {}).get('panels', [])], [show(panel) for panel in (new.get('dashboard') or {}).get('panels', [])]
        for panel in was:
            if panel not in now:
                note(f'패널이 없어지거나 바뀜: {panel}', sum(1 for item in now if item.split('(')[1].split(',')[0] == panel.split('(')[1].split(',')[0]) == 0)
        for panel in now:
            if panel not in was:
                note(f'패널이 생기거나 바뀜: {panel}')
        if was != now and sorted(was) == sorted(now):
            note('패널 순서가 바뀜')
    if (old.get('print') or None) != (new.get('print') or None):
        tidy = lambda block: {name: value for name, value in (block or {}).items() if value not in (None, [], '')}
        if tidy(old.get('print')) != tidy(new.get('print')):
            note(f"출력 양식: {json.dumps(tidy(old.get('print')), ensure_ascii=False)} → {json.dumps(tidy(new.get('print')), ensure_ascii=False)}", bool(tidy(old.get('print'))) and not tidy(new.get('print')))
    for part, label in (('checks', '비교 규칙'), ('limits', '한도'), ('effects', '자동 처리')):
        tidy = lambda item: json.dumps({name: value for name, value in item.items() if value not in (None, [], False)}, ensure_ascii=False, sort_keys=True)
        was, now = [tidy(item) for item in old.get(part) or []], [tidy(item) for item in new.get(part) or []]
        for item in was:
            if item not in now:
                note(f'{label} 없어지거나 바뀜: {item}', len(now) < len(was))
        for item in now:
            if item not in was:
                note(f'{label} 생기거나 바뀜: {item}')
    was, now = old.get('rules', []), new.get('rules', [])
    for rule in was:
        if rule not in now:
            note(f"규칙이 없어짐: {rule['message']}", True)
    for rule in now:
        if rule not in was:
            note(f"규칙이 추가됨: {rule['message']}")
    return notes, lost


CHANGE = '''%(key)s 를 고치는 요청이다. 아래가 지금의 정의 전체다.
%(current)s

이 정의에서 요청에 필요한 부분만 고치고, 나머지는 (keywords, 항목, 계산, fill, 상태, 동작, rules 까지) 한 글자도 바꾸지 말고 그대로 둔 전체를 답하라.
형식: {"action": "change", "key": "%(key)s", "definition": <고친 뒤의 전체>}'''

def accepted(saved, written):
    """The definition as the framework took it: everything that may be left out is written out by the framework itself
    (a field's required, a group's label, the lines' minimum ...), so nothing downstream reads the model's own wording."""
    definition = {name: value for name, value in saved['definition'].items() if name != 'key'}
    for part in ('rules', 'effects'):
        if written.get(part):
            definition[part] = written[part]          # the trial copy is saved without them (they are checked after publishing)
    return complete(definition)


def _unasked(request, lost, record_to):
    """Of the things that went missing, the ones the request did not ask to remove. Whether a sentence asks for a
    removal is a question of meaning, so it is put to the model as its own small question - not as a refusal of
    its answer, which it would simply obey ("팩스번호 없애줘" once came back with the fax number restored)."""
    question = ('요청: ' + request + '\n\n이 요청을 처리한 결과 아래 것들이 없어졌다.\n'
                + '\n'.join(f'{index}. {item}' for index, item in enumerate(lost, 1))
                + '\n\n각각에 대해, 요청이 그것을 없애거나 바꾸라고 한 것이면 true, 요청과 상관없는데 없어진 것이면 false 로 답하라.\n'
                  '형식: {"1": true|false, "2": ...}')
    try:
        verdict = _json(llm.ask([{'role': 'system', 'content': 'JSON only'}, {'role': 'user', 'content': question}], record_to, 'removed-on-purpose', max_tokens=200))
    except Exception:
        return list(lost)        # no clear answer: treat every loss as unasked, the safe side
    return [item for index, item in enumerate(lost, 1) if verdict.get(str(index)) is not True]


def write(request, framework, record_to, trial_prefix='trial_'):
    """Returns {'action', 'key', 'definition'} that the framework has accepted (as a trial draft).

    A change is written from the current definition itself, not from the summary: the model first says which
    entity the request is about, then gets that definition whole. Whatever went missing without being asked
    for goes back to the model once, so a rule or a formula is never dropped silently."""
    capabilities = framework.capabilities()
    shown = {key: capabilities[key] for key in ('parts', 'fieldTypes', 'builtInRules', 'ruleTypes', 'codeGroups') if key in capabilities}
    base = [{'role': 'system', 'content': 'JSON only'},
            {'role': 'user', 'content': PROMPT % {'guide': capabilities.get('guide', ''), 'capabilities': json.dumps(shown, ensure_ascii=False, indent=1), 'existing': _existing(framework), 'request': request,
                                                  'code_screens': ', '.join(code_screens()) or '(없음)'}}]
    stored = {item['key']: item['definition'] for item in real(framework, trial_prefix)}
    messages, error, answer, target, asked_back = list(base), '', '', None, False
    for attempt in range(1, 5):
        answer = llm.ask(messages, record_to, f'define-{attempt}')
        try:
            proposal = _json(answer)
            if proposal.get('action') == 'other':
                return {'action': 'other', 'reason': str(proposal.get('reason') or '')[:300]}
            action, key, definition = proposal.get('action'), proposal.get('key'), proposal.get('definition')
            if action not in ('create', 'change') or not isinstance(key, str) or key.startswith(trial_prefix):
                raise ValueError('action(create|change) 과 key 가 있어야 한다')
            if action == 'change' and key not in stored:
                raise ValueError(f'change 인데 {key} 라는 자료가 없다. 있는 자료: {sorted(stored)}')
            if action == 'create' and key in stored:
                raise ValueError(f'{key} 는 이미 있다. 그 자료를 고치는 요청이면 action 을 change 로, 새 자료면 다른 key 를 쓴다')
            if action == 'change' and target != key:
                # The first answer only tells which entity is meant; the change itself is made on the real definition.
                target = key
                base = base + [{'role': 'assistant', 'content': json.dumps({'action': 'change', 'key': key}, ensure_ascii=False)},
                               {'role': 'user', 'content': CHANGE % {'key': key, 'current': json.dumps(clean(stored[key]), ensure_ascii=False, indent=1)}}]
                messages = list(base)
                continue
            if not isinstance(definition, dict):
                raise ValueError('definition 이 있어야 한다')
            if action == 'change' and not asked_back:
                _, lost = differences(stored[key], definition)
                unasked = _unasked(request, lost, record_to) if lost else []
                if unasked:
                    asked_back = True
                    raise ValueError('요청하지 않은 것이 사라졌다:\n- ' + '\n- '.join(unasked) + '\n이것들만 원래대로 되살리고, 나머지 고친 것은 그대로 둔다')
            # The framework is the judge: the definition is saved as a trial draft; a refusal is its message.
            saved = framework.save_definition(trial_name(key, trial_prefix), {name: value for name, value in definition.items() if name not in ('rules', 'effects')}, 'DRAFT')
            return {'action': action, 'key': key, 'definition': accepted(saved, definition)}
        except Exception as problem:  # a refusal of any kind goes back to the model once more
            error = str(problem)
            messages = base + [{'role': 'assistant', 'content': answer[:4000]},
                               {'role': 'user', 'content': f'받아들여지지 않았다: {error}\n고쳐서 JSON 전체를 다시 답하라.'}]
    raise RuntimeError('정의를 만들지 못했습니다: ' + error)
