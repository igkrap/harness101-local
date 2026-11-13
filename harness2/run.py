"""말 -> 정의 -> 검사 -> 적용. One request, start to finish, with every step written down.

  python3 harness2/run.py "거래처 등록 화면 만들어줘"
  python3 harness2/run.py --definition runs/<run>/1-define/accepted.json     # checks + apply again, no model
  python3 harness2/run.py --dry "..."                                        # stop before applying

Each run is a folder: what the model was given and answered, the accepted definition, every check and
its outcome, what was applied. Nothing here knows about particular screens or fields.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import checks
import define
from framework import APP, Framework

RUNS = Path(__file__).resolve().parent / 'runs'
TRIAL = 'trial_'


def impact(framework, key, old, new):
    """What a change means for the rows that already exist."""
    notes, blocking = [], []
    rows = framework.ok('GET', f'/api/data/{key}')
    old_fields = {field['name']: field for field in old['fields']}
    new_fields = {field['name']: field for field in new['fields']}
    for name, field in new_fields.items():
        before = old_fields.get(name)
        empty = sum(1 for row in rows if row.get(name) in (None, ''))
        if field['required'] and (before is None or not before['required']) and empty:
            blocking.append(f"{field['label']} 을(를) 필수로 하려는데, 그 값이 비어 있는 기존 자료가 {empty}건 있습니다.")
        if before and before.get('type', 'text') != field.get('type', 'text'):
            filled = len(rows) - empty
            if filled:
                blocking.append(f"{field['label']} 의 종류를 {before.get('type', 'text')} → {field.get('type', 'text')} 로 바꾸려는데, 값이 들어 있는 기존 자료가 {filled}건 있습니다.")
        if before is None:
            notes.append(f"{field['label']} 항목이 추가됩니다(기존 자료 {len(rows)}건은 이 값이 빈 채로 남습니다).")
    for name, field in old_fields.items():
        if name not in new_fields:
            filled = sum(1 for row in rows if row.get(name) not in (None, ''))
            (blocking if filled else notes).append(f"{field['label']} 항목이 없어집니다" + (f"(값이 들어 있는 기존 자료 {filled}건에서 그 값이 사라집니다)." if filled else '.'))
    return notes, blocking


def run(request=None, definition_file=None, dry=False, force=False):
    folder = RUNS / time.strftime('%Y%m%d-%H%M%S')
    folder.mkdir(parents=True)
    framework = Framework()
    result = {'request': request, 'folder': str(folder)}
    started = time.time()
    try:
        if definition_file:
            proposal = json.loads(Path(definition_file).read_text(encoding='utf-8'))
            written = proposal['definition']             # goes the same way as a model's answer: the framework takes it first
            saved = framework.save_definition(TRIAL + proposal['key'], {name: value for name, value in written.items() if name != 'rules'}, 'DRAFT')
            proposal['definition'] = define.accepted(saved, written)
        else:
            (folder / 'request.txt').write_text(request, encoding='utf-8')
            proposal = define.write(request, framework, folder / '1-define', TRIAL)
        if proposal['action'] == 'other':
            result.update(status='other', reason=proposal.get('reason', ''))
            return result
        key, definition, action = proposal['key'], proposal['definition'], proposal['action']
        result['key'] = key          # known from here on, so the trial copy is removed whatever happens next
        (folder / '1-define').mkdir(exist_ok=True)
        (folder / '1-define' / 'accepted.json').write_text(json.dumps(proposal, ensure_ascii=False, indent=1), encoding='utf-8')
        def label(field):
            extra = [field.get('type', 'text')] + (['필수'] if field['required'] else []) + (['계산'] if field.get('formula') or field.get('sum') else []) \
                + ([f"{'' if field.get('min') is None else format(field['min'], 'g')}~{'' if field.get('max') is None else format(field['max'], 'g')}"] if field.get('min') is not None or field.get('max') is not None else []) \
                + (['중복 불가'] if field.get('unique') else []) + ([{'dropdown': '목록에서 고름', 'search': '입력하며 찾기', 'popup': '검색창'}[field['pick']]] if field.get('pick') else [])
            return f"{field['label']}({', '.join(str(item) for item in extra)})"
        result.update(action=action, key=key, title=definition['title'], fields=[label(field) for field in definition['fields']])
        if definition.get('lines'):
            result['lines'] = [label(field) for field in definition['lines']['fields']]
            limit = definition['lines']
            result['line_limit'] = (f"{limit.get('min', 1)}줄 이상" if limit.get('max') is None else (f"{limit['max']}줄만" if limit.get('min', 1) == limit['max'] else f"{limit.get('min', 1)}~{limit['max']}줄")) if (limit.get('min', 1) != 1 or limit.get('max') is not None) else ''
        if definition.get('status'):
            result['statuses'] = [value['label'] for value in definition['status']['values']]
            result['actions'] = [action_['label'] for action_ in definition['status']['actions']]
        if definition.get('rules'):
            result['rules'] = [rule['message'] for rule in definition['rules']]
        if definition.get('dashboard'):
            words = {'bar': '막대', 'line': '선', 'pie': '원', 'figures': '핵심 숫자'}
            result['panels'] = [f"{panel['title']} - {words[panel['chart']]}" + ('' if panel['chart'] == 'figures' else f"({panel['value']})") + f", 너비 {panel['width']}/3" for panel in definition['dashboard']['panels']]
        if definition.get('print'):
            form = definition['print']
            result['print'] = ', '.join(part for part in [f"제목 {form['title']}" if form.get('title') else '', '결재란 ' + '·'.join(form['signers']) if form.get('signers') else '',
                                                           f"맺음말 \"{form['note']}\"" if form.get('note') else ''] if part)
        if definition.get('summary'):
            part = definition['summary']
            result['summary'] = {'entity': part['entity'] + (' 의 줄 표' if part.get('lines') else ''),
                                 'groups': [group.get('label') or group['field'] for group in part['groupBy']],
                                 'values': [f"{value['label']}({ {'sum': '합계', 'count': '건수', 'avg': '평균', 'min': '최소', 'max': '최대'}[value['op']] })" for value in part['values']],
                                 'filters': part.get('filters', []),
                                 'analysis': [text for text in [
                                     f"계획 대비 실적({part['compare']['entity']} 의 {part['compare']['field']})" if (part.get('compare') or {}).get('type') == 'plan' else '',
                                     {'month': '전월 대비', 'year': '전년 대비'}[part['compare']['by']] if (part.get('compare') or {}).get('type') == 'previous' else '',
                                     f"{part['compare'].get('balance')} = {part['compare']['value']} − {part['compare']['entity']} 의 {part['compare']['field']}" if (part.get('compare') or {}).get('type') == 'minus' else '',
                                     '누계' if part.get('cumulative') else '',
                                     ', '.join(f"{value['label']}: {value['between'][0]}→{value['between'][1]} 일수" for value in part['values'] if value.get('between')),
                                     '구성비' if part.get('share') else '', f"상위 {part['top']}개" if part.get('top') else ''] if text],
                                 'chart': ({'bar': '막대', 'line': '선', 'pie': '원'}[part['chart']['type']] + ' 차트 - ' + part['chart'].get('value', '')) if part.get('chart') else ''}

        current = next((item for item in framework.definitions() if item['key'] == key), None)
        if current and action == 'change':
            notes, blocking = ([], []) if definition.get('summary') or current['definition'].get('summary') or definition.get('dashboard') or current['definition'].get('dashboard') else impact(framework, key, current['definition'], definition)
            result.update(impact=notes, needs_decision=blocking)
            result['changes'], result['removed'] = define.differences(current['definition'], definition)
            if not result['changes']:
                # Asked to change something, and the definition came back the same: that is not a success.
                result['status'] = 'unchanged'
                return result
            if blocking and not force:
                result['status'] = 'needs_decision'
                return result

        # Checks run on a trial copy: a draft with its own key and title, which the menus never show.
        trial_key, trial_title = TRIAL + key, definition['title'] + ' (시험)'
        # Rules point at other entities by their real keys, so they are checked after publishing (and undone if they fail).
        trial = {name: value for name, value in definition.items() if name != 'rules'}
        framework.save_definition(trial_key, dict(trial, title=trial_title), 'DRAFT')
        data = (checks.dashboard_checks if definition.get('dashboard') else checks.summary_checks if definition.get('summary') else checks.record_checks)(trial_key, definition, framework)
        screen = checks.screen_checks(trial_title, definition, folder / '2-check', APP)
        results = data.results + screen.results
        (folder / '2-check').mkdir(exist_ok=True)
        (folder / '2-check' / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding='utf-8')
        result.update(checks=len(results), failed=[item for item in results if not item['passed']])
        if result['failed']:
            result['status'] = 'failed'
            return result
        if dry:
            result['status'] = 'checked'
            return result
        saved = framework.save_definition(key, definition, 'PUBLISHED')
        if definition.get('rules'):
            ruled = checks.rule_checks(key, definition, framework)
            results += ruled.results
            (folder / '2-check' / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding='utf-8')
            result.update(checks=len(results), failed=[item for item in results if not item['passed']])
            if result['failed']:
                # Put back what was there before (or take the new entity away again).
                if current:
                    framework.save_definition(key, current['definition'], current['status'])
                else:
                    framework.delete_definition(key, force=True)
                result['status'] = 'failed'
                return result
        (folder / '3-apply').mkdir(exist_ok=True)
        (folder / '3-apply' / 'published.json').write_text(json.dumps(saved, ensure_ascii=False, indent=1), encoding='utf-8')
        result.update(status='applied', program=saved['programCode'], revision=saved['revision'])
        return result
    except Exception as problem:
        result.update(status='error', error=str(problem)[:600])
        return result
    finally:
        if result.get('key'):
            framework.delete_definition(TRIAL + result['key'], force=True)   # the trial copy never outlives the run
        pending, checks.LEFTOVER[:] = list(checks.LEFTOVER), []
        still = [item for item in checks.sweep(framework, pending) if not item[0].startswith(TRIAL)]
        checks.LEFTOVER[:] = []
        if still:
            result['leftover_rows'] = still
        result['seconds'] = round(time.time() - started, 1)
        (folder / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')


def say(result):
    """The outcome in plain words."""
    lines = []
    status = result.get('status')
    if result.get('title'):
        lines.append(f"{'새 화면' if result.get('action') == 'create' else '화면 수정'}: {result['title']}  ({result['key']})")
        if result.get('panels'):
            lines.append(f"현황판: 차트 패널 {len(result['panels'])}개")
            lines += ['  · ' + panel for panel in result['panels']]
        elif result.get('summary'):
            part = result['summary']
            lines.append(f"집계 화면: {part['entity']} 을(를) {', '.join(part['groups'])}(으)로 묶어 {', '.join(part['values'])}")
            if part['filters']:
                lines.append('조회 조건: ' + ', '.join(part['filters']))
            if part.get('analysis'):
                lines.append('분석 틀: ' + ', '.join(part['analysis']))
            if part['chart']:
                lines.append('차트: ' + part['chart'])
        else:
            lines.append(('위쪽 항목: ' if result.get('lines') else '항목: ') + ', '.join(result.get('fields', [])))
        if result.get('lines'):
            lines.append('줄 표 항목: ' + ', '.join(result['lines']) + (f"  [{result['line_limit']}]" if result.get('line_limit') else ''))
        if result.get('statuses'):
            lines.append('상태: ' + ' → '.join(result['statuses']) + ' / 동작: ' + ', '.join(result.get('actions', [])))
        if result.get('print'):
            lines.append('출력 양식: ' + result['print'])
        for rule in result.get('rules', []):
            lines.append('규칙: ' + rule)
    if result.get('action') == 'change':
        lines.append('바뀐 점:' if result.get('changes') else '바뀐 점: 없음')
        for note in result.get('changes', []):
            lines.append('  - ' + note)
    for note in result.get('impact', []):
        lines.append('· ' + note)
    if status == 'applied':
        lines.append(f"검사 {result['checks']}개 통과 → 적용했습니다. ({result['seconds']}초)")
    elif status == 'checked':
        lines.append(f"검사 {result['checks']}개 통과. 적용은 하지 않았습니다(--dry).")
    elif status == 'unchanged':
        lines.append('적용하지 않았습니다. 요청을 반영한 변화가 없습니다(이미 그렇게 되어 있거나, 요청을 이해하지 못했습니다).')
    elif status == 'needs_decision':
        lines.append('적용하지 않았습니다. 먼저 정해야 할 것:')
        lines += ['  - ' + item for item in result['needs_decision']]
    elif status == 'failed':
        lines.append(f"검사 {result['checks']}개 중 {len(result['failed'])}개 실패. 적용하지 않았습니다:")
        lines += [f"  - {item['description']}: {item['detail']}" for item in result['failed']]
    elif status == 'other':
        lines.append('정의로 처리할 수 없는 요청입니다: ' + result.get('reason', ''))
    else:
        lines.append('실패: ' + result.get('error', ''))
    lines.append('기록: ' + result['folder'])
    return '\n'.join(lines)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('request', nargs='?')
    parser.add_argument('--definition')
    parser.add_argument('--dry', action='store_true')
    parser.add_argument('--force', action='store_true', help='apply even when existing rows are affected')
    args = parser.parse_args()
    if not args.request and not args.definition:
        parser.error('요청 문장이나 --definition 파일이 필요합니다')
    outcome = run(args.request, args.definition, args.dry, args.force)
    print(say(outcome))
    sys.exit(0 if outcome.get('status') in ('applied', 'checked') else 1)
