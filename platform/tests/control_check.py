#!/usr/bin/env python3
"""A check of the whole control path, on a project made for it and removed again.

Everything is asked of the running platform through ctl.py, exactly as a person or an agent would; git and the
database are only looked at to see what really happened. It makes a project, applies a screen and a change to it,
and then walks the controls: every request commits, taking a record back changes the screen back, work spaces carry
their own screens, what is changed outside a request shows as unrecorded, files changed by hand are followed by
"sync", records reach a remote, and the project goes away without a trace.

  python3 tests/control_check.py            about a minute
  python3 tests/control_check.py --ui       also clicks through the change-history page in a browser (record, take back, work spaces, remote)
  python3 tests/control_check.py --pack     also builds and trial-installs the project's setup packs (slower, 220MB)
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SLUG, TITLE = 'ctl-check', '컨트롤 점검'
results = []


def ctl(*args, project=True):
    done = subprocess.run([sys.executable, str(HERE.parent / 'ctl.py'), *args, *(['-p', SLUG] if project else [])], capture_output=True, text=True, timeout=1800)
    try:
        return json.loads(done.stdout)
    except ValueError:
        return {'ok': False, 'error': (done.stdout + done.stderr)[-400:]}


def check(what, passed, detail=''):
    results.append((what, bool(passed)))
    print(('  통과  ' if passed else '  실패  ') + what + ('' if passed or not detail else f'\n          {str(detail)[:500]}'), flush=True)
    return passed


def fields(key='check_item'):
    found = next((screen for screen in ctl('screens').get('screens', []) if screen['key'] == key), None)
    return found['fields'] if found else None


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT / 'projects' / SLUG, capture_output=True, text=True).stdout.strip()


def definition(extra=()):
    base = [{'name': 'itemCode', 'label': '품목 코드', 'type': 'text', 'required': True, 'unique': True, 'search': True},
            {'name': 'itemName', 'label': '품목명', 'type': 'text', 'required': True, 'search': True},
            {'name': 'price', 'label': '단가', 'type': 'number', 'min': 0}]
    return {'action': 'create', 'key': 'check_item', 'definition': {'title': '점검 품목 등록', 'keywords': ['점검'], 'fields': base + list(extra)}}


def main():
    global SLUG
    with_pack, with_ui = '--pack' in sys.argv, '--ui' in sys.argv
    work = Path(tempfile.mkdtemp(prefix='control-check-'))
    for stale in ('ctl-check', 'ctl-moved'):
        if any(item['slug'] == stale for item in ctl('projects', project=False).get('projects', [])):
            ctl('remove', stale, '--confirm', stale, project=False)
    try:
        made = ctl('create', SLUG, TITLE, project=False)
        if not check('프로젝트 만들기', made.get('ok'), made):
            return
        status = ctl('status')
        check('새 프로젝트: 화면 0개, 기록 안 된 것 없음, 작업 공간 main', status.get('ok') and fields() is None and status['git']['branch'] == 'main' and not status['unrecorded']['site'], status)

        first = work / 'first.json'
        first.write_text(json.dumps(definition(), ensure_ascii=False))
        applied = ctl('apply', '점검 품목 등록 화면 만들어줘', '--file', str(first))
        check('화면 적용 (검사 통과 후 개발 사이트 반영)', applied.get('ok') and fields() == ['품목 코드', '품목명', '단가'], applied.get('said') or applied)
        check('요청이 성공하면 그 요청 문장으로 커밋된다', git('log', '-1', '--format=%s') == '점검 품목 등록 화면 만들어줘' and not git('status', '--porcelain'), git('log', '-3', '--format=%s'))

        second = work / 'second.json'
        second.write_text(json.dumps(dict(definition([{'name': 'memo', 'label': '비고', 'type': 'memo'}]), action='change'), ensure_ascii=False))
        changed = ctl('apply', '점검 품목 등록에 비고 추가해줘', '--file', str(second))
        check('화면 수정 적용과 커밋', changed.get('ok') and fields() == ['품목 코드', '품목명', '단가', '비고'] and git('log', '-1', '--format=%s') == '점검 품목 등록에 비고 추가해줘', changed.get('said') or changed)

        undone = ctl('undo')
        check('기록 취소: 깃에 취소 커밋이 생기고 화면이 따라 되돌아간다', undone.get('ok') and fields() == ['품목 코드', '품목명', '단가'] and git('log', '-1', '--format=%s').startswith('취소:'), undone.get('said') or undone)

        branch = ctl('branch', 'trial', '--create')
        again = ctl('apply', '점검 품목 등록에 비고 추가해줘', '--file', str(second))
        check('작업 공간을 만들고 그 안에서 화면을 바꾼다', branch.get('ok') and again.get('ok') and git('branch', '--show-current') == 'trial' and '비고' in (fields() or []), again.get('said') or branch)
        back = ctl('branch', 'main')
        check('main 으로 옮기면 그 변경이 화면에서 사라진다', back.get('ok') and fields() == ['품목 코드', '품목명', '단가'], back.get('said') or back)
        forth = ctl('branch', 'trial')
        check('작업 공간으로 돌아가면 다시 나타난다', forth.get('ok') and '비고' in (fields() or []), forth.get('said') or forth)
        ctl('branch', 'main')

        # something changed outside a request: a common code added straight in the development database
        site = next(item for item in ctl('projects', project=False)['projects'] if item['slug'] == SLUG)['site']
        subprocess.run(['docker', 'exec', 'mdi-db', 'psql', '-U', 'mdi', '-d', site['db'], '-qc',
                        "INSERT INTO sys_code_groups (group_code, group_name) VALUES ('CHECK_KIND', '점검 종류'); INSERT INTO sys_codes (group_code, code, code_name, sort_order) VALUES ('CHECK_KIND', 'A', '가', 1)"], capture_output=True)
        check('요청 밖에서 바뀐 것은 "기록 안 된 변경"으로 보인다', ctl('status')['unrecorded']['site'] == ['공통 코드'], ctl('status').get('unrecorded'))
        committed = ctl('commit', '-m', '점검 종류 코드 추가')
        codes = lambda: subprocess.run(['docker', 'exec', 'mdi-db', 'psql', '-U', 'mdi', '-d', site['db'], '-Atc', "select count(*) from sys_codes where group_code = 'CHECK_KIND'"], capture_output=True, text=True).stdout.strip()
        check('커밋하면 기록되고 남은 것이 없다', committed.get('ok') and not ctl('status')['unrecorded']['site'] and git('log', '-1', '--format=%s') == '점검 종류 코드 추가', committed.get('said') or committed)
        check('기록할 것이 없을 때의 커밋은 그렇게 말한다', '기록할 변경이 없습니다' in ctl('commit').get('said', ''))

        uncoded = ctl('undo')
        check('코드를 추가한 기록을 취소하면 그 코드가 없어진다', uncoded.get('ok') and codes() == '0' and not ctl('status')['unrecorded']['site'], uncoded.get('said') or ctl('status').get('unrecorded'))

        # a person arranges a menu (straight in the database here); it is recorded, and taking that record back takes the menu away
        menus = lambda: subprocess.run(['docker', 'exec', 'mdi-db', 'psql', '-U', 'mdi', '-d', site['db'], '-Atc', "select count(*) from sys_menus where menu_name = '점검 품목'"], capture_output=True, text=True).stdout.strip()
        subprocess.run(['docker', 'exec', 'mdi-db', 'psql', '-U', 'mdi', '-d', site['db'], '-qc',
                        "INSERT INTO sys_menus (module_code, program_code, menu_name, sort_order, menu_type) SELECT 'SYSTEM', program_code, '점검 품목', 1, 'PROGRAM' FROM app_definitions WHERE entity_key = 'check_item'"], capture_output=True)
        arranged = ctl('commit', '-m', '점검 품목 메뉴 편성')
        check('메뉴 편성도 기록된다', arranged.get('ok') and menus() == '1' and '메뉴 편성' in arranged.get('said', ''), arranged.get('said') or arranged)
        unarranged = ctl('undo')
        check('그 기록을 취소하면 메뉴 편성도 따라 되돌아간다', unarranged.get('ok') and menus() == '0' and not ctl('status')['unrecorded']['site'], unarranged.get('said') or ctl('status').get('unrecorded'))

        # files changed by hand (git used directly, outside the platform): sync brings the site along
        target = git('log', '--format=%H', '--grep', '점검 품목 등록 화면 만들어줘', '-1')
        subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', 'revert', '--no-edit', target], cwd=ROOT / 'projects' / SLUG, capture_output=True)
        synced = ctl('sync')
        check('손으로 깃을 바꾼 뒤 "깃 상태로 맞추기": 화면이 사라진다', synced.get('ok') and fields() is None, synced.get('said') or synced)
        check('맞춘 뒤에는 기록 안 된 변경이 없다', not ctl('status')['unrecorded']['site'], ctl('status').get('unrecorded'))

        bare = work / 'remote.git'
        subprocess.run(['git', 'init', '-q', '--bare', str(bare)])
        check('잘못된 원격 주소는 거절한다', not ctl('remote', 'ftp://nowhere/x').get('ok'))
        check('원격이 없을 때 올리기는 방법을 알려 주며 거절한다', '연결' in str(ctl('push')))
        linked, pushed = ctl('remote', str(bare)), ctl('push')
        there = subprocess.run(['git', '--git-dir', str(bare), 'log', '-1', '--format=%s', 'main'], capture_output=True, text=True).stdout.strip()
        check('원격 저장소 연결과 올리기: 기록이 원격에 있다', linked.get('ok') and pushed.get('ok') and there == git('log', '-1', '--format=%s'), pushed.get('said') or pushed)
        check('변경 이력을 읽을 수 있다', ctl('log').get('ok') and '작업 공간 main' in ctl('log').get('said', ''))

        # another name: the one people see, then the English one (folder, database and server move with it)
        titled = ctl('rename', SLUG, '--title', '점검 새 이름', project=False)
        seen = subprocess.run(['docker', 'exec', 'mdi-db', 'psql', '-U', 'mdi', '-d', site['db'], '-Atc', "select setting_value from sys_settings where setting_key='system_name'"], capture_output=True, text=True).stdout.strip()
        check('보이는 이름 바꾸기: 플랫폼과 그 프로젝트의 화면 이름이 바뀐다', titled.get('ok') and titled['project']['site']['title'] == '점검 새 이름' and seen == '점검 새 이름', titled)
        commits = git('rev-list', '--count', 'HEAD')
        moved = ctl('rename', SLUG, '--slug', 'ctl-moved', project=False)
        if check('영문 이름 바꾸기', moved.get('ok') and moved['project']['name'] == 'ctl-moved', moved):
            SLUG = 'ctl-moved'
            made = {'project': moved['project']}
            site = moved['project']['site']
            names = subprocess.run(['docker', 'ps', '--format', '{{.Names}}'], capture_output=True, text=True).stdout
            bases = subprocess.run(['docker', 'exec', 'mdi-db', 'psql', '-U', 'mdi', '-d', 'postgres', '-Atc', "select string_agg(datname, ',' order by datname) from pg_database where datname like 'mdi_ctl_%'"], capture_output=True, text=True).stdout.strip()
            check('폴더·데이터베이스·서버가 새 이름으로 옮겨졌다', (ROOT / 'projects/ctl-moved/.git').is_dir() and not (ROOT / 'projects/ctl-check').exists() and 'mdi-ctl-moved-api' in names and 'mdi-ctl-check-api' not in names
                  and bases == 'mdi_ctl_moved,mdi_ctl_moved_test', f'{names.split()} {bases}')
            check('깃 기록과 화면은 그대로다', git('rev-list', '--count', 'HEAD') == commits and ctl('status').get('ok') and isinstance(ctl('screens').get('screens'), list), ctl('status'))
            fifth = work / 'fifth.json'
            fifth.write_text(json.dumps(definition(), ensure_ascii=False))
            after = ctl('apply', '점검 품목 등록 화면 만들어줘', '--file', str(fifth))
            check('이름을 바꾼 뒤에도 요청이 그 프로젝트에서 진행된다', after.get('ok') and fields() == ['품목 코드', '품목명', '단가'], after.get('said') or after)

        if with_ui:
            # The same controls from the change-history page, clicked in a browser; judged here by what git and the database then hold.
            ui_remote = work / 'ui-remote.git'
            subprocess.run(['git', 'init', '-q', '--bare', str(ui_remote)])
            subprocess.run(['docker', 'exec', 'mdi-db', 'psql', '-U', 'mdi', '-d', site['db'], '-qc',
                            "INSERT INTO sys_code_groups (group_code, group_name) VALUES ('UI_KIND', '화면 점검'); INSERT INTO sys_codes (group_code, code, code_name, sort_order) VALUES ('UI_KIND', 'A', '가', 1)"], capture_output=True)
            ran = subprocess.run(['node', str(HERE / 'history_page_check.cjs'), made['project']['id'], str(ui_remote)], capture_output=True, text=True, timeout=600)
            steps = {}
            for line in ran.stdout.splitlines():
                try:
                    step = json.loads(line); steps[step['step']] = step
                except ValueError:
                    pass
            ui_codes = lambda: subprocess.run(['docker', 'exec', 'mdi-db', 'psql', '-U', 'mdi', '-d', site['db'], '-Atc', "select count(*) from sys_codes where group_code = 'UI_KIND'"], capture_output=True, text=True).stdout.strip()
            ok = lambda name: steps.get(name, {}).get('ok')
            why = lambda name: steps.get(name, steps.get('error', {})).get('detail', ran.stderr[-300:])
            check('화면: 변경 이력 목록이 보인다', ok('list'), why('list'))
            check('화면: 기록 안 된 변경이 보이고 "기록하기"로 기록된다', ok('unrecorded-shown') and ok('record') and '화면에서 기록한 변경' in git('log', '-5', '--format=%s'), why('record'))
            check('화면: "이 변경 취소하기"로 취소되고 사이트가 따라간다', ok('undo') and ui_codes() == '0', why('undo'))
            check('화면: 작업 공간을 만들고 main 으로 돌아온다', ok('branch-create') and ok('branch-back') and 'ui-trial' in git('branch') and git('branch', '--show-current') == 'main', why('branch-back'))
            pushed_there = subprocess.run(['git', '--git-dir', str(ui_remote), 'log', '-1', '--format=%s', 'main'], capture_output=True, text=True).stdout.strip()
            check('화면: 원격 주소 연결과 "원격에 올리기"', ok('remote') and ok('push') and pushed_there == git('log', '-1', '--format=%s'), why('push'))

        if with_pack:
            fresh = work / 'third.json'
            fresh.write_text(json.dumps(definition(), ensure_ascii=False))
            ctl('apply', '점검 품목 등록 화면 만들어줘', '--file', str(fresh))
            packed = ctl('pack')
            files = (packed.get('result') or {}).get('files') or {}
            check('셋업 팩: 프로젝트 이름으로 두 개가 만들어지고 빈 환경 설치를 통과한다', packed.get('ok') and all(Path(item['file']).is_file() and item['name'].startswith(SLUG + '-setup-') for item in files.values()) and len(files) == 2, packed.get('said') or packed)
            check('팩을 만든 뒤 "현재 버전"이다', ctl('status').get('current') is True)
    finally:
        removed = ctl('remove', SLUG, '--confirm', SLUG, project=False)
        left = subprocess.run(['docker', 'ps', '-a', '--format', '{{.Names}}'], capture_output=True, text=True).stdout
        bases = subprocess.run(['docker', 'exec', 'mdi-db', 'psql', '-U', 'mdi', '-d', 'postgres', '-Atc', "select count(*) from pg_database where datname like 'mdi_ctl_%'"], capture_output=True, text=True).stdout.strip()
        check('프로젝트 지우기: 폴더, 서버, 데이터베이스가 남지 않는다', removed.get('ok') and not (ROOT / 'projects' / SLUG).exists() and f'mdi-{SLUG}-api' not in left and bases == '0', removed)
        shutil.rmtree(Path.home() / '.local/share/local-workshop/packs' / SLUG, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)
    failed = [what for what, passed in results if not passed]
    print(f'\n{len(results) - len(failed)}/{len(results)} 통과' + ('' if not failed else ' · 실패: ' + '; '.join(failed)))
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
