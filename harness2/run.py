"""말 -> 정의 -> 검사 -> 적용. One request, start to finish, with every step written down.

  python3 harness2/run.py "거래처 등록 화면 만들어줘"
  python3 harness2/run.py --definition runs/<run>/1-define/accepted.json     # checks + apply again, no model
  python3 harness2/run.py --dry "..."                                        # stop before applying

Each run is a folder: what the model was given and answered, the accepted definition, every check and
its outcome, what was applied. Nothing here knows about particular screens or fields.
"""
import argparse
import re
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import checks
import flows
import define
from framework import Framework, app_url

RUNS = Path(__file__).resolve().parent / 'runs'
TRIAL = 'trial_'


def commit(result, message, model=True):
    """The last step of a request that succeeded: what it made is written into the project's files and committed to its git,
    one commit per request, in the request's own words. A failure here does not undo the request - it is said, and the next
    commit (or "커밋해줘") carries the change."""
    try:
        import llm
        import release
        from sites import site
        import project_git
        author = (f"{project_git.MODEL_AUTHOR[0]} ({llm.model_id()})", project_git.MODEL_AUTHOR[1]) if model else None
        recorded = release.record(site().root, message, author=author, site_only=True)
        result['commit'] = recorded.get('commit')
        if recorded.get('pushed') not in (None, True):
            result['commit_note'] = '원격 저장소에는 올리지 못했습니다: ' + str(recorded['pushed'])
    except Exception as problem:
        result['commit_note'] = '깃에 기록하지 못했습니다: ' + str(problem)[:200]
    return result


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


def run(request=None, definition_file=None, dry=False, force=False, part_of=None):
    folder = RUNS / time.strftime('%Y%m%d-%H%M%S')
    folder.mkdir(parents=True)
    framework = Framework()
    result = {'request': request, 'folder': str(folder)}
    started = time.time()
    mark = checks.high_water(framework) if part_of is None else None      # a step is cleaned up by the request it is part of
    try:
        if request and not definition_file and re.match(r'\s*업무\s*흐름', request):
            # A business flow, not a screen: registered (after running it end to end), shown or removed.
            result.update(flows.handle(request, framework))
            if result.get('changed') and not dry and part_of is None:
                commit(result, request, model=False)
            return result
        if definition_file:
            proposal = json.loads(Path(definition_file).read_text(encoding='utf-8'))
            written = proposal['definition']             # goes the same way as a model's answer: the framework takes it first
            saved = define.trial_save(framework, proposal['key'], written, TRIAL, leave=('rules',))
            proposal['definition'] = define.accepted(saved, written)
        else:
            (folder / 'request.txt').write_text(request, encoding='utf-8')
            proposal = define.write(request, framework, folder / '1-define', TRIAL, allow_steps=part_of is None)
        if proposal['action'] == 'other':
            result.update(status='other', reason=proposal.get('reason', ''))
            return result
        if proposal['action'] == 'steps':
            # More than one screen: each step is a request of its own, done in order; a later step sees what the earlier ones made.
            (folder / '1-define' / 'steps.json').write_text(json.dumps(proposal['steps'], ensure_ascii=False, indent=1), encoding='utf-8')
            done = []
            for index, step in enumerate(proposal['steps'], 1):
                time.sleep(1.1)                                   # run folders are named by the second
                outcome = run(step, dry=dry, force=force, part_of=request)
                done.append(dict(outcome, step=index, request=step))
                if outcome.get('status') not in ('applied', 'checked', 'unchanged'):      # (a step whose screen already was so is done, not stuck)
                    break
            finished = len(done) == len(proposal['steps']) and done[-1].get('status') in ('applied', 'checked', 'unchanged') and any(item.get('status') in ('applied', 'checked') for item in done)
            if finished and not dry:          # a change in several steps is judged by the business flows as a whole, at its end
                passed, flowed, said = flows.judge([item['key'] for item in done if item.get('key')], framework)
                if not passed:
                    undo({'planned': proposal['steps'], 'steps': done, '_inner': True})
                    result.update(planned=proposal['steps'], steps=done, status='failed', flows=said, failed=[item for item in flowed if not item['passed']])
                    return result
                result['status'] = 'applied'
                commit(result, request)
            if not finished and not dry and any(item.get('status') == 'applied' for item in done):
                # A request either succeeds whole or leaves nothing behind (the user's rule): the steps already applied are taken back.
                done_back, said_back = undo({'planned': proposal['steps'], 'steps': done, '_inner': True})
                result['rolled_back'] = said_back if done_back else ['앞 단계를 되돌리지 못했습니다: '] + said_back
            result.update(status=('checked' if dry else 'applied') if finished else 'failed' if not dry else 'partial', steps=done, planned=proposal['steps'],
                          checks=sum(item.get('checks') or 0 for item in done), title=' → '.join(item.get('title') or '?' for item in done if item.get('title')))
            return result
        key, definition, action = proposal['key'], proposal['definition'], proposal['action']
        result['key'] = key          # known from here on, so the trial copy is removed whatever happens next
        if proposal.get('doubt'):
            result['doubt'] = proposal['doubt']
        (folder / '1-define').mkdir(exist_ok=True)
        (folder / '1-define' / 'accepted.json').write_text(json.dumps(proposal, ensure_ascii=False, indent=1), encoding='utf-8')
        def label(field):
            extra = [field.get('type', 'text')] + (['필수'] if field['required'] else []) + (['계산'] if field.get('formula') or field.get('sum') else []) \
                + ([f"{'' if field.get('min') is None else format(field['min'], 'g')}~{'' if field.get('max') is None else format(field['max'], 'g')}"] if field.get('min') is not None or field.get('max') is not None else []) \
                + ([('정수만' if field['decimals'] == 0 else f"소수 {field['decimals']}자리")] if field.get('decimals') is not None else []) + (['중복 불가'] if field.get('unique') else []) + ([{'dropdown': '목록에서 고름', 'search': '검색창', 'popup': '검색창'}[field['pick']]] if field.get('pick') else [])
            extra += [f"{when['field']}={'|'.join(when['is']) or '비어 있음'} 일 때{word}" for when, word in ((field.get('showWhen'), '만 보임'), (field.get('requiredWhen'), ' 필수'), (field.get('lockWhen'), ' 잠김')) if when]
            return f"{field['label']}({', '.join(str(item) for item in extra)})"
        result.update(action=action, key=key, title=definition['title'], fields=[label(field) for field in definition['fields']])
        if definition.get('lines'):
            result['lines'] = [label(field) for field in definition['lines']['fields']]
            limit = definition['lines']
            result['line_limit'] = (f"{limit.get('min', 1)}줄 이상" if limit.get('max') is None else (f"{limit['max']}줄만" if limit.get('min', 1) == limit['max'] else f"{limit.get('min', 1)}~{limit['max']}줄")) if (limit.get('min', 1) != 1 or limit.get('max') is not None) else ''
        if definition.get('moreLines'):
            result['more_lines'] = [{'label': more['label'], 'fields': [label(field) for field in more['fields']]} for more in definition['moreLines']]
        if definition.get('status'):
            result['statuses'] = [value['label'] for value in definition['status']['values']]
            result['actions'] = [action_['label'] for action_ in definition['status']['actions']]
        if definition.get('rules'):
            result['rules'] = [rule['message'] for rule in definition['rules']]
        if definition.get('checks'):
            result['checks_rules'] = [rule['message'] for rule in definition['checks']]
        if definition.get('limits'):
            result['limits'] = [rule['message'] for rule in definition['limits']]
        if definition.get('effects'):
            names = {action['name']: action['label'] for action in (definition.get('status') or {}).get('actions', [])}
            result['effects'] = [('등록하면 ' if effect['on'] == 'create' else names.get(effect['on'], effect['on']) + ' 하면 ')
                                 + (f"{effect['create']['entity']} 을(를) 자동으로 만든다" if effect.get('create') else f"{effect['expand']['from']} 을(를) 펼쳐 그 줄마다 {effect['expand']['into']} 을(를) 만든다" if effect.get('expand') else f"{effect['fill']['entity']} 의 수량이 다 차면 그 자료에 {effect['fill']['action']} 을(를) 한다" if effect.get('fill') else f"{effect['act']['via']} 이(가) 가리키는 자료에 {effect['act']['action']} 을(를) 한다")
                                 for effect in definition['effects']]
        if definition.get('calendar'):
            part = definition['calendar']
            result['view'] = f"달력 화면 - {part['entity']} 자료를 {part['date']}" + (f" ~ {part['end']}" if part.get('end') else '') + ' 날짜로 보여 준다'
        if definition.get('uniqueBy') or definition.get('noCycle'):
            result['layer'] = ' / '.join(filter(None, ['겹치면 안 되는 조합 ' + ', '.join('·'.join(group) for group in definition.get('uniqueBy') or []) if definition.get('uniqueBy') else '',
                                                      f"순환 금지 ({definition['noCycle']['parent']} ↔ 줄의 {definition['noCycle']['child']})" if definition.get('noCycle') else '']))
        if definition.get('stock'):
            part = definition['stock']
            result['stock'] = ('재고가 늘어난다 (줄마다 LOT, 단가 ' + (part.get('unitCost') or '없음') + ')' if part['direction'] == 'in' else '센 수량으로 그 창고의 장부를 맞춘다 (재고 실사·기초재고)' if part['direction'] == 'count' else f"재고가 {part['warehouse']} 창고에서 {part['toWarehouse']} 창고로 옮겨진다 (LOT 번호·단가 그대로)" if part['direction'] == 'move' else '재고가 줄어든다 (오래된 LOT 부터, 모자라면 거절)') + f" - 품목 {part['item']}, 수량 {part['quantity']}, 창고 {part['warehouse']}" + (f", LOT 번호 {part['lot']} (LOT 관리 품목만)" if part.get('lot') else '')
        if definition.get('stockView'):
            result['view'] = '재고 보기 화면 - ' + {'all': '현재고·LOT·수불 내역 셋 다 (탭)', 'balance': '현재고', 'lots': 'LOT', 'moves': '수불 내역'}[definition['stockView'].get('show') or 'all']
        if definition.get('take'):
            part = definition['take']
            result['view'] = f"이어받기 화면 - {part['from']} 에서 아직 남은 것을 목록으로 조회해, 고른 줄로 {part['entity']} 을(를) 만든다 (입력 폼 없이 목록에서 처리)" \
                + (f" / 상태 {', '.join(part['statuses'])} 인 건만" if part.get('statuses') else '') + (f" / 줄에서 직접 적는 값: {', '.join(part.get('ask') or (part.get('lines') or {}).get('ask') or [])}" if part.get('ask') or (part.get('lines') or {}).get('ask') else '') + (f" / 함께 넘기는 값: {', '.join(list(part.get('set') or {}) + list(part.get('lineSet') or (part.get('lines') or {}).get('set') or {}))}" if part.get('set') or part.get('lineSet') or part.get('lines') else '')
        if definition.get('tree'):
            part = definition['tree']
            result['view'] = f"트리 화면 - {part['entity']} 자료를 " + (f"{part['parent']} → {part['child']} 쌍으로 잇는다" if part.get('child') else f"{part['parent']} (상위) 아래로 묶는다")
        if definition.get('period') or definition.get('closing'):
            result['query'] = ' / '.join(filter(None, [f"처음 조회 기간: {definition['period']}" if definition.get('period') else '', ('마감과 무관' if definition['closing'] == 'none' else f"마감 기준: {definition['closing']}") if definition.get('closing') else '']))
        if definition.get('over'):
            part = definition['over']
            result['over'] = f"{part['entity']} 자료를 여는 업무 화면 - " + ('상태 ' + ', '.join(part['statuses']) + ' 인 건만' if part.get('statuses') else '모든 건') \
                + (' / 동작: ' + ', '.join(part['actions']) if part.get('actions') else ' / 동작 없음') + (' / 내용 수정 가능' if part.get('edit') else ' / 내용은 못 고침')
        separate = [action['label'] for action in (definition.get('status') or {}).get('actions', []) if action.get('separate')]
        if separate:
            result['separate'] = separate
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
            notes, blocking = ([], []) if definition.get('summary') or current['definition'].get('summary') or definition.get('dashboard') or current['definition'].get('dashboard') or definition.get('over') or current['definition'].get('over') or any(definition.get(part) or current['definition'].get(part) for part in ('calendar', 'tree', 'take', 'stockView')) else impact(framework, key, current['definition'], definition)
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
        trial_key, trial_title = define.trial_name(key, TRIAL), definition['title'] + ' (시험)'
        # Rules point at other entities by their real keys, so they are checked after publishing (and undone if they fail).
        # Effects are left out of the trial as well: they would make and change records of real entities while the trial is checked.
        # A field that points at this same screen (a parent department) points at the trial copy while it is the trial that is checked.
        checked = define.repoint(definition, key, trial_key)
        trial = {name: value for name, value in checked.items() if name not in ('rules', 'effects')}
        framework.save_definition(trial_key, dict(trial, title=trial_title), 'DRAFT')
        data = (checks.stock_view_checks if definition.get('stockView') else checks.take_checks if definition.get('take') else checks.view_checks if definition.get('calendar') or definition.get('tree') else checks.over_checks if definition.get('over') else checks.dashboard_checks if definition.get('dashboard') else checks.summary_checks if definition.get('summary') else checks.record_checks)(trial_key, checked, framework)
        screen = checks.screen_checks(trial_title, definition, folder / '2-check', app_url())
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
        if definition.get('rules') or definition.get('effects'):
            ruled = checks.rule_checks(key, definition, framework) if definition.get('rules') else checks.Report()
            if definition.get('effects') and ruled.passed:
                ruled.results += checks.effect_checks(key, definition, framework).results
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
        if part_of is None:          # the business flows this screen is part of, run end to end with the screens as they are now
            passed, flowed, said = flows.judge([key], framework)
            if flowed:
                results += flowed
                (folder / '2-check' / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding='utf-8')
                result.update(checks=len(results), failed=[item for item in results if not item['passed']], flows=said)
            if not passed:
                if current:
                    framework.save_definition(key, current['definition'], current['status'])
                else:
                    framework.delete_definition(key, force=True)
                result['status'] = 'failed'
                return result
        (folder / '3-apply').mkdir(exist_ok=True)
        (folder / '3-apply' / 'published.json').write_text(json.dumps(saved, ensure_ascii=False, indent=1), encoding='utf-8')
        # What was there before, kept with the run: this is what "undo" puts back.
        (folder / '3-apply' / 'before.json').write_text(json.dumps(current, ensure_ascii=False, indent=1), encoding='utf-8')
        result.update(status='applied', program=saved['programCode'], revision=saved['revision'], created=current is None)
        return result
    except Exception as problem:
        result.update(status='error', error=str(problem)[:600])
        return result
    finally:
        if result.get('key'):
            framework.delete_definition(define.trial_name(result['key'], TRIAL), force=True)   # the trial copy never outlives the run
        pending, checks.LEFTOVER[:] = list(checks.LEFTOVER), []
        still = [item for item in checks.sweep(framework, pending) if not item[0].startswith(TRIAL)]
        checks.LEFTOVER[:] = []
        if mark is not None:
            still = checks.clear_since(framework, mark, framework.username)
        if still:
            result['leftover_rows'] = still
        if result.get('status') == 'applied' and part_of is None:      # a step of a larger request is committed with the whole request
            commit(result, request)
        result['seconds'] = round(time.time() - started, 1)
        (folder / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')


def undo(result):
    """Take back what a request applied: a changed screen gets its earlier definition again, a new screen is removed.
    Steps are undone last first. Refused (with the reason) when the screen was changed again afterwards, or when a new
    screen already holds records or is used by another screen - nothing is forced. Returns (done, lines of plain words)."""
    framework, lines, done = Framework(), [], True
    parts = [item for item in result.get('steps', [])] if result.get('planned') else [result]
    for item in reversed([part for part in parts if part.get('status') == 'applied']):
        key, title = item['key'], item.get('title') or item['key']
        now = next((one for one in framework.definitions() if one['key'] == key), None)
        if now is None:
            lines.append(f'{title}: 이미 없습니다.')
            continue
        if now['revision'] != item.get('revision'):
            lines.append(f'{title}: 이 요청 뒤에 화면이 또 바뀌어서 되돌리지 않았습니다. 더 최근 요청부터 되돌려야 합니다.')
            done = False
            break
        before = Path(item['folder']) / '3-apply' / 'before.json'
        earlier = json.loads(before.read_text(encoding='utf-8')) if before.exists() else None
        try:
            if item.get('created') or earlier is None:
                code, answer = framework.delete_definition(key)
                if code != 200:
                    raise RuntimeError((answer or {}).get('detail') or str(answer))
                lines.append(f'{title}: 새로 만든 화면을 없앴습니다.')
            else:
                framework.save_definition(key, define.clean(earlier['definition']), earlier['status'])
                lines.append(f'{title}: 이 요청 전의 모습으로 되돌렸습니다.')
        except Exception as problem:
            lines.append(f'{title}: 되돌리지 못했습니다 - {str(problem)[:200]}')
            done = False
            break
    if not lines:
        lines, done = ['되돌릴 것이 없습니다 (적용된 것이 없는 요청입니다).'], False
    if done and not result.get('_inner'):      # undoing is a change too: the business flows it touches must still run end to end
        keys = [part['key'] for part in parts if part.get('status') == 'applied' and part.get('key')]
        passed, _, said = flows.judge(keys, framework)
        if not passed:
            for item in [part for part in parts if part.get('status') == 'applied']:      # put back what the request had applied
                published = Path(item['folder']) / '3-apply' / 'published.json'
                if published.exists():
                    again = json.loads(published.read_text(encoding='utf-8'))
                    framework.save_definition(item['key'], define.clean(again['definition']), again.get('status', 'PUBLISHED'))
            return False, lines + said + ['되돌리면 업무 흐름이 깨져서, 되돌린 것을 다시 원래대로 해 두었습니다. 흐름을 바꾸려면 업무 흐름도 함께 바꿔야 합니다.']
    if done and not result.get('_inner'):
        noted = commit({}, '되돌림: ' + str(result.get('request') or result.get('title') or '')[:60], model=False)
        if noted.get('commit'):
            lines.append(f"깃에 기록했습니다 ({noted['commit'][:7]}).")
        elif noted.get('commit_note'):
            lines.append('⚠ ' + noted['commit_note'])
    return done, lines


def say(result):
    """The outcome in plain words."""
    if result.get('status') == 'flow':
        return '\n'.join(result.get('lines', [])) + (f"\n깃에 기록했습니다 ({result['commit'][:7]})." if result.get('commit') else '')
    if result.get('planned'):
        steps, planned = result.get('steps', []), result['planned']
        applied = [item for item in steps if item.get('status') in ('applied', 'checked')]
        lines = [f"{len(planned)}단계로 나눠 처리했습니다." if result['status'] in ('applied', 'checked') else f"{len(planned)}단계 중 {len(applied)}단계까지 됐고, {len(applied) + 1}단계에서 멈췄습니다."]
        for index, text in enumerate(planned, 1):
            item = next((one for one in steps if one['step'] == index), None)
            mark = '하지 않음' if item is None else {'applied': '적용', 'checked': '검사 통과', 'unchanged': '이미 그렇게 되어 있음'}.get(item.get('status'), '멈춤')
            lines.append(f'\n[{index}단계: {mark}] {text}')
            if item is not None:
                lines += ['  ' + line for line in say(item).split('\n') if line and not line.startswith('기록:')]
        if result.get('rolled_back'):
            lines.append('\n요청 전체가 끝나지 않아 앞 단계에서 적용한 것도 되돌렸습니다 (실패한 요청은 아무것도 남기지 않습니다).')
        lines.append(f"\n기록: {result['folder']}")
        return '\n'.join(lines)
    lines = []
    status = result.get('status')
    if result.get('title'):
        lines.append(f"{'새 화면' if result.get('action') == 'create' else '화면 수정'}: {result['title']}  ({result['key']})")
        if result.get('over'):
            lines.append('업무 화면: ' + result['over'])
        if result.get('view'):
            lines.append(result['view'])
        if result.get('query'):
            lines.append(result['query'])
        elif result.get('panels'):
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
        elif result.get('fields'):          # a screen over another entity (take-over, calendar, tree) has no fields of its own
            lines.append(('위쪽 항목: ' if result.get('lines') else '항목: ') + ', '.join(result.get('fields', [])))
        if result.get('lines'):
            lines.append('줄 표 항목: ' + ', '.join(result['lines']) + (f"  [{result['line_limit']}]" if result.get('line_limit') else ''))
        if result.get('stock'):
            lines.append('재고: ' + result['stock'])
        if result.get('layer'):
            lines.append('조합 기준 정보: ' + result['layer'])
        for more in result.get('more_lines') or []:
            lines.append(f"줄 표 {more['label']} 항목: " + ', '.join(more['fields']))
        if result.get('statuses'):
            lines.append('상태: ' + ' → '.join(result['statuses']) + ' / 동작: ' + ', '.join(result.get('actions', [])))
        if result.get('print'):
            lines.append('출력 양식: ' + result['print'])
        if result.get('separate'):
            lines.append('업무 화면에서만 하는 동작: ' + ', '.join(result['separate']))
        for rule in result.get('checks_rules', []):
            lines.append('비교 규칙: ' + rule)
        for rule in result.get('limits', []):
            lines.append('한도: ' + rule)
        for rule in result.get('effects', []):
            lines.append('자동 처리: ' + rule)
        for rule in result.get('rules', []):
            lines.append('규칙: ' + rule)
    if result.get('action') == 'change':
        lines.append('바뀐 점:' if result.get('changes') else '바뀐 점: 없음')
        for note in result.get('changes', []):
            lines.append('  - ' + note)
    if result.get('doubt'):
        lines.append('⚠ 확인해 볼 점: ' + result['doubt'])
    for note in result.get('impact', []):
        lines.append('· ' + note)
    if status == 'applied':
        lines.append(f"검사 {result['checks']}개 통과 → 적용했습니다. ({result['seconds']}초)")
        if result.get('commit'):
            lines.append(f"깃에 기록했습니다 ({result['commit'][:7]}).")
        if result.get('commit_note'):
            lines.append('⚠ ' + result['commit_note'])
    elif status == 'checked':
        lines.append(f"검사 {result['checks']}개 통과. 적용은 하지 않았습니다(--dry).")
    elif status == 'unchanged':
        lines.append('적용하지 않았습니다. 요청을 반영한 변화가 없습니다(이미 그렇게 되어 있거나, 요청을 이해하지 못했습니다).')
    elif status == 'needs_decision':
        lines.append('적용하지 않았습니다. 먼저 정해야 할 것:')
        lines += ['  - ' + item for item in result['needs_decision']]
    elif status == 'failed':
        lines.append(f"검사 {result.get('checks', len(result.get('failed', [])))}개 중 {len(result['failed'])}개 실패. 적용하지 않았습니다:")
        lines += [f"  - {item['description']}: {item['detail']}" for item in result['failed']]
        lines += ['  ' + line for line in result.get('flows') or []]
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
