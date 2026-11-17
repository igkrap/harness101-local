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

업무 흐름과 기준 정보 (지금 시스템의 화면 정의에서 프레임워크가 읽어 낸 것 - 사람이 보는 업무 안내서와 같은 내용):
%(process)s

이 프로젝트의 업무 원칙 (사용자가 정해 둔 것 - 있으면 따른다. 없으면 요청과 그 업무의 상식으로 정한다):
%(principles)s

규칙:
- 요청이 이미 있는 자료를 고치는 것이면 {"action": "change", "key": "<그 자료의 key>"} 까지만 답한다(그러면 그 자료의 정의 전체를 받아서 고치게 된다).
- 새 자료면 action 은 "create" 이고 key 는 이미 있는 key 와 겹치지 않게 한다.
- 정의 하나는 화면 하나다. 요청을 다 하려면 화면을 둘 이상 만들거나 고쳐야 할 때는 정의를 쓰지 말고 {"action": "steps", "steps": ["<첫 화면에 대한 요청 문장>", "<다음 화면에 대한 요청 문장>", ...]} 로만 답한다.
  요청의 말을 바꾸지 않는다("등록하면"을 "확정하면"으로 바꾸지 않는다). 요청에 없는 조건을 덧붙이지 않는다.
  먼저 있어야 하는 것부터 차례로 적는다(가리킬 자료 → 그것을 쓰는 화면, 집계 화면 → 그것을 담는 현황판, 상태·동작 추가 → 그 동작을 쓰는 자동 처리). 각 문장은 화면 하나에 대한 것이고, 앞뒤 문장 없이도 뜻이 통하게 화면 이름과 할 일을 다 적는다.
- 현황·합계·통계·차트처럼 이미 있는 자료를 모아서 보는 요청은 새 자료를 만들지 말고 집계 화면(summary)으로 한다. 모을 자료는 이미 있어야 한다.
- 승인 화면·처리 화면·대기 목록·조회 전용 화면처럼 이미 있는 자료를 다른 화면으로 여는 요청은 새 자료를 만들지 말고 over 로 한다. 권한은 화면 단위이므로 "팀장만 승인"은 승인 화면을 따로 만드는 것으로 푼다(누구에게 그 화면을 줄지는 사람이 정한다). 그 동작을 등록 화면에서는 못 하게 하려면 steps 로: 먼저 그 자료의 등록 화면에서 동작에 separate 를 붙이고(없는 상태·동작이면 추가하고), 다음에 업무 화면을 만든다.
- 앞 단계 자료를 조회해서 다음 단계를 등록하는 요청("주문을 조회해서 출하 등록", "점검 지시에서 골라 점검 결과 등록", "~에서 골라서 한꺼번에 ~ 등록")은 새 등록 화면을 만들지 말고 이어받기 화면(take)으로 한다. 여러 건을 목록에서 고르고 수량만 고쳐 저장하는 화면이며 입력 폼이 없다. 만들 자료와 앞 단계 자료는 이미 있어야 하고, 만들 자료에 앞 단계를 한도로 하는 limits 가 있어야 한다(없으면 steps 로 그 한도부터 넣는다).
- 현황판·대시보드처럼 차트만 모아 보는 요청은 dashboard 로 한다. 패널은 이미 있는 집계 화면만 가리킬 수 있으므로, 맞는 집계 화면이 있으면 그것을 쓰고, 없으면 steps 로 필요한 집계 화면들을 먼저 만들고 마지막에 현황판을 만든다.
- 수량 원장(ledger)으로 들고 나는 것의 남은 수량·현재 수량을 보는 화면은 집계로 빼지 말고 원장 보기(ledgerView)로 하고, thing 에 그 대상 자료 key 를 적는다 (재고 현황 → item, 장비 보관 현황 → equipment).
- 잔량·미처리·남은 수량처럼 한 자료에서 다른 자료를 뺀 나머지(원장이 아닌 것)는 compare minus 로, 처리 기간·소요 일수는 values 의 between 으로, 누계는 cumulative 로 한다.
- 계획 대비·목표 대비·달성률은 compare plan 으로, 전월 대비·전년 대비·증감은 compare previous 로, 비중·점유율은 share 로, 순위·상위 N 은 top 으로 한다. 계획을 담은 자료가 없으면 이 요청으로는 그 등록 화면(예: 판매 계획, 점검 계획)부터 만든다.
- 요청이 항목을 정해 주지 않았으면 그 업무에서 흔히 쓰는 항목으로 정한다(5~8개, 마스터-디테일이면 디테일 항목 3~5개).
- 번호(serial), 상태(status)는 그 업무에 실제로 필요할 때만 붙인다. 줄 표(lines)는 하나의 마스터에 디테일이 여러 개 딸린 기준 정보에만 붙인다 (품목의 공정 순서, 점검표의 점검 항목). BOM 은 상위 품목·하위 자재·소요량 한 쌍을 한 건으로 등록한다 (줄 표 없이, noCycle 은 상위 품목과 하위 자재 항목에, 겹치면 안 되는 조합은 상위·하위 쌍). 이런 기준 정보는 업무보다 먼저 등록해 두는 것이다. 조합 기준 정보에는 uniqueBy(품목당 하나 등), 줄 항목 unique(같은 자재 두 줄 금지), noCycle(상위·하위가 같은 자료를 가리킬 때 순환 금지)을 요청에 맞게 적는다. 업무 흐름의 자료(작업지시, 생산실적 ...)에는 줄 표를 붙이지 않고, 자재나 공정이 필요하면 그 기준 정보를 가리킨다. 요청이 개수나 범위를 말하면("하나만", "0~100") 그대로 적는다.
- required 는 그 값 없이는 자료가 성립하지 않는 항목에만 true.
- search 는 조회 조건으로 쓸 항목(1~3개, 줄 항목 제외)에 true.
- 다른 자료에서 고르는 항목(거래처, 품목, 장비, 사원, 부서 ...)은 글자로 받지 말고 ref 로 한다. 이미 있는 자료만 가리킬 수 있고, ref.label 과 fill 의 값은 그 자료에 실제로 있는 항목 name 이어야 한다(위 '이미 있는 자료' 참고).
- 정해진 값 중에서 고르는 항목은 code 로 한다. 맞는 공통 코드 그룹이 있으면 그것을 쓰고, 없으면 그 정의의 codeGroups 에 그룹과 값을 선언한다 (단위, 거래처 구분, 점검 결과 ...). 값이 정해져 있지 않은 것만 글자(text)로 둔다.
- 단가·요율·표준 시간처럼 대상과 날짜에 따라 정해지는 값은 그 값을 담은 기준 정보(예: 품목 단가 - 거래처·품목별, 적용 기간, effective by [거래처, 품목])를 두고, 쓰는 자료에 lookups 로 찾아 채운다 (거래처 단가 → 없으면 품목 기본 단가처럼 여러 개를 순서대로).
- "~하면 ~못 하게" 같은 요청은 rules 로 적는다. 규칙이 가리키는 자료와 항목은 이미 있어야 한다.
- 다른 자료가 가리키고 있는 자료는 프레임워크가 언제나 지우지 못하게 막는다: 그것을 막는 규칙(blockWhenReferenced 의 delete)을 따로 만들지 않는다. 요청에 없는 규칙은 덧붙이지 않는다.
- effects 의 on 은 요청의 말 그대로 정한다: "등록하면·저장하면·입력하면"은 create, "확정하면·승인하면·완료하면"처럼 상태 버튼을 말하면 그 action 이름이다.
- 한 건 안에서 두 값을 견주는 조건(날짜 순서 등)은 checks 로, 다른 자료의 수량을 넘지 못하게 하는 것(지시보다 많이 처리하기 방지)은 limits 로, "~하면 자동으로 ~된다/만들어진다"는 effects 로 적는다. 그 규칙은 저장이 거절되어야 하는 자료, 일이 시작되는 자료의 정의에 붙인다(출하 수량 제한은 출하에, 수주 확정 시 출하 생성은 수주에).
- id, 상태, 등록·수정자/일시는 프레임워크가 관리하므로 항목으로 넣지 않는다(상태는 definition.status 로).
- 이미 있는 자료의 건마다 그 뒤에 일어난 일을 남기는 화면(요청이 "~에서 생성한 데이터 기반으로", "~한 것 중", "~한 사람 중", "~한 건을", "~에 대해"처럼 앞의 자료를 가리킬 때)은 따로 적는 자료로 만들지 않고 "from": {"entity": "<앞 자료 key>"} 를 적는다 - 앞 자료를 가리키는 항목, 한 건에 한 번만, 같은 이름 항목 넘겨받기, 앞 자료 목록에서 골라 만드는 탭을 프레임워크가 갖춘다. 화면 하나로 끝나므로 steps 로 나누지 않는다. 앞 자료와 같은 이름·같은 종류의 항목을 두면 그 값이 넘어온다.
- 요청이 업무 흐름 속 화면을 만들거나 고치는 것이면 그 흐름 전체를 보고 정한다: 앞뒤 단계를 잇는 길(이어받기 화면, 자동 처리, 한도)이 끊기지 않게, 같은 수량이 두 길로 두 번 처리되지 않게 한다. '판정하는 흐름'은 적용 전에 하네스가 끝까지 돌려 본다.
- 정의로 할 수 없는 요청이면 {"action": "other", "reason": "<이유 한 줄>"} 로만 답한다. 해당하는 경우: 아래 '코드로 만든 화면'을 고치는 요청, 로그인·메뉴·권한·디자인 같은 시스템 요청, 프레임워크 안내에 없는 동작.

코드로 만든 화면(정의가 아니라서 여기서 고칠 수 없음): %(code_screens)s

요청: %(request)s'''


def trial_name(key, prefix='trial_'):
    """The key of a trial copy: the prefix and the key, cut to the framework's 40 characters."""
    return (prefix + key)[:40]


def repoint(definition, was, now):
    """The definition with its fields that point at the screen `was` pointing at `now` instead. A screen may point at itself
    (a parent department); its trial copy must then point at the trial, and what the framework hands back must point home again."""
    out = json.loads(json.dumps(definition))
    for field in (out.get('fields') or []) + ((out.get('lines') or {}).get('fields') or []) + [item for more in out.get('moreLines') or [] for item in more.get('fields') or []]:
        if isinstance(field.get('ref'), dict) and field['ref'].get('entity') == was:
            field['ref']['entity'] = now
    return out


def trial_save(framework, key, definition, prefix, leave=('rules', 'effects')):
    """Save the definition as its trial draft (the framework's judgement of it) and return what the framework stored, pointing home."""
    name = trial_name(key, prefix)
    saved = framework.save_definition(name, repoint({part: value for part, value in definition.items() if part not in leave}, key, name), 'DRAFT')
    return dict(saved, definition=repoint(saved['definition'], name, key)) if isinstance(saved, dict) and isinstance(saved.get('definition'), dict) else saved


def real(framework, trial_prefix='trial_'):
    """The definitions there really are: a trial copy left by an interrupted run is not one of them."""
    return [item for item in framework.definitions() if not item['key'].startswith(trial_prefix)]


def _fields(fields, in_lines=False):
    def one(field):
        extra = field['type'] + (f"→{field['ref']['entity']}" if field.get('ref') else '') + (', 필수' if field['required'] else '') \
            + (', 계산' if field.get('formula') or field.get('sum') else '') + (', 중복 불가 (한 건 안에서 같은 값 두 번 금지)' if field.get('unique') and in_lines else ', 중복 불가' if field.get('unique') else '') \
            + (f", {field['ref']['entity']} 의 줄 하나를 고름" + (f" ({field['ref']['within']} 이(가) 같은 것만)" if field['ref'].get('within') else '') if (field.get('ref') or {}).get('line') else '') \
            + ''.join(f", {field[part]['field']}{'≠' if field[part].get('not') else '='}{'|'.join(field[part]['is']) or '비어 있음'} 일 때{word}" for part, word in (('showWhen', '만 보임'), ('requiredWhen', ' 필수'), ('lockWhen', ' 잠김')) if field.get(part))
        return f"{field['name']}({field['label']}, {extra})"
    return ', '.join(one(field) for field in fields)


def describe(key, definition):
    """One screen in words: what it holds and how it behaves (the line the model reads for an existing screen)."""
    text = f"- key {key} / 화면 이름 {definition['title']} / 항목: {_fields(definition['fields'])}"
    if definition.get('lines'):
        text += f" / 줄 표({definition['lines']['label']}): {_fields(definition['lines']['fields'], True)}"
    for more in definition.get('moreLines') or []:
        text += f" / 줄 표 {more['name']}({more['label']}): {_fields(more['fields'])}"
    if definition.get('status'):
        text += ' / 상태: ' + ', '.join(f"{value['code']}={value['label']}" for value in definition['status']['values']) \
            + ' / 동작: ' + ', '.join(f"{action['name']}({action['label']})" for action in definition['status']['actions'])
    if definition.get('rules'):
        text += ' / 규칙: ' + '; '.join(rule['message'] for rule in definition['rules'])
    if definition.get('checks'):
        text += ' / 비교 규칙: ' + '; '.join(rule['message'] for rule in definition['checks'])
    if definition.get('limits'):
        text += ' / 한도: ' + '; '.join(f"{rule['message']} (" + (f"{rule['entity']} 한 건에 한 번만, " if not rule.get('field') else f"{rule['field']} 합이 {rule['entity']} 의 {rule['entityField']} 을(를) 넘지 못함, ")
                                         + ', '.join(f'{mine}↔{theirs}' for mine, theirs in zip(rule['by'], rule['entityBy'])) + ' 이(가) 같은 것끼리)' for rule in definition['limits'])
    for span in definition.get('noOverlap') or []:
        text += f" / 겹침 금지: {span['from']}~{span['to']}" + (f" ({', '.join(span['by'])} 이(가) 같은 것끼리)" if span.get('by') else '') + (f", 세지 않는 상태 {span['ignore']}" if span.get('ignore') else '')
    if definition.get('effective'):
        part = definition['effective']
        text += f" / 적용 기간: {part['from']} ~ {part.get('to') or '(계속)'}" + (f" ({', '.join(part.get('by') or [])} 이(가) 같은 것끼리 기간이 겹치지 않음)" if part.get('by') else '')
    if definition.get('uniqueBy'):
        text += ' / ' + ', '.join('·'.join(group) + ' 이(가) 같은 자료는 하나만 (중복 등록 금지)' for group in definition['uniqueBy'])
    if definition.get('noCycle'):
        text += f" / 순환 금지: 줄의 {definition['noCycle']['child']} 이(가) {definition['noCycle']['parent']} 자신이거나 돌고 돌아 다시 그것을 품을 수 없음"
    if definition.get('ledger'):
        part = definition['ledger']
        text += f" / 수량 원장: {dict(zip(('in', 'out', 'move', 'count'), ('들어옴', '나감', '위치 이동', '세기'))).get(part['direction'], part['direction'])} - 대상 {part['thing']}, 수량 {part['quantity']}, 위치 {part['place']}" + (f", 받는 위치 {part['toPlace']}" if part.get('toPlace') else '') + (f", 묶음 번호 {part['lot']}" if part.get('lot') else '')
    if definition.get('screen') is False or definition.get('dataOnly'):
        text += ' / 화면 없음: 다른 업무에서 저절로 만들어지고 바뀌는 데이터 ("screen": false)'
    if definition.get('codeGroups'):
        text += ' / 선언한 코드 그룹: ' + ', '.join(f"{group['code']}({group['name']}: {', '.join(value['code'] for value in group['values'])})" for group in definition['codeGroups'])
    if definition.get('lock'):
        text += f" / 마감: {definition['lock']['group']} 묶음 ({definition['lock']['date']} 기준)"
    if definition.get('lookups'):
        text += ' / 찾아 채우기: ' + '; '.join(f"{', '.join(item['set'])} ← {item['from']} ({', '.join(f'{theirs}={mine}' for theirs, mine in item['match'].items())}" + (f", {item['at']} 날짜 기준" if item.get('at') else '') + ')' for item in definition['lookups'])
    if definition.get('follows'):
        text += f" / 후행 자료: {definition['follows']} 이(가) 가리키는 앞 단계를 이어받아서만 생긴다 (자기 화면에서 신규 등록 없음, 앞 단계 없이는 기타 화면에서)"
    if (definition.get('status') or {}).get('closed'):
        text += ' / 끝난 상태(더 이어지지 않음): ' + ', '.join(definition['status']['closed'])
    if definition.get('effects'):
        text += ' / 자동 처리: ' + '; '.join(('등록할 때' if effect['on'] == 'create' else f"{effect['on']} 동작을 할 때") + ' → ' + (f"{effect['create']['entity']} 한 건을 만든다" if effect.get('create') else f"{effect['expand']['from']} 에서 {', '.join(effect['expand']['match'])} 이(가) 같은 것을 찾아 그 줄마다 {effect['expand']['into']} 한 건씩 만든다 (수량 = 줄의 수량 × 이 자료의 수량)" + (f", 이 자료의 {effect['expand']['at']} 날짜에 유효한 것만" if effect['expand'].get('at') else ', 등록하는 날(오늘) 유효한 것만') if effect.get('expand') else f"{effect['fill']['entity']} 의 수량이 다 차면 그 자료에 {effect['fill']['action']} 동작을 한다" if effect.get('fill') else f"이 자료를 {effect['cascade']['via']} 로 가리키는 {effect['cascade']['entity']} 에도 {effect['cascade']['action']} 동작을 한다(아래로 전파)" if effect.get('cascade') else f"{effect['act']['via']} 이(가) 가리키는 자료에 {effect['act']['action']} 동작을 한다") for effect in definition['effects'])
    if definition.get('over'):
        part = definition['over']
        text = f"- key {key} / 화면 이름 {definition['title']} / 업무 화면: {part['entity']} 자료 중 " + (f"상태 {part['statuses']} 인 건" if part.get('statuses') else '모든 건') \
            + f" / 이 화면의 동작: {part.get('actions') or '없음'}" + (' / 내용 수정 가능' if part.get('edit') else '') + (' / 새로 등록 가능(등록 화면)' if part.get('create') else '')
    if definition.get('ledgerView'):
        text = f"- key {key} / 화면 이름 {definition['title']} / 원장 보기 화면: " + {'all': '현재 수량·묶음·들고 난 내역 셋 다 (탭)', 'balance': '현재 수량', 'lots': '묶음', 'moves': '들고 난 내역'}.get(definition['ledgerView'].get('show') or 'all', '') + (f" / 보는 대상: {definition['ledgerView']['thing']}" if definition['ledgerView'].get('thing') else '')
    if definition.get('take'):
        part = definition['take']
        typed = part.get('ask') or (part.get('lines') or {}).get('ask') or []
        carried = list((part.get('set') or {}).keys()) + list((part.get('lineSet') or (part.get('lines') or {}).get('set') or {}).keys())
        text = (f"- key {key} / 화면 이름 {definition['title']} / 이어받기 화면: {part['from']} 에서 아직 남은 것을 목록으로 보여 주고, 줄을 여러 개 골라 "
                f"이번 수량(줄마다 직접 적음)" + (f"과 {', '.join(typed)}(줄마다 직접 적음)" if typed else '') + f" 을(를) 적어 한꺼번에 저장하면 고른 줄마다 {part['entity']} 이(가) 한 건씩 만들어진다"
                + (f" / 앞 단계에서 함께 넘기는 값: {', '.join(carried)}" if carried else '') + (f" / 상태 {', '.join(part['statuses'])} 인 건만" if part.get('statuses') else ''))
    for kind, word in (('calendar', '달력 화면'), ('tree', '트리 화면')):
        if definition.get(kind):
            text = f"- key {key} / 화면 이름 {definition['title']} / {word}: " + json.dumps({name: value for name, value in definition[kind].items() if value not in (None, [])}, ensure_ascii=False)
    if definition.get('dashboard'):
        text = f"- key {key} / 화면 이름 {definition['title']} / 현황판: 패널 " + ', '.join(f"{panel['summary']}({panel['chart']})" for panel in definition['dashboard']['panels'])
    if definition.get('summary'):
        part = definition['summary']
        text = f"- key {key} / 화면 이름 {definition['title']} / 집계 화면: {part['entity']}" + (' 의 줄 표' if part.get('lines') else '') + ' 을(를) ' \
            + ', '.join(group['field'] + (f"({group['by']})" if group.get('by') else '') for group in part['groupBy']) + ' (으)로 묶어 ' \
            + ', '.join(f"{value['label']}={value['op']}" + (f"({value['field']})" if value.get('field') else '') for value in part['values']) \
            + (f" / 차트 {part['chart']['type']}" if part.get('chart') else '') \
            + (f" / 계획 대비({part['compare']['entity']})" if (part.get('compare') or {}).get('type') == 'plan' else f" / {part['compare'].get('balance')}(− {part['compare']['entity']})" if (part.get('compare') or {}).get('type') == 'minus' else f" / 전기 대비({part['compare']['by']})" if part.get('compare') else '') \
            + (' / 구성비' if part.get('share') else '') + (f" / 상위 {part['top']}" if part.get('top') else '')
    return text


def process(framework):
    """The flows, the master data by layer and the rules every screen has, as the framework reads them off the definitions
    (GET /api/meta/process - the same text people read as the 업무 안내서), and which flows are judged end to end."""
    try:
        text = framework.ok('GET', '/api/meta/process')['text']
    except Exception:            # an older framework without the guide: the screens alone
        return '(없음)'
    if '[화면별]' in text:        # each screen is already told above, with its keys and field names
        head, _, rest = text.partition('[화면별]')
        text = head + rest[rest.find('[모든 화면에 걸리는 규칙]'):] if '[모든 화면에 걸리는 규칙]' in rest else head
    import flows                 # (late: flows reads the checks, which read this module)
    judged = [flow['name'] for flow in flows.load()]
    return text.strip() + ('\n[판정하는 흐름 - 적용 전에 끝까지 돌려 본다]\n' + '\n'.join(f'- {name}' for name in judged) if judged else '')


def _existing(framework):
    return '\n'.join(describe(item['key'], item['definition']) for item in real(framework)) or '(없음)'


def principles():
    """The project's own business principles (principles.md at its root, written and changed by the user): what the harness itself never assumes."""
    path = __import__('framework').site().root / 'principles.md'
    text = path.read_text(encoding='utf-8').strip() if path.exists() else ''
    return text or '(없음)'


def code_screens():
    """Titles of the screens that exist as code files (they are changed by the code route, not by definitions)."""
    from pathlib import Path
    titles = []
    for path in sorted((__import__('framework').site().root / 'frontend/src/screens').glob('*.tsx')):
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
    groups = [definition.get('fields') or []] + ([definition['lines'].get('fields') or []] if isinstance(definition.get('lines'), dict) else []) \
        + [more.get('fields') or [] for more in definition.get('moreLines') or [] if isinstance(more, dict)]
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
    if definition.get('moreLines'):
        out['moreLines'] = [{name: value for name, value in dict(more, fields=[field(item) for item in more['fields']]).items() if value is not None and not (name == 'min' and value == 0)}
                            for more in definition['moreLines']]
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
    was, now = {more['name']: more for more in old.get('moreLines') or []}, {more['name']: more for more in new.get('moreLines') or []}
    for name, more in was.items():
        if name not in now:
            note(f"줄 표 {more['label']}({name}) 이(가) 통째로 없어짐", True)
            continue
        compare(f"줄 표 {more['label']} 의", more['fields'], now[name]['fields'])
        for part in ('label', 'min', 'max'):
            if more.get(part) != now[name].get(part):
                note(f"줄 표 {more['label']} 의 {part}: {more.get(part)} → {now[name].get(part)}")
    for name, more in now.items():
        if name not in was:
            note(f"줄 표 {more['label']}({name}) 이(가) 추가됨")
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
        if sorted(before.get('closed') or []) != sorted(after.get('closed') or []):
            note(f"끝난 상태(더 이어지지 않음): {before.get('closed') or []} → {after.get('closed') or []}", bool(set(before.get('closed') or []) - set(after.get('closed') or [])))
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
    for part, word in (('calendar', '달력 화면'), ('tree', '트리 화면'), ('take', '이어받기 화면'), ('ledgerView', '원장 보기 화면'), ('ledger', '수량 원장'), ('uniqueBy', '겹치면 안 되는 조합'), ('effective', '적용 기간'), ('noOverlap', '겹침 금지'), ('noCycle', '순환 금지'), ('period', '처음 조회 기간')):
        if (old.get(part) or None) != (new.get(part) or None):
            note(f"{word}: {json.dumps(old.get(part), ensure_ascii=False)} → {json.dumps(new.get(part), ensure_ascii=False)}", bool(old.get(part)) and not new.get(part))
    only = lambda definition: bool(definition.get('dataOnly') or definition.get('screen') is False)
    if only(old) != only(new):
        note('화면: ' + ('있음 → 없음 (데이터로만)' if only(new) else '없음 → 있음'), only(old) and not only(new))
    if (old.get('codeGroups') or []) != (new.get('codeGroups') or []):
        note(f"코드 그룹 선언: {', '.join(group['code'] for group in old.get('codeGroups') or []) or '없음'} → {', '.join(group['code'] for group in new.get('codeGroups') or []) or '없음'}")
    if (old.get('lock') or None) != (new.get('lock') or None):
        note(f"마감: {json.dumps(old.get('lock'), ensure_ascii=False)} → {json.dumps(new.get('lock'), ensure_ascii=False)}", bool(old.get('lock')) and not new.get('lock'))
    if (old.get('lookups') or []) != (new.get('lookups') or []):
        note(f"찾아 채우기: {json.dumps(old.get('lookups') or [], ensure_ascii=False)} → {json.dumps(new.get('lookups') or [], ensure_ascii=False)}", len(new.get('lookups') or []) < len(old.get('lookups') or []))
    if (old.get('follows') or None) != (new.get('follows') or None):
        note(f"후행 자료(앞 단계를 이어받아서만 생김): {old.get('follows')} → {new.get('follows')}", bool(old.get('follows')) and not new.get('follows'))
    if (old.get('over') or None) != (new.get('over') or None):
        note(f"업무 화면: {json.dumps(old.get('over'), ensure_ascii=False)} → {json.dumps(new.get('over'), ensure_ascii=False)}")
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


def _mismatch(request, key, definition, before, record_to):
    """Does the result say what the request said? Put to the model as a reading task (easier than writing): the request
    beside the result in words. Returns '' when they agree, else one line naming the difference."""
    made = describe(key, complete(json.loads(json.dumps(definition))))
    if before is not None:
        notes, _ = differences(before, definition)
        made = '바뀐 점:\n' + ('\n'.join('- ' + note for note in notes) or '- (없음)') + '\n\n고친 뒤의 화면:\n' + made
    question = ('사용자의 요청과, 그 요청으로 만든 결과다. 결과가 요청과 어긋나는지 본다.\n\n요청: ' + request + '\n\n결과:\n' + made + '''

어긋남으로 보는 것:
- 요청이 말한 때·조건·대상·숫자를 다른 것으로 바꿨다 (예: "등록하면"을 "확정하면"으로, "하나만"을 제한 없음으로).
- 요청이 말한 것을 빠뜨렸다.
- 요청에 없는 조건이나 동작을 덧붙였다.
어긋남이 아닌 것: 요청이 정해 주지 않은 세부(항목 구성, 이름, 조회 조건, 차트 모양 등)를 알아서 정한 것, 요청과 무관하게 원래 있던 것.
형식: {"ok": true} 또는 {"ok": false, "problem": "<무엇이 어떻게 다른지 한 줄>"}''')
    try:
        verdict = _json(llm.ask([{'role': 'system', 'content': 'JSON only'}, {'role': 'user', 'content': question}], record_to, 'matches-request', max_tokens=200))
    except Exception:
        return ''
    return '' if verdict.get('ok') is not False else str(verdict.get('problem') or '요청과 다른 점이 있다')[:300]


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


def write(request, framework, record_to, trial_prefix='trial_', allow_steps=True):
    """Returns {'action', 'key', 'definition'} that the framework has accepted (as a trial draft).

    A change is written from the current definition itself, not from the summary: the model first says which
    entity the request is about, then gets that definition whole. Whatever went missing without being asked
    for goes back to the model once, so a rule or a formula is never dropped silently."""
    capabilities = framework.capabilities()
    shown = {key: capabilities[key] for key in ('parts', 'fieldTypes', 'builtInRules', 'ruleTypes', 'codeGroups') if key in capabilities}
    base = [{'role': 'system', 'content': 'JSON only'},
            {'role': 'user', 'content': PROMPT % {'guide': capabilities.get('guide', ''), 'capabilities': json.dumps(shown, ensure_ascii=False, indent=1), 'existing': _existing(framework), 'process': process(framework), 'principles': principles(), 'request': request,
                                                  'code_screens': ', '.join(code_screens()) or '(없음)'}}]
    stored = {item['key']: item['definition'] for item in real(framework, trial_prefix)}
    messages, error, answer, target, asked_back, compared, doubt = list(base), '', '', None, False, False, ''
    told_done = False      # a step told once that the work it put before itself is there already
    trials = set()       # trial copies saved along the way; only the accepted one is left for the checks
    for attempt in range(1, 5):
        answer = llm.ask(messages, record_to, f'define-{attempt}')
        try:
            proposal = _json(answer)
            if proposal.get('action') == 'other':
                for other in trials:
                    framework.delete_definition(other, force=True)
                return {'action': 'other', 'reason': str(proposal.get('reason') or '')[:300]}
            if proposal.get('action') == 'steps':
                steps = [str(step).strip() for step in proposal.get('steps') or [] if str(step).strip()]
                if not 1 <= len(steps) <= 6:
                    raise ValueError('steps 는 1~6개의 요청 문장이어야 한다')
                if not allow_steps:
                    itself = re.sub(r'\s+', '', request.split('\n')[0])
                    if any(re.sub(r'\s+', '', step) in itself or itself in re.sub(r'\s+', '', step) for step in steps) and not told_done:
                        # the step names itself again behind work it takes to come first: that work is there already (the plan put it
                        # before this step) - the screen itself is asked for, once
                        told_done = True
                        messages = list(base) + [{'role': 'assistant', 'content': answer},
                                                 {'role': 'user', 'content': '그 앞의 일(' + ' / '.join(step for step in steps if re.sub(r'\s+', '', step) not in itself and itself not in re.sub(r'\s+', '', step))
                                                  + ')은 이미 되어 있다 (위의 이미 있는 자료를 보라). steps 로 나누지 말고 이 화면 하나의 정의를 JSON 으로 답하라.'}]
                        continue
                    # a step that turns out to need more than one screen: its parts go into the plan it belongs to, in its place
                    for other in trials:
                        framework.delete_definition(other, force=True)
                    return {'action': 'split', 'steps': steps}
                return {'action': 'steps', 'steps': steps}         # (one step only: that one request, done as a step)
            action, key, definition = proposal.get('action'), proposal.get('key'), proposal.get('definition')
            if action not in ('create', 'change') or not isinstance(key, str) or key.startswith(trial_prefix):
                raise ValueError('action(create|change) 과 key 가 있어야 한다')
            if action == 'change' and key not in stored:
                if isinstance(definition, dict) and definition.get('title'):
                    action = 'create'            # a whole definition for a key that is not there yet: a new one, as meant
                else:
                    raise ValueError(f'change 인데 {key} 라는 자료가 없다. 새 자료면 {{"action": "create", "key": ..., "definition": <정의 전체>}} 로 답한다. 있는 자료: {sorted(stored)}')
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
            trials.add(trial_name(key, trial_prefix))
            saved = trial_save(framework, key, definition, trial_prefix)
            # Rules and effects name real entities, so they are judged under the real key (nothing is stored): a refusal goes back to the model like any other.
            if definition.get('rules') or definition.get('effects'):
                framework.validate_definition(key, definition)
            # Read once against the request; a difference goes back to the model once. If it is still there, the result carries
            # the doubt instead of stopping - the person is told only when there is something to look at.
            taken = accepted(saved, definition)
            doubt = _mismatch(request, key, taken, stored.get(key) if action == 'change' else None, record_to)
            if doubt and not compared:
                compared = True
                raise ValueError('요청과 다르다: ' + doubt + '\n요청의 말 그대로 되게 고친다 (요청이 맞고 이 지적이 틀렸다고 보면 그대로 다시 답한다)')
            for other in trials - {trial_name(key, trial_prefix)}:
                framework.delete_definition(other, force=True)
            return {'action': action, 'key': key, 'definition': taken, 'doubt': doubt}
        except Exception as problem:  # a refusal of any kind goes back to the model once more
            error = str(problem)
            messages = base + [{'role': 'assistant', 'content': answer[:4000]},
                               {'role': 'user', 'content': f'받아들여지지 않았다: {error}\n고쳐서 JSON 전체를 다시 답하라.'}]
    for other in trials:          # nothing was accepted: no trial copy stays behind
        framework.delete_definition(other, force=True)
    raise RuntimeError('정의를 만들지 못했습니다: ' + error)
