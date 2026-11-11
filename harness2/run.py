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
        else:
            (folder / 'request.txt').write_text(request, encoding='utf-8')
            proposal = define.write(request, framework, folder / '1-define', TRIAL)
        if proposal['action'] == 'other':
            result.update(status='other', reason=proposal.get('reason', ''))
            return result
        key, definition, action = proposal['key'], proposal['definition'], proposal['action']
        (folder / '1-define').mkdir(exist_ok=True)
        (folder / '1-define' / 'accepted.json').write_text(json.dumps(proposal, ensure_ascii=False, indent=1), encoding='utf-8')
        result.update(action=action, key=key, title=definition['title'], fields=[f"{field['label']}({field.get('type', 'text')}{', 필수' if field['required'] else ''})" for field in definition['fields']])

        current = next((item for item in framework.definitions() if item['key'] == key), None)
        if current and action == 'change':
            notes, blocking = impact(framework, key, current['definition'], definition)
            result.update(impact=notes, needs_decision=blocking)
            if blocking and not force:
                result['status'] = 'needs_decision'
                return result

        # Checks run on a trial copy: a draft with its own key and title, which the menus never show.
        trial_key, trial_title = TRIAL + key, definition['title'] + ' (시험)'
        framework.save_definition(trial_key, dict(definition, title=trial_title), 'DRAFT')
        data = checks.data_checks(trial_key, definition, framework)
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
        result['seconds'] = round(time.time() - started, 1)
        (folder / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')


def say(result):
    """The outcome in plain words."""
    lines = []
    status = result.get('status')
    if result.get('title'):
        lines.append(f"{'새 화면' if result.get('action') == 'create' else '화면 수정'}: {result['title']}  ({result['key']})")
        lines.append('항목: ' + ', '.join(result.get('fields', [])))
    for note in result.get('impact', []):
        lines.append('· ' + note)
    if status == 'applied':
        lines.append(f"검사 {result['checks']}개 통과 → 적용했습니다. ({result['seconds']}초)")
    elif status == 'checked':
        lines.append(f"검사 {result['checks']}개 통과. 적용은 하지 않았습니다(--dry).")
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
