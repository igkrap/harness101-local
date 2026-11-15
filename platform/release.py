"""Record what was made and turn it into a setup pack for operation, on request ("커밋해줘", "셋업 팩 만들어줘", "운영에 배포해줘").

Screens are definitions kept in the development database, so recording means writing them out as files in the
project (release/) and committing them to the project's git.

A setup pack is everything an operating copy needs, in one folder (and one zip): the server program, the built
screens, the release/ files, a docker-compose.yml with its own database, and install/update scripts. The server
applies release/ by itself when it starts (ReleaseLoader), so installing is "unpack, run install.sh" on any machine
with Docker, and updating is "unpack the newer pack over it, run update.sh". An operating copy's own records,
users, roles and permissions are never touched by a pack.

Every pack is tried before it is handed over: it is installed from nothing in a throwaway copy, checked (the server
starts, every screen was accepted, the administrator can sign in) and removed again.

"""
import sys
import hashlib
from contextlib import contextmanager
import http.cookiejar
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import backend_deploy as live
import project_git as vcs
import windows_pack
from sites import site      # the project in hand: every name below comes from it

TRIAL_PORT = 5390
VENDOR = live.SHARE / 'vendor/windows'      # the Windows runtime pieces (Java, PostgreSQL ...), downloaded once
PWSH = live.SHARE / 'tools/pwsh/pwsh'        # PowerShell, to parse-check the Windows scripts (they cannot be run on this machine)
APP_IMAGE = 'eclipse-temurin:17-jre'


class ReleaseError(RuntimeError):
    pass


import threading
_holding = threading.local()


@contextmanager
def exclusive(what):
    """One thing at a time changes a project's git and development site, whoever asks (a page, the request box, a command line)."""
    import fcntl
    held = _holding.__dict__.setdefault('projects', set())
    if site().slug in held:        # this same piece of work already has the project (taking back records first, a pack records first)
        yield
        return
    site().state.mkdir(parents=True, exist_ok=True)
    with open(site().state / 'control.lock', 'a+') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.seek(0)
            raise ReleaseError(f"다른 작업이 이 프로젝트의 깃·배포를 쓰고 있어 {what}을(를) 하지 못했습니다 ({handle.read().strip()[:80] or '진행 중'}). 잠시 뒤 다시 하세요.")
        handle.seek(0); handle.truncate(); handle.write(f'{what} {time.strftime("%H:%M:%S")}'); handle.flush()
        held.add(site().slug)
        try:
            yield
        finally:
            held.discard(site().slug)
            handle.seek(0); handle.truncate()
            fcntl.flock(handle, fcntl.LOCK_UN)


def _psql(db, sql, rows=False):
    """SQL goes through stdin (never argv). rows: the answer as a list of JSON values, one per line."""
    result = subprocess.run(['docker', 'exec', '-i', live.DB_CONTAINER, 'psql', '-U', live.DB_USER, '-d', db, '-v', 'ON_ERROR_STOP=1', '-q', '-At'],
                            input=sql, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise ReleaseError('DB 작업 실패: ' + result.stderr[-400:])
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()] if rows else result.stdout


def _literal(value):
    return "'" + json.dumps(value, ensure_ascii=False).replace("'", "''") + "'"


def _database_exists(name):
    return bool(_psql('postgres', f"SELECT 1 FROM pg_database WHERE datname = '{name}'").strip())


# ---- what development holds, as files ----

def _definitions(db):
    return {row['key']: row for row in _psql(db, """
        SELECT json_build_object('key', entity_key, 'programCode', program_code, 'definition', definition::jsonb)
        FROM app_definitions WHERE status = 'PUBLISHED' ORDER BY entity_key""", rows=True)}


def _menus(db):
    """Modules and the menu tree. A menu is told apart by its program, a folder by its place (module / names down to it)."""
    modules = _psql(db, "SELECT row_to_json(m) FROM sys_modules m ORDER BY sort_order, module_code", rows=True)
    rows = _psql(db, "SELECT row_to_json(m) FROM sys_menus m ORDER BY sort_order, menu_id", rows=True)
    by_id = {row['menu_id']: row for row in rows}

    def place(row):
        names, at = [], row
        while at.get('parent_id') in by_id:
            at = by_id[at['parent_id']]
            names.insert(0, at['menu_name'])
        return names
    menus = [{'module': row['module_code'], 'folders': place(row), 'type': row['menu_type'], 'program': row['program_code'], 'name': row['menu_name'],
              'sort': row['sort_order'], 'enabled': row['enabled'], 'icon': row.get('icon')} for row in rows]
    menus.sort(key=lambda item: (len(item['folders']), item['module'], item['folders'], item['sort'], item['name']))
    return {'modules': modules, 'menus': menus}


def _codes(db):
    return {'groups': _psql(db, "SELECT row_to_json(g) FROM sys_code_groups g ORDER BY group_code", rows=True),
            'codes': _psql(db, "SELECT row_to_json(c) FROM sys_codes c ORDER BY group_code, sort_order, code", rows=True)}


def _dump(value):
    return json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + '\n'


def _bundle():
    """What the development site holds, in the written form of release/ (file name -> text)."""
    out = {f'definitions/{key}.json': _dump(row) for key, row in _definitions(site().db).items()}
    settings = _psql(site().db, "SELECT row_to_json(s) FROM sys_settings s WHERE setting_key NOT LIKE 'release\\_%' ORDER BY setting_key", rows=True)
    out.update({'codes.json': _dump(_codes(site().db)), 'menus.json': _dump(_menus(site().db)), 'settings.json': _dump(settings)})
    return out


def unrecorded(project):
    """What the development site holds that git does not yet: screens made or changed outside a request (through the
    administrator's screens or API), menus arranged, codes added - and files changed by hand. Nothing is written."""
    folder, held = Path(project) / 'release', _bundle()
    names = {'codes.json': '공통 코드', 'menus.json': '메뉴 편성', 'settings.json': '시스템 설정'}
    out = []
    for name, text in held.items():
        path = folder / name
        if not path.is_file() or path.read_text(encoding='utf-8') != text:
            out.append(names.get(name) or json.loads(text)['definition']['title'])
    if (folder / 'definitions').is_dir():
        out += [f'{path.stem} (지워진 화면)' for path in (folder / 'definitions').glob('*.json') if f'definitions/{path.name}' not in held]
    dirty = [line[3:].strip().strip('"') for line in vcs._git(project, 'status', '--porcelain', '--untracked-files=all', raw=True).splitlines() if line.strip()] if (Path(project) / '.git').exists() else []
    return {'site': out, 'files': [path for path in dirty if not path.startswith('release/')]}


def write_bundle(project):
    """Write development's definitions, common codes and menus under release/ (files that are no longer true are removed)."""
    folder = Path(project) / 'release'
    (folder / 'definitions').mkdir(parents=True, exist_ok=True)
    definitions = _definitions(site().db)
    for path in (folder / 'definitions').glob('*.json'):
        if path.stem not in definitions:
            path.unlink()
    for key, row in definitions.items():
        path, text = folder / 'definitions' / f'{key}.json', _dump(row)
        if not path.is_file() or path.read_text(encoding='utf-8') != text:
            path.write_text(text, encoding='utf-8')
    settings = _psql(site().db, "SELECT row_to_json(s) FROM sys_settings s WHERE setting_key NOT LIKE 'release\\_%' ORDER BY setting_key", rows=True)
    for name, value in (('codes.json', _codes(site().db)), ('menus.json', _menus(site().db)), ('settings.json', settings)):
        path, text = folder / name, _dump(value)
        if not path.is_file() or path.read_text(encoding='utf-8') != text:
            path.write_text(text, encoding='utf-8')
    readme = folder / 'README.md'
    if not readme.is_file():
        readme.write_text('# 배포 묶음\n\n플랫폼이 커밋하거나 셋업 팩을 만들 때 개발 DB에서 뽑아 적는 파일입니다. 손으로 고치지 않습니다.\n\n'
                          '- `definitions/` 화면 정의 (화면 하나에 파일 하나)\n- `codes.json` 공통 코드\n- `menus.json` 모듈과 메뉴 편성\n- `settings.json` 시스템 이름·로고·테마 (새로 설치할 때만 쓰임)\n', encoding='utf-8')
    return definitions


def _titles(project, paths):
    out = []
    for path in paths:
        try:
            out.append(json.loads((Path(project) / path).read_text(encoding='utf-8'))['definition']['title'])
        except (OSError, ValueError, KeyError):
            out.append(Path(path).stem)
    return out


def record(project, message=None, author=None, site_only=False):
    """Write the bundle and commit every pending change of the project. Returns what was recorded (commit None = nothing new).
    site_only: only what the development site holds (release/) is recorded - the record a request ends with. Source files someone is in the
    middle of changing stay out of it, so taking that request back later (a revert of its record) cannot take their work with it.
    Another git command may be at work in the project at the same moment (the platform's own pages read its state): then it waits and tries again."""
    for attempt in range(6):
        try:
            with exclusive('기록'):
                return _record(project, message, author, site_only)
        except RuntimeError as error:
            if 'index.lock' not in str(error) or attempt == 5:
                raise
            time.sleep(1.5)


def _record(project, message=None, author=None, site_only=False):
    vcs.ensure_repo(project)
    write_bundle(project)
    changed = [line[3:].strip().strip('"') for line in vcs._git(project, 'status', '--porcelain', '--untracked-files=all', raw=True).splitlines() if line.strip()]
    screens = _titles(project, [path for path in changed if path.startswith('release/definitions/') and (Path(project) / path).is_file()])
    removed = [Path(path).stem for path in changed if path.startswith('release/definitions/') and not (Path(project) / path).is_file()]
    other = [] if site_only else [path for path in changed if not path.startswith('release/')]
    title = (message or '').strip().splitlines()[0] if (message or '').strip() else ('화면 ' + ', '.join(screens[:3]) + (f' 외 {len(screens) - 3}개' if len(screens) > 3 else '') if screens else '변경 기록')
    body = '\n'.join(filter(None, [f"화면 정의: {', '.join(screens)}" if screens else '', f"지워진 화면: {', '.join(removed)}" if removed else '',
                                   '공통 코드 변경' if 'release/codes.json' in changed else '', '메뉴 편성 변경' if 'release/menus.json' in changed else '',
                                   f'소스 파일 {len(other)}개' if other else '']))
    detail = '\n\n'.join(filter(None, [('요청: ' + message.strip()[:2000]) if message and len(message.strip()) > 72 else '', body]))
    sha = vcs.commit(project, title[:72] + ('\n\n' + detail if detail else ''), author=author or vcs.PLATFORM_AUTHOR, only=['release'] if site_only else None)
    pushed = None
    if sha and vcs.status(project).get('remote'):
        try:
            vcs.push(project)
            pushed = True
        except Exception as error:      # the record itself stands; say that it did not reach the remote
            pushed = str(error)[:200]
    return {'commit': sha, 'screens': screens, 'removed': removed, 'codes': 'release/codes.json' in changed, 'menus': 'release/menus.json' in changed,
            'source_files': len(other), 'pushed': pushed}


# ---- git as a control, not only a record ----
# The screens live in the development database; the files under release/ are their written form. Recording writes the
# files from the database. The other way round - taking a change back, moving to another work space - changes the
# files, and then the development site is brought to what the files say, so that git decides what the screens are.

CARRIED = ('rules', 'effects', 'limits')      # parts that may name a screen made later: put in with a second pass
REMOTE = re.compile(r'(https://[\w.-]+(:\d+)?/[\w./~-]+|git@[\w.-]+:[\w./~-]+|ssh://[\w.@:/~-]+|file:///[\w./~ -]+|/[\w./~ -]+\.git)')      # also a folder on this machine or a mounted disk


def _apply_menus(menus):
    """The development site's menu tree becomes what the files say: a program's menu keeps its row (so the permissions given on it stay),
    folders are matched by their place, and what the files no longer have is removed."""
    if not menus['modules']:
        return
    statements = [f"""INSERT INTO sys_modules SELECT * FROM json_populate_recordset(NULL::sys_modules, {_literal(menus['modules'])}::json)
        ON CONFLICT (module_code) DO UPDATE SET module_name = EXCLUDED.module_name, icon = EXCLUDED.icon, sort_order = EXCLUDED.sort_order, enabled = EXCLUDED.enabled;"""]
    _psql(site().db, '\n'.join(statements))
    programs = {row for row in _psql(site().db, "SELECT to_json(program_code) FROM sys_programs", rows=True)}
    current = _psql(site().db, "SELECT row_to_json(m) FROM sys_menus m", rows=True)
    by_id = {row['menu_id']: row for row in current}

    def place(row):
        names, at = [], row
        while at.get('parent_id') in by_id:
            at = by_id[at['parent_id']]
            names.insert(0, at['menu_name'])
        return tuple(names)
    folder_ids = {(row['module_code'], place(row), row['menu_name']): row['menu_id'] for row in current if row['menu_type'] == 'FOLDER'}
    program_ids = {row['program_code']: row['menu_id'] for row in current if row['menu_type'] == 'PROGRAM'}
    kept = set()
    text = lambda value: 'NULL' if value is None else "'" + str(value).replace("'", "''") + "'"
    for item in menus['menus']:              # folders come before what they hold (sorted by depth)
        folders = tuple(item['folders'])
        parent = folder_ids.get((item['module'], folders[:-1], folders[-1])) if folders else None
        if folders and parent is None:
            continue                          # its folder could not be made (should not happen)
        fields = f"module_code = {text(item['module'])}, parent_id = {parent or 'NULL'}, menu_name = {text(item['name'])}, sort_order = {int(item['sort'])}, enabled = {'TRUE' if item['enabled'] else 'FALSE'}, icon = {text(item.get('icon'))}"
        if item['type'] == 'FOLDER':
            key = (item['module'], folders, item['name'])
            if key in folder_ids:
                _psql(site().db, f"UPDATE sys_menus SET {fields} WHERE menu_id = {folder_ids[key]};")
            else:
                folder_ids[key] = int(_psql(site().db, f"""INSERT INTO sys_menus (module_code, parent_id, menu_name, sort_order, enabled, icon, menu_type)
                    VALUES ({text(item['module'])}, {parent or 'NULL'}, {text(item['name'])}, {int(item['sort'])}, {'TRUE' if item['enabled'] else 'FALSE'}, {text(item.get('icon'))}, 'FOLDER') RETURNING menu_id;""").strip())
            kept.add(folder_ids[key])
        elif item['program'] in programs:     # a screen that is not there has no menu
            if item['program'] in program_ids:
                _psql(site().db, f"UPDATE sys_menus SET {fields} WHERE menu_id = {program_ids[item['program']]};")
            else:
                program_ids[item['program']] = int(_psql(site().db, f"""INSERT INTO sys_menus (module_code, parent_id, program_code, menu_name, sort_order, enabled, icon, menu_type)
                    VALUES ({text(item['module'])}, {parent or 'NULL'}, {text(item['program'])}, {text(item['name'])}, {int(item['sort'])}, {'TRUE' if item['enabled'] else 'FALSE'}, {text(item.get('icon'))}, 'PROGRAM') RETURNING menu_id;""").strip())
            kept.add(program_ids[item['program']])
    gone = [row['menu_id'] for row in current if row['menu_id'] not in kept]
    if gone:
        _psql(site().db, f"DELETE FROM sys_menus WHERE menu_id IN ({', '.join(str(item) for item in gone)});")


def apply_files(project):
    """Bring the development site to what release/ holds. Returns what changed there, in plain words."""
    import sys
    harness = str(Path(__file__).resolve().parents[1] / 'harness2')
    if harness not in sys.path:
        sys.path.insert(0, harness)
    import define
    from framework import Framework
    folder = Path(project) / 'release'
    files = {path.stem: json.loads(path.read_text(encoding='utf-8')) for path in sorted((folder / 'definitions').glob('*.json'))} if (folder / 'definitions').is_dir() else {}
    held = _definitions(site().db)
    todo = {key: row for key, row in files.items() if key not in held or held[key]['definition'] != row['definition']}
    gone = [key for key in held if key not in files]
    lines = []
    if (folder / 'codes.json').is_file():
        codes = json.loads((folder / 'codes.json').read_text(encoding='utf-8'))
        if codes != _codes(site().db) and (codes.get('groups') or codes.get('codes')):
            # The common codes become exactly what the files say (records keep the code values they hold; a code that is gone just reads as its value).
            _psql(site().db, f"""
                INSERT INTO sys_code_groups SELECT * FROM json_populate_recordset(NULL::sys_code_groups, {_literal(codes.get('groups', []))}::json)
                ON CONFLICT (group_code) DO UPDATE SET group_name = EXCLUDED.group_name, description = EXCLUDED.description, enabled = EXCLUDED.enabled;
                INSERT INTO sys_codes SELECT * FROM json_populate_recordset(NULL::sys_codes, {_literal(codes.get('codes', []))}::json)
                ON CONFLICT (group_code, code) DO UPDATE SET code_name = EXCLUDED.code_name, sort_order = EXCLUDED.sort_order, enabled = EXCLUDED.enabled;
                DELETE FROM sys_codes c WHERE NOT EXISTS (SELECT 1 FROM json_populate_recordset(NULL::sys_codes, {_literal(codes.get('codes', []))}::json) f WHERE f.group_code = c.group_code AND f.code = c.code);
                DELETE FROM sys_code_groups g WHERE NOT EXISTS (SELECT 1 FROM json_populate_recordset(NULL::sys_code_groups, {_literal(codes.get('groups', []))}::json) f WHERE f.group_code = g.group_code);""")
            lines.append('공통 코드: 이 기록의 모습으로 바꿨습니다.')
    if not todo and not gone:
        return lines + _apply_rest(folder)
    framework = Framework()

    def put(key, definition):
        body = {'definition': define.clean(definition), 'status': 'PUBLISHED'}
        if key not in held:
            body['programCode'] = files[key].get('programCode')
        code, answer = framework.call('PUT', f'/api/system/definitions/{key}', body)
        return None if code == 200 else str((answer or {}).get('detail') or answer)[:200]
    waiting, problems = dict(todo), {}
    while waiting:
        done = []
        for key, row in waiting.items():
            problems[key] = put(key, {name: value for name, value in row['definition'].items() if name not in CARRIED})
            if problems[key] is None:
                done.append(key)
        if not done:
            break
        for key in done:
            waiting.pop(key)
            problems.pop(key)
    for key, row in todo.items():
        if key not in waiting:
            problem = put(key, row['definition']) if any(row['definition'].get(name) for name in CARRIED) else None
            lines.append(f"{row['definition']['title']}: " + ('이 기록의 모습으로 바꿨습니다.' if key in held else '화면을 다시 만들었습니다.') if not problem else f"{row['definition']['title']}: 반영하지 못했습니다 - {problem}")
    for key, problem in problems.items():
        if problem:
            lines.append(f"{todo[key]['definition']['title']}: 반영하지 못했습니다 - {problem}")
    # Screens the files no longer have: last made first, so one that points at another goes before it.
    for key in sorted(gone, key=lambda name: held[name]['programCode'], reverse=True):
        code, answer = framework.delete_definition(key)
        title = held[key]['definition']['title']
        lines.append(f'{title}: 화면을 없앴습니다.' if code == 200 else f"{title}: 없애지 못했습니다 - {(answer or {}).get('detail') or answer} (화면은 남겨 두었습니다)")
    return lines + _apply_rest(folder)


def _apply_rest(folder):
    """After the screens: the menu arrangement and the system's settings, where the files say something else than the site holds."""
    lines = []
    if (folder / 'menus.json').is_file():
        menus = json.loads((folder / 'menus.json').read_text(encoding='utf-8'))
        if menus != _menus(site().db):
            _apply_menus(menus)
            lines.append('메뉴 편성: 이 기록의 모습으로 바꿨습니다.' if menus == _menus(site().db) else '메뉴 편성: 일부를 반영하지 못했습니다 (없는 화면의 메뉴는 넣지 않습니다).')
    if (folder / 'settings.json').is_file():
        settings = json.loads((folder / 'settings.json').read_text(encoding='utf-8'))
        held = _psql(site().db, "SELECT row_to_json(s) FROM sys_settings s WHERE setting_key NOT LIKE 'release\\_%' ORDER BY setting_key", rows=True)
        if settings != held and settings:
            _psql(site().db, f"INSERT INTO sys_settings SELECT * FROM json_populate_recordset(NULL::sys_settings, {_literal(settings)}::json) ON CONFLICT (setting_key) DO UPDATE SET setting_value = EXCLUDED.setting_value;")
            lines.append('시스템 설정: 이 기록의 모습으로 바꿨습니다.')
    return lines


def _settled(project):
    """Before the files are changed by git, what the development site holds now is recorded - nothing made is lost by moving."""
    made = record(project, '옮기기 전 상태 기록')
    return [f"옮기기 전에 아직 기록하지 않은 변경을 먼저 기록했습니다 ({made['commit'][:7]})."] if made.get('commit') else []


def _follow(project, lines):
    """After git changed the files: bring the development site along. When part of it could not follow, the answer says so and
    how to put it right - "깃 상태로 맞춰줘" tries again, "커밋해줘" keeps what the site holds instead."""
    try:
        moved = apply_files(project)
    except Exception as error:
        moved = [f'개발 사이트에 반영하지 못했습니다 - {str(error)[:300]}']
    failed = [line for line in moved if '못했습니다' in line]
    if failed:
        moved.append('⚠ 깃과 개발 사이트가 어긋나 있습니다. 원인을 고친 뒤 "깃 상태로 맞춰줘" 라고 하면 다시 맞추고, 지금 화면을 그대로 두려면 "커밋해줘" 라고 하세요.')
    return {'success': not failed, 'lines': lines + moved}


def _flows_broken(project):
    """Every registered business flow, run end to end with the development site as it is now: lines for those that do not hold."""
    try:
        folder = str(Path(__file__).resolve().parents[1] / 'harness2')
        if folder not in sys.path:
            sys.path.append(folder)
        import flows
        from framework import Framework
        framework = Framework()
        stages = sorted({key for flow in flows.load() for key in flow['stages']})
        return flows.judge(stages, framework)[2] if stages else []
    except Exception as problem:
        return [f'업무 흐름을 돌려 보지 못했습니다: {str(problem)[:200]}']


def git_undo(project, sha=None):
    """Take one recorded change back (the newest when none is named): a new commit that undoes it, and the development site follows."""
    with exclusive('기록 취소'):
        lines = _settled(project)
        target = sha or vcs.head(project)
        subject = vcs._git(project, 'log', '-1', '--format=%s', target)
        done = vcs.revert(project, target)
        lines.append(f'"{subject}" 을(를) 취소했습니다 ({done[:7]}).')
        out = {**_follow(project, lines), 'sha': done}
        broken = _flows_broken(project) if out.get('success') else []
        if broken:          # taking a change back is a change too: when it breaks a business flow, the taking back is taken back
            vcs.revert(project, done)
            again = _follow(project, [])
            out.update(success=False, lines=lines + broken + ['되돌리면 업무 흐름이 깨져서 취소하지 않았습니다 (취소한 것을 다시 취소했습니다). 흐름을 바꾸려면 업무 흐름도 함께 바꿔야 합니다.'] + again.get('lines', []))
        return out


def git_switch(project, name, create=False):
    """Move to another work space (branch), making it first when asked. The development site becomes what that work space holds."""
    with exclusive('작업 공간 옮기기'):
        lines = _settled(project)
        state = vcs.switch(project, name, create)
        lines.append(f"작업 공간 {state['branch']} " + ('을(를) 만들고 그리로 옮겼습니다 (지금 상태에서 갈라집니다).' if create else '(으)로 옮겼습니다.'))
        return {**(_follow(project, lines) if not create else {'success': True, 'lines': lines}), 'status': state}


def git_sync(project):
    """Bring the development site to what git holds now (after a step that could not finish, or after files were changed by hand)."""
    with exclusive('깃 상태로 맞추기'):
        out = _follow(project, [])
        if out['success'] and not out['lines']:
            out['lines'] = ['개발 사이트는 이미 깃과 같습니다.']
        return out


def git_remote(project, url):
    """Say where the project's remote repository is (a private repository of the user's own)."""
    vcs._require_repo(project)
    url = (url or '').strip()
    if not REMOTE.fullmatch(url) or len(url) > 300:
        raise ValueError('원격 저장소 주소는 https://… 또는 git@…:… 모양이어야 합니다.')
    has = vcs._git(project, 'remote', 'get-url', 'origin', check=False)
    vcs._git(project, 'remote', 'set-url' if has else 'add', 'origin', url)
    return {'success': True, 'lines': [f'원격 저장소를 연결했습니다: {url}', '"원격에 올려줘" 라고 하면 지금까지의 기록을 올립니다.']}


def git_push(project):
    state = vcs.status(project)
    lines = _settled(project) if state['remote'] else []
    if not state['remote']:
        raise ValueError('원격 저장소가 연결되어 있지 않습니다. "원격 저장소 연결해줘 <주소>" 라고 하거나 변경 이력 화면에서 주소를 넣으세요.')
    vcs.push(project)
    return {'success': True, 'lines': lines + [f"원격 저장소에 올렸습니다: {state['remote']} ({state['branch']})"]}


def git_log(project, limit=10):
    vcs._require_repo(project)
    state = vcs.status(project)
    rows = vcs._git(project, 'log', f'-{int(limit)}', '--date=format:%m-%d %H:%M', '--format=%h|%ad|%an|%s').splitlines()
    lines = [f"작업 공간 {state['branch']}" + (f" · 원격 {state['remote']}" + (f" (올리지 않은 기록 {state['ahead']}개)" if state.get('ahead') else '') if state['remote'] else ' · 원격 없음')]
    for row in rows:
        sha, when, who, subject = row.split('|', 3)
        lines.append(f"{when}  {sha}  {subject}  ({'모델' if who.startswith(vcs.MODEL_AUTHOR[0]) else '플랫폼' if who == vcs.PLATFORM_AUTHOR[0] else who})")
    return {'success': True, 'lines': lines}


# ---- the setup pack ----

COMPOSE = """# 운영 한 벌: 데이터베이스와 서버(화면 포함). 설정은 같은 폴더의 .env 에서 읽습니다.
name: ${PACK_NAME:-erp}
services:
  db:
    image: postgres:17-alpine
    environment:
      POSTGRES_USER: mdi
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      POSTGRES_DB: app
    volumes:
      - db:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U mdi -d app"]
      interval: 3s
      timeout: 3s
      retries: 40
    restart: unless-stopped
  app:
    image: ${APP_IMAGE:-eclipse-temurin:17-jre}
    depends_on:
      db:
        condition: service_healthy
    environment:
      DB_URL: jdbc:postgresql://db:5432/app
      SPRING_DATASOURCE_USERNAME: mdi
      SPRING_DATASOURCE_PASSWORD: ${DB_PASSWORD}
      WORKSPACE_ADMIN_USERNAME: admin
      WORKSPACE_ADMIN_PASSWORD: ${ADMIN_PASSWORD}
      SPRING_WEB_RESOURCES_STATIC_LOCATIONS: file:/app/web/
      APP_RELEASE_DIR: /app/release
      APP_TIMEZONE: ${APP_TIMEZONE:-Asia/Seoul}
    volumes:
      - ./app/app.jar:/app/app.jar:ro
      - ./web:/app/web:ro
      - ./release:/app/release:ro
    command: ["java", "-jar", "/app/app.jar"]
    ports:
      - "${BIND:-0.0.0.0}:${PORT:-8080}:8080"
    restart: unless-stopped
volumes:
  db: {}
"""

ENV_EXAMPLE = """# 운영 설정. install.sh 가 이 파일을 .env 로 복사하고 비밀번호 두 개를 무작위로 채웁니다.
# 묶음 이름 (한 서버에 여러 벌을 둘 때 서로 다르게)
PACK_NAME=erp
# 접속 포트와 받을 주소 (0.0.0.0 = 다른 PC 에서도 접속, 127.0.0.1 = 이 서버에서만)
PORT=8080
BIND=0.0.0.0
# 데이터베이스 비밀번호 (처음 설치할 때 정해지며, 그 뒤에는 바꾸지 않습니다)
DB_PASSWORD=
# 관리자(admin)의 첫 비밀번호 (처음 설치할 때 한 번만 쓰입니다. 들어가서 바꾸세요)
ADMIN_PASSWORD=
APP_TIMEZONE=Asia/Seoul
"""

INSTALL = """#!/bin/sh
# 처음 설치: .env 를 만들고(비밀번호는 무작위) 운영 한 벌을 띄웁니다. 이미 설치된 곳에서는 update.sh 를 쓰세요.
set -e
cd "$(dirname "$0")"
command -v docker >/dev/null 2>&1 || { echo "도커(Docker)가 필요합니다: https://docs.docker.com/get-docker/"; exit 1; }
random() { LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c "$1"; }
if [ ! -f .env ]; then
  sed -e "s/^DB_PASSWORD=.*/DB_PASSWORD=$(random 24)/" -e "s/^ADMIN_PASSWORD=.*/ADMIN_PASSWORD=$(random 12)/" .env.example > .env
  chmod 600 .env
  echo ".env 를 만들었습니다 (포트를 바꾸려면 지금 고친 뒤 다시 실행하세요)."
fi
docker compose up -d
sh ./wait.sh
port=$(grep '^PORT=' .env | cut -d= -f2)
echo "설치했습니다: http://<이 서버 주소>:${port:-8080}"
echo "관리자 아이디는 admin, 첫 비밀번호는 이 폴더의 .env 파일 ADMIN_PASSWORD 줄에 있습니다. 들어가서 바꾸세요."
"""

UPDATE = """#!/bin/sh
# 새 팩으로 올리기: 새 팩의 내용을 이 폴더에 덮어쓴 뒤(.env 는 그대로 둡니다) 실행합니다.
# 먼저 데이터베이스를 backups/ 에 받아 두고, 서버를 새 프로그램으로 다시 띄웁니다. 화면 정의는 서버가 시작하면서 스스로 반영합니다.
set -e
cd "$(dirname "$0")"
[ -f .env ] || { echo ".env 가 없습니다. 처음 설치는 install.sh 로 합니다."; exit 1; }
sh ./backup.sh
docker compose up -d --force-recreate app
sh ./wait.sh
"""

BACKUP = """#!/bin/sh
# 데이터베이스 전체를 backups/ 에 파일 하나로 받습니다 (자료, 첨부 파일, 사용자, 권한 모두).
set -e
cd "$(dirname "$0")"
mkdir -p backups
file="backups/db-$(date +%Y%m%d-%H%M%S).dump"
docker compose exec -T db pg_dump -U mdi -Fc app > "$file"
echo "백업: $file"
"""

RESTORE = """#!/bin/sh
# 백업 파일로 되돌리기: sh restore.sh backups/db-20260101-120000.dump  (지금 자료는 그 시점으로 바뀝니다)
set -e
cd "$(dirname "$0")"
[ -f "$1" ] || { echo "되돌릴 백업 파일을 적어 주세요: sh restore.sh backups/<파일>"; exit 1; }
docker compose stop app
docker compose exec -T db psql -U mdi -d postgres -c 'DROP DATABASE IF EXISTS app WITH (FORCE)' -c 'CREATE DATABASE app OWNER mdi'
docker compose exec -T db pg_restore -U mdi -d app --no-owner < "$1"
docker compose start app
sh ./wait.sh
"""

WAIT = """#!/bin/sh
# 서버가 뜰 때까지 기다리고, 팩의 화면 정의가 반영됐는지 알려 줍니다.
cd "$(dirname "$0")"
i=0
until docker compose logs app 2>/dev/null | grep -q 'Started .*Application'; do
  i=$((i+1)); [ $i -gt 90 ] && { echo "서버가 시작하지 않았습니다. docker compose logs app 으로 확인하세요."; exit 1; }
  sleep 2
done
sleep 2
status=$(docker compose exec -T db psql -U mdi -d app -Atc "select setting_value from sys_settings where setting_key='release_status'" 2>/dev/null)
detail=$(docker compose exec -T db psql -U mdi -d app -Atc "select setting_value from sys_settings where setting_key='release_detail'" 2>/dev/null)
if [ "$status" = "ok" ]; then echo "화면 반영: $detail"; else echo "화면을 반영하지 못했습니다 (이전 상태 그대로입니다): $detail"; exit 2; fi
"""


def _readme(version):
    return f"""# 운영 셋업 팩

만든 때: {version['made_at']} · 화면 {version['screens']}개 · 기록 {version.get('commit', '')[:7]}

이 폴더 하나가 운영 한 벌입니다. 도커(Docker)가 있는 서버라면 어디에나 설치할 수 있습니다.

## 처음 설치

1. 이 폴더를 서버에 풉니다.
2. `sh install.sh` 를 실행합니다. (포트를 바꾸려면 한 번 실행해 `.env` 가 생긴 뒤 `PORT` 를 고치고 다시 실행합니다.)
3. 안내된 주소로 들어갑니다. 관리자 아이디는 `admin`, 첫 비밀번호는 `.env` 의 `ADMIN_PASSWORD` 입니다. 들어가서 바꾸세요.

윈도우 서버에서는 `.env.example` 을 `.env` 로 복사해 `DB_PASSWORD`, `ADMIN_PASSWORD` 를 직접 채운 뒤 `docker compose up -d` 를 실행합니다.

## 새 팩으로 올리기

1. 새 팩을 같은 폴더에 덮어씁니다. (`.env` 와 `backups/` 는 팩에 들어 있지 않으므로 그대로 남습니다.)
2. `sh update.sh` 를 실행합니다. 데이터베이스를 먼저 `backups/` 에 받아 두고 서버를 다시 띄웁니다.

화면 정의·공통 코드·메뉴 편성은 서버가 시작하면서 팩의 것으로 맞춥니다. 전부 받아들여지지 않으면 하나도 바꾸지 않습니다.
운영에서 입력한 자료, 첨부 파일, 사용자, 역할, 권한은 건드리지 않습니다. 시스템 이름·로고·테마는 처음 설치할 때만 팩의 것을 씁니다.
팩에 없는 화면(개발에서 지운 화면)은 자료 보호를 위해 운영에 그대로 남습니다.

## 그 밖에

- 백업: `sh backup.sh` · 되돌리기: `sh restore.sh backups/<파일>`
- 멈추기: `docker compose stop` · 다시 켜기: `docker compose start` · 기록 보기: `docker compose logs app`
- 인터넷이 되지 않는 서버에서는 도커 이미지 두 개(`postgres:17-alpine`, `{APP_IMAGE}`)를 먼저 옮겨 두어야 합니다.

## 들어 있는 것

- `app/app.jar` 서버 프로그램 · `web/` 화면 · `release/` 화면 정의, 공통 코드, 메뉴 편성
- `docker-compose.yml`, `.env.example`, `install.sh`, `update.sh`, `backup.sh`, `restore.sh`, `wait.sh`, `VERSION.json`
"""


def _web_hash(frontend):
    digest = hashlib.sha256()
    for path in sorted([*(frontend / 'src').rglob('*'), frontend / 'index.html', frontend / 'package.json', frontend / 'vite.config.ts', *(frontend / 'public').rglob('*')]):
        if path.is_file():
            digest.update(str(path.relative_to(frontend)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _build_web(project, note):
    """The screens as built files, kept per source state so the same sources are built once."""
    frontend = Path(project) / 'frontend'
    built = site().ops_home / 'builds' / _web_hash(frontend)[:16]
    if not (built / 'index.html').is_file():
        note('화면 빌드')
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(['npx', 'vite', 'build', '--outDir', str(Path(tmp) / 'web'), '--emptyOutDir'], cwd=frontend, capture_output=True, text=True, timeout=600)
            if result.returncode != 0 or not (Path(tmp) / 'web/index.html').is_file():
                raise ReleaseError('화면 빌드 실패: ' + (result.stderr or result.stdout)[-600:])
            built.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(Path(tmp) / 'web', built)
    return built


def _mounted(container, target):
    try:
        info = json.loads(live.sh(['docker', 'inspect', container]))[0]
    except live.DeployError:
        return None
    return next((mount['Source'] for mount in info.get('Mounts', []) if mount['Destination'] == target), None)


def _compose(folder, *args, env=None, timeout=600, check=True, stdin=None):
    """docker compose in a pack folder. A clean docker config keeps a broken credential helper on this machine out of the way (the images are public)."""
    config = live.SHARE / 'docker-config'
    config.mkdir(parents=True, exist_ok=True)
    if not (config / 'config.json').is_file():
        (config / 'config.json').write_text('{}')
    plugins = Path.home() / '.docker/cli-plugins'
    if plugins.is_dir() and not (config / 'cli-plugins').exists():
        (config / 'cli-plugins').symlink_to(plugins)
    result = subprocess.run(['docker', 'compose', *args], cwd=folder, capture_output=True, text=stdin is None, timeout=timeout, input=stdin,
                            env={**os.environ, 'DOCKER_CONFIG': str(config), **(env or {})})
    if check and result.returncode != 0:
        err = result.stderr if isinstance(result.stderr, str) else result.stderr.decode(errors='replace')
        raise ReleaseError(f"docker compose {args[0]} 실패: " + err[-500:])
    return result


def _copy_sql(folder, sql):
    out = _compose(folder, 'exec', '-T', 'db', 'psql', '-U', 'mdi', '-d', 'app', '-At', '-c', sql, check=False)
    return (out.stdout or '').strip() if out.returncode == 0 else ''


def _wait_copy(folder, seconds=200):
    """Wait until the copy's server has started and has dealt with the pack. Returns (status, detail) as the server wrote them."""
    end = time.time() + seconds
    while time.time() < end:
        logs = _compose(folder, 'logs', '--no-color', '--tail', '400', 'app', check=False).stdout or ''
        if 'APPLICATION FAILED TO START' in logs:
            raise ReleaseError('서버 시작 실패: ' + logs[-800:])
        if re.search(r'Started \w*Application', logs):
            time.sleep(2)
            status = _copy_sql(folder, "select setting_value from sys_settings where setting_key='release_status'")
            if status:
                return status, _copy_sql(folder, "select setting_value from sys_settings where setting_key='release_detail'")
        time.sleep(3)
    raise ReleaseError(f'서버가 {seconds}초 안에 시작하지 않았습니다.')


def _sign_in(port, password):
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    base = f'http://127.0.0.1:{port}'
    session = json.load(opener.open(base + '/api/auth/session', timeout=30))
    request = urllib.request.Request(base + '/api/auth/login', data=urllib.parse.urlencode({'username': 'admin', 'password': password}).encode(),
                                     headers={session['csrf']['headerName']: session['csrf']['token'], 'Content-Type': 'application/x-www-form-urlencoded'}, method='POST')
    try:
        with opener.open(request, timeout=30) as answer:
            if answer.status != 200:
                return False
        page = opener.open(base + '/', timeout=30).read().decode(errors='replace')
        listed = json.load(opener.open(base + '/api/meta/definitions', timeout=30))
        return '<div id="root"' in page and isinstance(listed, list) and len(listed)
    except urllib.error.HTTPError:
        return False


def _write_env(folder, name, port, bind, keep=True):
    """The copy's .env: kept when it is there (its passwords belong to the copy's database), made with random passwords otherwise."""
    path = Path(folder) / '.env'
    if keep and path.is_file():
        return dict(line.split('=', 1) for line in path.read_text().splitlines() if '=' in line and not line.startswith('#'))
    values = {'PACK_NAME': name, 'PORT': str(port), 'BIND': bind, 'DB_PASSWORD': secrets.token_urlsafe(18), 'ADMIN_PASSWORD': secrets.token_urlsafe(9), 'APP_TIMEZONE': 'Asia/Seoul'}
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w') as out:
        out.write(''.join(f'{key}={value}\n' for key, value in values.items()))
    return values


def _try_pack(folder, screens, note):
    """Install the pack from nothing in a throwaway copy, look at it, and remove it again."""
    with tempfile.TemporaryDirectory(dir=str(live.SHARE)) as tmp:
        trial = Path(tmp) / 'pack'
        shutil.copytree(folder, trial)
        values = _write_env(trial, f'packtrial{int(time.time())}', TRIAL_PORT, '127.0.0.1', keep=False)
        try:
            note('팩 시험 설치')
            _compose(trial, 'up', '-d')
            status, detail = _wait_copy(trial)
            if status != 'ok':
                raise ReleaseError('시험 설치에서 화면이 받아들여지지 않았습니다: ' + detail)
            held = _copy_sql(trial, "select count(*) from app_definitions where status='PUBLISHED'")
            if held != str(screens):
                raise ReleaseError(f'시험 설치에 화면이 {held}개만 들어갔습니다 (팩에는 {screens}개).')
            got = _sign_in(TRIAL_PORT, values['ADMIN_PASSWORD'])
            if got != screens:
                raise ReleaseError('시험 설치에 관리자로 들어가 화면을 읽지 못했습니다.')
            return detail
        finally:
            _compose(trial, 'down', '-v', '--remove-orphans', check=False)


def _marks(definitions):
    """A short mark of each definition as development holds it (what a pack carried is told apart from what was made since)."""
    return {key: hashlib.sha1(json.dumps(row['definition'], ensure_ascii=False, sort_keys=True).encode()).hexdigest() for key, row in definitions.items()}


def _releases(state):
    folder = Path(state) / 'releases'
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def history(state, limit=20):
    out = []
    for path in sorted(_releases(state).glob('2*.json'), reverse=True)[:limit]:
        try:
            out.append(json.loads(path.read_text(encoding='utf-8')))
        except ValueError:
            pass
    return out


def _last(state, kind=None):
    return next((item for item in history(state, 200) if item.get('success') and (kind is None or item.get('kind') == kind)), None)


def pack(project, state, log=None):
    """Record, build the setup pack (folder and zip) and try it. Returns the pack's record; success False tells the step and why."""
    note = log or (lambda *_: None)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    out = {'kind': 'pack', 'stamp': stamp, 'started_at': time.strftime('%Y-%m-%dT%H:%M:%S')}
    step = 'record'
    try:
        with exclusive('셋업 팩 만들기'):
            note('기록')
            out['recorded'] = record(project)
            out['commit'] = vcs.head(project)
            step = 'program'
            note('서버 프로그램 확인')
            shipped = live.deploy(project, state, 'pack', note)       # development runs the same sources first, so what is packed is what was tried
            if not shipped.get('success'):
                raise ReleaseError(f"개발 서버 반영 실패({shipped.get('step')}): {shipped.get('error', '')[:300]}")
            jar = Path(_mounted(site().api_container, '/app/app.jar'))
            step = 'screens'
            built = _build_web(project, note)
            step = 'assemble'
            note('팩 조립')
            definitions = _definitions(site().db)
            name = f'{site().slug}-setup-{stamp}'
            folder = site().packs / name
            (folder / 'app').mkdir(parents=True)
            shutil.copy2(jar, folder / 'app/app.jar')
            shutil.copytree(built, folder / 'web')
            shutil.copytree(Path(project) / 'release', folder / 'release')
            version = {'made_at': out['started_at'], 'stamp': stamp, 'commit': out['commit'] or '', 'screens': len(definitions), 'server': jar.name,
                       'database_version': (live.flyway_versions() or [''])[-1]}
            (folder / 'VERSION.json').write_text(_dump(version), encoding='utf-8')
            for file, text in (('docker-compose.yml', COMPOSE), ('.env.example', ENV_EXAMPLE), ('README.md', _readme(version)),
                               ('install.sh', INSTALL), ('update.sh', UPDATE), ('backup.sh', BACKUP), ('restore.sh', RESTORE), ('wait.sh', WAIT)):
                (folder / file).write_text(text, encoding='utf-8')
                if file.endswith('.sh'):
                    (folder / file).chmod(0o755)
            step = 'trial'
            out['trial'] = _try_pack(folder, len(definitions), note)
            step = 'windows'
            note('윈도우용 팩 만들기 (최초 셋업, 업데이트)')
            made = windows_pack.write_zips(folder, version, VENDOR, site().packs, name, PWSH, service=site().service, title=site().title)
            files = {kind: {'name': made[kind].name, 'file': str(made[kind]), 'size': made[kind].stat().st_size} for kind in ('install', 'update')}
            out.update(success=True, folder=str(folder), name=name, files=files, program=_program(project), postgres=made['postgres'], scripts_parsed=made['script_check'] is not None,
                       screens=len(definitions), shipped=_marks(definitions), tag=f'pack-{stamp}')
            vcs.tag(project, out['tag'], '운영 셋업 팩 ' + out['started_at'])
            for old in sorted((path for path in site().packs.glob('*setup-*') if path.is_dir()), key=lambda path: path.name[-15:])[:-1]:       # only the current version's packs are kept (an earlier version is not handed out again)
                shutil.rmtree(old, ignore_errors=True)
                for file in site().packs.glob(old.name + '*.zip'):
                    file.unlink()
    except Exception as error:
        out.update(success=False, step=step, error=str(error)[-1200:])
    out['finished_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    (_releases(state) / f"{stamp.replace('-', '')}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    return out


def _program(project):
    """A mark of the program itself (server and screens sources), to tell whether a pack still holds the current one."""
    return {'server': live.source_hash(Path(project) / 'backend')[:12], 'web': _web_hash(Path(project) / 'frontend')[:16]}


def screens():
    """The screens the development site holds, briefly: key, title, kind and the labels of their fields."""
    out = []
    for key, row in _definitions(site().db).items():
        definition = row['definition']
        out.append({'key': key, 'title': definition.get('title'), 'type': definition.get('type'), 'program': row['programCode'],
                    'fields': [field['label'] for field in definition.get('fields') or []],
                    'lines': [field['label'] for field in (definition.get('lines') or {}).get('fields') or []]})
    return out


def status(project, state):
    """For the platform's home: the packs made so far (newest first) and whether the newest still holds everything made."""
    made = [item for item in history(state, 200) if item.get('success') and item.get('kind') == 'pack' and item.get('files')
            and all(Path(file['file']).is_file() for file in item['files'].values())][:1]
    packs = [{'stamp': item['stamp'], 'started_at': item['started_at'], 'screens': item.get('screens'),
              'files': {kind: {'name': file['name'], 'size': file['size']} for kind, file in item['files'].items()}} for item in made]
    out = {'project': site().title, 'slug': site().slug, 'packs': packs, 'pending': None, 'current': False}
    try:
        out['unrecorded'] = unrecorded(project)
        out['git'] = vcs.status(project) if (Path(project) / '.git').exists() else None
        here = _definitions(site().db)
        marks, shipped = _marks(here), ((made[0] if made else {}).get('shipped') or {})
        program = bool(made) and made[0].get('program') is not None and made[0]['program'] != _program(project)
        out['pending'] = {'new': [row['definition']['title'] for key, row in here.items() if key not in shipped],
                          'changed': [row['definition']['title'] for key, row in here.items() if key in shipped and shipped[key] != marks[key]],
                          'removed': len([key for key in shipped if key not in here]), 'program': program}
        out['current'] = bool(made) and not out['pending']['new'] and not out['pending']['changed'] and not out['pending']['removed'] and not program
    except Exception as error:      # the home page still opens when docker is down
        out['error'] = str(error)[:200]
    return out


def pack_file(state, name):
    """The zip of a pack by its file name (only names this module made)."""
    if not re.fullmatch(r'[a-z0-9-]{1,40}-\d{8}-\d{6}-(install|update)\.zip', name or ''):
        raise ValueError('팩 이름이 올바르지 않습니다.')
    path = site().packs / name
    if not path.is_file():
        raise ValueError('그 팩은 남아 있지 않습니다.')
    return path


COMMANDS = (('platform-pack', re.compile(r'플랫폼.*(팩|패키지|꾸러미)')),
            ('model-pack', re.compile(r'모델 ?(팩|패키지|꾸러미)')),
            ('pack', re.compile(r'(셋업|셋팅|세팅|설치|운영|배포) ?(팩|패키지|꾸러미|묶음)|setup ?pack|배포|릴리[스즈]|운영 ?(에|으로|서버|환경).*(올려|반영|내보내|적용|설치)')),       # "배포해줘" means: make the setup packs
            ('record', re.compile(r'커밋|깃 ?(에|으로|허브)|저장소에|버전.*(남겨|기록|저장)|변경.*(기록|저장)해')))


# An order may also come already decided, from a tool instead of a sentence (platform/ctl.py): the same kinds, the same work.
ORDER_KINDS = {'record': '변경 기록 (깃)', 'git-undo': '기록한 변경 취소 (깃)', 'git-branch': '작업 공간 옮기기 (깃)', 'git-push': '원격에 올리기 (깃)', 'git-remote': '원격 저장소 연결 (깃)',
               'git-log': '변경 이력 (깃)', 'git-sync': '깃 상태로 맞추기', 'pack': '운영 셋업 팩 만들기',
               'platform-pack': '플랫폼 셋업 팩 만들기', 'model-pack': '모델 팩 만들기',
               'replay': '적어 둔 화면 정의 적용', 'project-rename': '프로젝트 이름 바꾸기'}       # a definition already written (a recorded answer of the model, or a tool's own): checked and applied like any request, without asking the model


def given_order(order):
    """Check an order that came decided: {'kind': ..., and what that kind needs}. Returns (kind, named)."""
    if not isinstance(order, dict) or order.get('kind') not in ORDER_KINDS:
        raise ValueError('알 수 없는 명령입니다: ' + str((order or {}).get('kind') if isinstance(order, dict) else order)[:40])
    kind, named = order['kind'], {}
    if kind == 'git-branch':
        if not isinstance(order.get('name'), str) or not vcs.BRANCH_NAME.fullmatch(order['name']):
            raise ValueError('작업 공간 이름이 올바르지 않습니다.')
        named = {'name': order['name'], 'create': bool(order.get('create'))}
    elif kind == 'git-remote':
        named = {'url': str(order.get('url') or '')}
    elif kind == 'git-undo' and order.get('sha'):
        named = {'sha': str(order['sha'])}
    elif kind == 'replay':
        if not isinstance(order.get('file'), str) or not Path(order['file']).is_file():
            raise ValueError('적용할 화면 정의 파일을 찾지 못했습니다.')
        named = {'file': order['file']}
    elif kind == 'project-rename':
        named = {key: str(order[key]) for key in ('title', 'slug') if order.get(key)}
        if not named:
            raise ValueError('바꿀 이름이 없습니다.')
    elif kind == 'record' and order.get('message'):
        named = {'message': str(order['message'])[:2000]}
    return kind, named


def carry_out(kind, named, project, state, note=None):
    """Do one order. The single place every way of asking ends in: a button, a sentence in the request box, a tool."""
    if kind == 'record':
        return record(project, named.get('message'))
    if kind == 'git-undo':
        return git_undo(project, vcs._sha(project, named['sha']) if named.get('sha') else None)
    if kind == 'git-branch':
        return git_switch(project, named['name'], named['create'])
    if kind == 'git-push':
        return git_push(project)
    if kind == 'git-remote':
        return git_remote(project, named['url'])
    if kind == 'git-log':
        return git_log(project)
    if kind == 'git-sync':
        return git_sync(project)
    if kind == 'pack':
        return pack(project, state, note)
    import platform_pack
    return platform_pack.build(project, note) if kind == 'platform-pack' else platform_pack.model_pack(note)


BRANCH = r'(?:브랜치|작업 ?공간)'
GIT_ORDERS = (('git-sync', re.compile(r'깃 ?(상태|기록|대로|기준).*(맞춰|맞추|되돌|동기)')),
              ('git-remote', re.compile(r'(원격|저장소|깃허브|깃 ?랩|리모트).*(연결|등록|설정|바꿔)')),
              ('git-log', re.compile(r'(변경 ?이력|커밋 ?(이력|목록|기록)|깃 ?(이력|로그)|히스토리).*(보여|알려|뭐|확인)')),
              ('git-branch', re.compile(BRANCH + r'.*(만들|생성|전환|바꿔|옮겨|이동|가줘)')),
              ('git-push', re.compile(r'(원격|깃허브|깃 ?랩|리모트).*(올려|푸시|보내)|푸시해')),
              ('git-undo', re.compile(r'(방금|마지막|직전|최근).*(커밋|변경|기록|요청).*(취소|되돌)|커밋.*(취소|되돌)')))


def git_order(goal):
    """An order about the project's git, with what it names: ('git-branch', {'name': ..., 'create': ...}) and so on; None otherwise."""
    text = ' '.join((goal or '').split())
    if not text or len(text) > 400:
        return None
    renamed = re.search(r'프로젝트\s*(?:이름|명)(?:을|를|은|는)?\s*["\'“”‘’]?(.{1,40}?)["\'“”‘’]?\s*(?:으로|로)\s*(?:바꿔|변경|고쳐)', text)
    if renamed and not re.search(r'화면|항목', text):
        return 'project-rename', {'title': renamed.group(1).strip()}
    kind = next((name for name, pattern in GIT_ORDERS if pattern.search(text)), None)
    if not kind or (kind != 'git-remote' and (len(text) > 60 or re.search(r'화면|항목|집계|현황', text))):
        return None
    if kind == 'git-remote':
        url = REMOTE.search(text)
        return (kind, {'url': url.group(1)}) if url else None
    if kind == 'git-branch':
        action = r'\s*(?:을|를|으로|로|에)?\s*(?:새로 )?(?:만들|생성|전환|바꿔|옮겨|이동|가줘)'
        quote = '["\'“”‘’]?'
        found = [match.group(1) for match in (re.search(quote + r'([A-Za-z0-9가-힣._/-]+)' + quote + r'\s*' + BRANCH + action, text),
                                              re.search(BRANCH + r'\s*' + quote + r'([A-Za-z0-9가-힣._/-]+?)' + quote + action, text)) if match]
        names = [name for name in found if name not in ('으로', '로', '을', '를', '에', '새', '새로', '다른', '새로운')]
        if not names:
            return None
        return kind, {'name': names[0], 'create': bool(re.search(r'만들|생성', text))}
    return kind, {}


def command(goal):
    """Is this request an order to record, pack or deploy (not a screen to make)? Returns 'record' | 'pack' | 'platform-pack' | 'model-pack' | None."""
    text = ' '.join((goal or '').split())
    # An order is short and does not describe a screen; "배포 현황 화면 만들어줘" is a screen to make.
    if not text or len(text) > 60 or re.search(r'화면|항목|추가|집계|현황|등록 ?해|고쳐|바꿔|삭제', text):
        return None
    kind = next((name for name, pattern in COMMANDS if pattern.search(text)), None)
    # Taking an operating server back is done by hand there, with its own packs; a sentence about that is not an order to make a pack.
    return None if kind == 'pack' and re.search(r'되돌|롤백|이전', text) else kind


def _size(count):
    return f'{count / 1024 / 1024:.0f}MB'


def say(kind, result):
    """The outcome in plain words."""
    if kind == 'record':
        if not result.get('commit'):
            return '기록할 변경이 없습니다. 이미 모두 기록되어 있습니다.'
        parts = [f"화면 {len(result['screens'])}개 ({', '.join(result['screens'][:5])}{' …' if len(result['screens']) > 5 else ''})" if result['screens'] else '',
                 '공통 코드' if result.get('codes') else '', '메뉴 편성' if result.get('menus') else '', f"소스 파일 {result['source_files']}개" if result.get('source_files') else '']
        tail = ' 원격 저장소에도 올렸습니다.' if result.get('pushed') is True else f" 원격 저장소에는 올리지 못했습니다: {result['pushed']}" if result.get('pushed') else ''
        return f"기록했습니다 ({result['commit'][:7]}): " + ', '.join(filter(None, parts)) + '.' + tail
    if kind == 'project-rename':
        return f"프로젝트 이름을 바꿨습니다: {(result.get('site') or {}).get('title') or result.get('title') or result.get('name')}" + (f" (영문 이름 {result['name']})" if result.get('site') else '')
    if kind.startswith('git-'):
        return '\n'.join(result.get('lines') or ['했습니다.'])
    if kind == 'platform-pack':
        version = result['version']
        return (f"플랫폼 셋업 팩을 만들었습니다 (맥·애플 실리콘용): {result['name']} ({result['size'] / 1024 / 1024:.1f}MB)\n"
                f"플랫폼·하네스·프로젝트(화면 {version['screens']}개)와 설치 스크립트가 들어 있습니다. 다른 맥에서 풀고 bash install.sh (처음) 또는 bash update.sh (플랫폼만 새 버전으로).\n"
                + (f"⚠ 커밋되지 않은 변경은 팩에 들어가지 않았습니다: {', '.join(result['uncommitted'])}\n" if result.get('uncommitted') else '')
                + f"모델({version['model']}, 약 15GB)은 들어 있지 않습니다. 인터넷이 없는 맥에는 '모델 팩 만들어줘' 로 만든 파일을 함께 옮기세요.\n파일 위치: {result['file']}")
    if kind == 'model-pack':
        return f"모델 팩: {result['name']} ({result['size'] / 1024 / 1024 / 1024:.1f}GB, {result['model']})\n플랫폼 셋업 팩을 푼 폴더 안이나 바로 옆에 두고 install.sh 를 실행하면 내려받지 않고 이 파일에서 풉니다.\n파일 위치: {result['file']}"
    if kind == 'pack':
        if not result.get('success'):
            return f"셋업 팩을 만들지 못했습니다 ({result.get('step')} 단계): {result.get('error', '')[:500]}"
        files = result['files']
        return (f"{site().title} 운영 셋업 팩을 만들었습니다 (윈도우 서버용, 화면 {result['screens']}개):\n"
                f"  최초 셋업 팩  {files['install']['name']} ({_size(files['install']['size'])}) - 빈 서버에 자바·PostgreSQL {result.get('postgres', '')}·DB·서비스까지 설치 (install.bat)\n"
                f"  업데이트 팩   {files['update']['name']} ({_size(files['update']['size'])}) - 설치된 서버를 새 버전으로 (update.bat, 실패하면 자동으로 이전 상태로)\n"
                f"팩에 든 프로그램·화면·화면 정의는 빈 환경에 설치해 확인했습니다 ({result.get('trial', '')}; 관리자 로그인 확인).\n"
                f"⚠ 윈도우용 설치 스크립트는 문법 검사만 했습니다 (이 맥에서는 윈도우 설치를 돌려 볼 수 없음). 실제 윈도우에서 한 번 설치해 보고 쓰세요.\n"
                f"파일 위치: {site().packs}")
    return str(result)
