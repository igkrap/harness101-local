"""Record what was made and put it into operation, on request ("커밋해줘", "운영에 배포해줘").

There are two copies of the app on this machine:
  개발 (development)  where screens are made and tried: mdi-local-api on 8083, screens on 5292, database mdi_local
  운영 (operation)    where people work: mdi-prod-api on 5300 (it serves the built screens itself), database mdi_prod

Screens are definitions kept in the development database, so recording means writing them out as files in the
project (release/) and committing them to the project's git. Deploying then carries those files to operation:
the same server program and built screens, the common codes, the definitions (through operation's own API, so
every rule is judged there too) and the menu arrangement. Operation's own records, users, roles and permissions
are never touched. Before anything changes operation's database is dumped; if a definition is refused there, the
dump is put back, so operation is never left half changed.
"""
import hashlib
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

PROD_CONTAINER, PROD_DB, PROD_PORT = 'mdi-prod-api', 'mdi_prod', 5300
PROD_URL = f'http://127.0.0.1:{PROD_PORT}'
PROD_HOME = live.SHARE / 'prod/local-only'
DEPLOYER, DEPLOYER_NAME = 'deployer', '배포 전용 (플랫폼)'
CARRIED = ('rules', 'effects', 'limits')      # parts that may name screens made later: applied in a second pass


class ReleaseError(RuntimeError):
    pass


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


def write_bundle(project):
    """Write development's definitions, common codes and menus under release/ (files that are no longer true are removed)."""
    folder = Path(project) / 'release'
    (folder / 'definitions').mkdir(parents=True, exist_ok=True)
    definitions = _definitions(live.DB_NAME)
    for path in (folder / 'definitions').glob('*.json'):
        if path.stem not in definitions:
            path.unlink()
    for key, row in definitions.items():
        path, text = folder / 'definitions' / f'{key}.json', _dump(row)
        if not path.is_file() or path.read_text(encoding='utf-8') != text:
            path.write_text(text, encoding='utf-8')
    for name, value in (('codes.json', _codes(live.DB_NAME)), ('menus.json', _menus(live.DB_NAME))):
        path, text = folder / name, _dump(value)
        if not path.is_file() or path.read_text(encoding='utf-8') != text:
            path.write_text(text, encoding='utf-8')
    readme = folder / 'README.md'
    if not readme.is_file():
        readme.write_text('# 배포 묶음\n\n플랫폼이 "커밋해줘", "운영에 배포해줘" 요청 때 개발 DB에서 뽑아 적는 파일입니다. 손으로 고치지 않습니다.\n\n'
                          '- `definitions/` 화면 정의 (화면 하나에 파일 하나)\n- `codes.json` 공통 코드\n- `menus.json` 모듈과 메뉴 편성\n', encoding='utf-8')
    return definitions


def _read_bundle(folder):
    folder = Path(folder)
    definitions = {path.stem: json.loads(path.read_text(encoding='utf-8')) for path in sorted((folder / 'definitions').glob('*.json'))}
    load = lambda name, empty: json.loads((folder / name).read_text(encoding='utf-8')) if (folder / name).is_file() else empty
    return definitions, load('codes.json', {'groups': [], 'codes': []}), load('menus.json', {'modules': [], 'menus': []})


def _titles(project, paths):
    out = []
    for path in paths:
        try:
            out.append(json.loads((Path(project) / path).read_text(encoding='utf-8'))['definition']['title'])
        except (OSError, ValueError, KeyError):
            out.append(Path(path).stem)
    return out


def record(project, message=None):
    """Write the bundle and commit every pending change of the project. Returns what was recorded (commit None = nothing new)."""
    vcs.ensure_repo(project)
    write_bundle(project)
    changed = [line[3:].strip().strip('"') for line in vcs._git(project, 'status', '--porcelain', '--untracked-files=all', raw=True).splitlines() if line.strip()]
    screens = _titles(project, [path for path in changed if path.startswith('release/definitions/') and (Path(project) / path).is_file()])
    removed = [Path(path).stem for path in changed if path.startswith('release/definitions/') and not (Path(project) / path).is_file()]
    other = [path for path in changed if not path.startswith('release/')]
    title = message or ('화면 ' + ', '.join(screens[:3]) + (f' 외 {len(screens) - 3}개' if len(screens) > 3 else '') if screens else '변경 기록')
    body = '\n'.join(filter(None, [f"화면 정의: {', '.join(screens)}" if screens else '', f"지워진 화면: {', '.join(removed)}" if removed else '',
                                   '공통 코드 변경' if 'release/codes.json' in changed else '', '메뉴 편성 변경' if 'release/menus.json' in changed else '',
                                   f'소스 파일 {len(other)}개' if other else '']))
    sha = vcs.commit(project, title[:72] + ('\n\n' + body if body else ''), author=vcs.PLATFORM_AUTHOR)
    pushed = None
    if sha and vcs.status(project).get('remote'):
        try:
            vcs.push(project)
            pushed = True
        except Exception as error:      # the record itself stands; say that it did not reach the remote
            pushed = str(error)[:200]
    return {'commit': sha, 'screens': screens, 'removed': removed, 'codes': 'release/codes.json' in changed, 'menus': 'release/menus.json' in changed,
            'source_files': len(other), 'pushed': pushed}


# ---- the operating copy ----

def _login_file(name):
    folder = Path(__file__).resolve().parent / 'state/auth'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    return folder / name


def _keep_login(path, username, password):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w') as out:
        json.dump({'username': username, 'password': password, 'url': PROD_URL}, out)
    path.chmod(0o600)


def _accounts():
    """First start of operation: its administrator gets a password of its own (kept in state/auth/prod-login.json, 0600)
    and the platform gets a separate account to apply releases with. Passwords never appear in argv, logs or output."""
    admin, deployer = _login_file('prod-login.json'), _login_file('prod-deployer.json')
    statements = ['CREATE EXTENSION IF NOT EXISTS pgcrypto;']
    made = {}
    if not admin.is_file():
        made[admin] = ('admin', secrets.token_urlsafe(12))
        statements.append("UPDATE workspace_users SET password_hash = '{bcrypt}' || crypt('%s', gen_salt('bf', 10)) WHERE username = 'admin';" % made[admin][1])
    if not deployer.is_file() or not _psql(PROD_DB, f"SELECT 1 FROM workspace_users WHERE username = '{DEPLOYER}'").strip():
        made[deployer] = (DEPLOYER, secrets.token_urlsafe(24))
        statements.append(f"""INSERT INTO workspace_users (username, password_hash, display_name, permissions, enabled, status)
            SELECT '{DEPLOYER}', '{{bcrypt}}' || crypt('{made[deployer][1]}', gen_salt('bf', 10)), '{DEPLOYER_NAME}', permissions, TRUE, 'ACTIVE' FROM workspace_users WHERE username = 'admin'
            ON CONFLICT (username) DO UPDATE SET password_hash = EXCLUDED.password_hash, enabled = TRUE, status = 'ACTIVE';
            INSERT INTO sys_user_roles (username, role_code) VALUES ('{DEPLOYER}', 'ADMIN') ON CONFLICT DO NOTHING;""")
    if made:
        try:
            _psql(PROD_DB, '\n'.join(statements))
        except ReleaseError as error:
            text = str(error)
            for _, password in made.values():
                text = text.replace(password, '***')
            raise ReleaseError(text)
        for path, (username, password) in made.items():
            _keep_login(path, username, password)


def _mounted(container, target):
    try:
        info = json.loads(live.sh(['docker', 'inspect', container]))[0]
    except live.DeployError:
        return None
    return next((mount['Source'] for mount in info.get('Mounts', []) if mount['Destination'] == target), None)


def _start_prod(jar, tmp):
    config = live.live_config()
    env = [entry for entry in config['env'] if not entry.startswith(('SPRING_WEB_RESOURCES_STATIC_LOCATIONS=', 'DB_URL='))]
    dev_url = next((entry.split('=', 1)[1] for entry in config['env'] if entry.startswith('DB_URL=')), f'jdbc:postgresql://{live.DB_CONTAINER}:5432/{live.DB_NAME}')
    envfile = Path(tmp) / 'prod.env'
    envfile.touch(mode=0o600)
    envfile.write_text('\n'.join(env + ['DB_URL=' + dev_url.replace('/' + live.DB_NAME, '/' + PROD_DB), 'SPRING_WEB_RESOURCES_STATIC_LOCATIONS=file:/app/web/']) + '\n')
    subprocess.run(['docker', 'rm', '-f', PROD_CONTAINER], capture_output=True)
    live.sh(['docker', 'run', '-d', '--name', PROD_CONTAINER, '--network', live.NETWORK, '--env-file', str(envfile), '--restart', 'unless-stopped',
             '-v', f'{jar}:/app/app.jar:ro', '-v', f'{PROD_HOME / "web"}:/app/web:ro', '-p', f'127.0.0.1:{PROD_PORT}:8080',
             config['image'], 'java', '-jar', '/app/app.jar'], timeout=120)
    for network in config.get('networks', []):
        if network != live.NETWORK:
            live.sh(['docker', 'network', 'connect', network, PROD_CONTAINER], timeout=60)
    live.wait_started(PROD_CONTAINER, PROD_URL + '/')


def _web_hash(frontend):
    digest = hashlib.sha256()
    for path in sorted([*(frontend / 'src').rglob('*'), frontend / 'index.html', frontend / 'package.json', frontend / 'vite.config.ts', *(frontend / 'public').rglob('*')]):
        if path.is_file():
            digest.update(str(path.relative_to(frontend)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _build_web(project, note):
    """The screens as built files, kept per source state so an earlier release can be put back without building."""
    frontend = Path(project) / 'frontend'
    digest = _web_hash(frontend)
    built = PROD_HOME / 'builds' / digest[:16]
    if not (built / 'index.html').is_file():
        note('화면 빌드')
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(['npx', 'vite', 'build', '--outDir', str(Path(tmp) / 'web'), '--emptyOutDir'], cwd=frontend, capture_output=True, text=True, timeout=600)
            if result.returncode != 0 or not (Path(tmp) / 'web/index.html').is_file():
                raise ReleaseError('화면 빌드 실패: ' + (result.stderr or result.stdout)[-600:])
            built.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(Path(tmp) / 'web', built)
    return built, digest


def _place_web(built):
    """Swap the served files: the container keeps its mount of web/, whose contents are replaced."""
    target = PROD_HOME / 'web'
    target.mkdir(parents=True, exist_ok=True)
    live.sh(['rsync', '-a', '--delete', str(built) + '/', str(target) + '/'], timeout=120)


def _backup_prod(stamp):
    live.BACKUPS.mkdir(parents=True, exist_ok=True)
    path = live.BACKUPS / f'{PROD_DB}-before-release-{stamp}.dump'
    with path.open('wb') as out:
        result = subprocess.run(['docker', 'exec', live.DB_CONTAINER, 'pg_dump', '-U', live.DB_USER, '-Fc', PROD_DB], stdout=out, stderr=subprocess.PIPE, timeout=600)
    if result.returncode != 0 or path.stat().st_size == 0:
        raise ReleaseError('운영 DB 백업 실패: ' + result.stderr.decode(errors='replace')[-400:])
    return path


def _restore_prod(dump):
    """Put operation's database back as it was in the dump (the server is stopped meanwhile)."""
    subprocess.run(['docker', 'stop', PROD_CONTAINER], capture_output=True, timeout=120)
    _psql('postgres', f'DROP DATABASE IF EXISTS "{PROD_DB}" WITH (FORCE);')
    _psql('postgres', f'CREATE DATABASE "{PROD_DB}" OWNER {live.DB_USER};')
    with Path(dump).open('rb') as data:
        result = subprocess.run(['docker', 'exec', '-i', live.DB_CONTAINER, 'pg_restore', '-U', live.DB_USER, '-d', PROD_DB, '--no-owner'], stdin=data, capture_output=True, timeout=600)
    if result.returncode != 0:
        raise ReleaseError('운영 DB 복원 실패: ' + result.stderr.decode(errors='replace')[-400:])
    subprocess.run(['docker', 'start', PROD_CONTAINER], capture_output=True, timeout=120)
    live.wait_started(PROD_CONTAINER, PROD_URL + '/')


class _Client:
    """Operation's API, signed in as the platform's own account."""
    def __init__(self):
        login = json.loads(_login_file('prod-deployer.json').read_text())
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        code, _ = self.call('POST', '/api/auth/login', form={'username': login['username'], 'password': login['password']})
        if code != 200:
            raise ReleaseError(f'운영 서버에 배포 계정으로 들어가지 못했습니다 ({code}).')

    def call(self, method, path, body=None, form=None):
        session = json.load(self.opener.open(PROD_URL + '/api/auth/session', timeout=30))
        headers = {session['csrf']['headerName']: session['csrf']['token'], 'Accept': 'application/json'}
        data = None
        if form is not None:
            data, headers['Content-Type'] = urllib.parse.urlencode(form).encode(), 'application/x-www-form-urlencoded'
        if body is not None:
            data, headers['Content-Type'] = json.dumps(body).encode(), 'application/json'
        try:
            with self.opener.open(urllib.request.Request(PROD_URL + path, data=data, headers=headers, method=method), timeout=60) as answer:
                text = answer.read().decode()
                return answer.status, (json.loads(text) if text.strip().startswith(('{', '[')) else text)
        except urllib.error.HTTPError as error:
            text = error.read().decode()
            return error.code, (json.loads(text) if text.strip().startswith(('{', '[')) else text)


def _apply_codes(codes):
    if not codes['groups'] and not codes['codes']:
        return
    _psql(PROD_DB, f"""
        INSERT INTO sys_code_groups SELECT * FROM json_populate_recordset(NULL::sys_code_groups, {_literal(codes['groups'])}::json)
        ON CONFLICT (group_code) DO UPDATE SET group_name = EXCLUDED.group_name, description = EXCLUDED.description, enabled = EXCLUDED.enabled;
        INSERT INTO sys_codes SELECT * FROM json_populate_recordset(NULL::sys_codes, {_literal(codes['codes'])}::json)
        ON CONFLICT (group_code, code) DO UPDATE SET code_name = EXCLUDED.code_name, sort_order = EXCLUDED.sort_order, enabled = EXCLUDED.enabled;""")


def _apply_menus(menus):
    """Operation's menu tree becomes development's: a program's menu keeps its row (so the permissions given on it stay),
    folders are matched by their place, and what development no longer has is removed."""
    if not menus['modules']:
        return
    statements = [f"""INSERT INTO sys_modules SELECT * FROM json_populate_recordset(NULL::sys_modules, {_literal(menus['modules'])}::json)
        ON CONFLICT (module_code) DO UPDATE SET module_name = EXCLUDED.module_name, icon = EXCLUDED.icon, sort_order = EXCLUDED.sort_order, enabled = EXCLUDED.enabled;"""]
    _psql(PROD_DB, '\n'.join(statements))
    programs = {row for row in _psql(PROD_DB, "SELECT to_json(program_code) FROM sys_programs", rows=True)}
    current = _psql(PROD_DB, "SELECT row_to_json(m) FROM sys_menus m", rows=True)
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
                _psql(PROD_DB, f"UPDATE sys_menus SET {fields} WHERE menu_id = {folder_ids[key]};")
            else:
                folder_ids[key] = int(_psql(PROD_DB, f"""INSERT INTO sys_menus (module_code, parent_id, menu_name, sort_order, enabled, icon, menu_type)
                    VALUES ({text(item['module'])}, {parent or 'NULL'}, {text(item['name'])}, {int(item['sort'])}, {'TRUE' if item['enabled'] else 'FALSE'}, {text(item.get('icon'))}, 'FOLDER') RETURNING menu_id;""").strip())
            kept.add(folder_ids[key])
        elif item['program'] in programs:     # a screen that did not reach operation has no menu there
            if item['program'] in program_ids:
                _psql(PROD_DB, f"UPDATE sys_menus SET {fields} WHERE menu_id = {program_ids[item['program']]};")
            else:
                program_ids[item['program']] = int(_psql(PROD_DB, f"""INSERT INTO sys_menus (module_code, parent_id, program_code, menu_name, sort_order, enabled, icon, menu_type)
                    VALUES ({text(item['module'])}, {parent or 'NULL'}, {text(item['program'])}, {text(item['name'])}, {int(item['sort'])}, {'TRUE' if item['enabled'] else 'FALSE'}, {text(item.get('icon'))}, 'PROGRAM') RETURNING menu_id;""").strip())
            kept.add(program_ids[item['program']])
    gone = [row['menu_id'] for row in current if row['menu_id'] not in kept]
    if gone:
        _psql(PROD_DB, f"DELETE FROM sys_menus WHERE menu_id IN ({', '.join(str(item) for item in gone)});")


def _marks(definitions):
    """A short mark of each definition as development holds it. What operation holds is the same definition written out
    again by its own server (defaults filled in), so the two texts cannot be compared; the marks of what was last shipped can."""
    return {key: hashlib.sha1(json.dumps(row['definition'], ensure_ascii=False, sort_keys=True).encode()).hexdigest() for key, row in definitions.items()}


def _shipped(state):
    last = next((item for item in history(state, 200) if item.get('success')), None)
    return (last or {}).get('shipped') or {}


def _apply_definitions(definitions, note, shipped):
    """New and changed definitions go in through operation's API. First without the parts that may name a screen
    made later (tried again while any is still accepted), then whole."""
    there, marks = _definitions(PROD_DB), _marks(definitions)
    todo = {key: row for key, row in definitions.items() if key not in there or shipped.get(key) != marks[key]}
    result = {'new': [definitions[key]['definition']['title'] for key in todo if key not in there],
              'changed': [definitions[key]['definition']['title'] for key in todo if key in there],
              'same': len(definitions) - len(todo), 'only_there': [row['definition']['title'] for key, row in there.items() if key not in definitions], 'failed': []}
    if not todo:
        return result
    client = _Client()

    def put(key, definition):
        body = {'definition': definition, 'status': 'PUBLISHED'}
        if key not in there:
            body['programCode'] = todo[key]['programCode']
        code, answer = client.call('PUT', f'/api/system/definitions/{key}', body)
        return None if code == 200 else f"{(answer.get('detail') or answer.get('message') or answer) if isinstance(answer, dict) else answer} ({code})"
    waiting, problems = dict(todo), {}
    while waiting:
        done = []
        for key, row in waiting.items():
            problems[key] = put(key, {name: value for name, value in row['definition'].items() if name not in CARRIED})
            if problems[key] is None:
                done.append(key)
                there.setdefault(key, {'definition': None})
        if not done:
            break
        for key in done:
            waiting.pop(key)
            problems.pop(key)
        note(f'화면 정의 {len(todo) - len(waiting)}/{len(todo)}')
    for key, row in todo.items():
        if key not in waiting and any(row['definition'].get(name) for name in CARRIED):
            problem = put(key, row['definition'])
            if problem:
                problems[key] = problem
    result['failed'] = [{'title': todo[key]['definition']['title'], 'reason': str(reason)[:300]} for key, reason in problems.items() if reason]
    return result


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


def status(project, state):
    """For the platform's home: is there an operating copy, what did the last release carry, what has not gone out yet."""
    out = {'url': PROD_URL, 'exists': False, 'last': next((item for item in history(state) if item.get('success')), None), 'pending': None}
    try:
        out['exists'] = _database_exists(PROD_DB) and _mounted(PROD_CONTAINER, '/app/app.jar') is not None
        here = _definitions(live.DB_NAME)
        there, shipped, marks = (_definitions(PROD_DB) if out['exists'] else {}), _shipped(state), _marks(here)
        out['pending'] = {'new': [row['definition']['title'] for key, row in here.items() if key not in there],
                          'changed': [row['definition']['title'] for key, row in here.items() if key in there and shipped.get(key) != marks[key]],
                          'program': bool(out['exists']) and _mounted(PROD_CONTAINER, '/app/app.jar') != _mounted(live.CONTAINER, '/app/app.jar')}
    except Exception as error:      # the home page still opens when docker is down
        out['error'] = str(error)[:200]
    return out


def deploy(project, state, log=None, ref=None):
    """Record, then carry everything to operation. ref: put back an earlier release (its tag) instead of the present state.
    Returns the release record (success False tells the step and why; operation is then as it was)."""
    note = log or (lambda *_: None)
    stamp = time.strftime('%Y%m%d%H%M%S')
    release = {'stamp': stamp, 'started_at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'url': PROD_URL, 'rollback_of': ref}
    step, dump, first = 'record', None, False
    try:
        with tempfile.TemporaryDirectory() as tmp:
            if ref:
                note('이전 배포 읽기')
                previous = next((item for item in history(state, 200) if item.get('tag') == ref and item.get('success')), None)
                if not previous:
                    raise ReleaseError(f'{ref} 배포 기록을 찾지 못했습니다.')
                archive = subprocess.run(['git', 'archive', ref, 'release'], cwd=project, capture_output=True, timeout=120)
                if archive.returncode != 0:
                    raise ReleaseError('이전 배포의 파일을 꺼내지 못했습니다: ' + archive.stderr.decode(errors='replace')[-300:])
                subprocess.run(['tar', '-x', '-C', tmp], input=archive.stdout, check=True, timeout=120)
                bundle, jar, built = Path(tmp) / 'release', Path(previous['jar']), Path(previous['web'])
                if not jar.is_file() or not (built / 'index.html').is_file():
                    raise ReleaseError('이전 배포의 서버 프로그램이나 화면 파일이 남아 있지 않습니다.')
                release.update(commit=previous.get('commit'), tag=ref)
            else:
                note('기록')
                release['recorded'] = record(project)
                release['commit'] = vcs.head(project)
                bundle = Path(project) / 'release'
                step = 'program'
                note('서버 프로그램 확인')
                shipped = live.deploy(project, state, 'release', note)      # development runs the same sources first
                if not shipped.get('success'):
                    raise ReleaseError(f"개발 서버 반영 실패({shipped.get('step')}): {shipped.get('error', '')[:300]}")
                jar = Path(_mounted(live.CONTAINER, '/app/app.jar'))
                step = 'screens'
                built, _ = _build_web(project, note)
            release.update(jar=str(jar), web=str(built))
            definitions, codes, menus = _read_bundle(bundle)
            step = 'environment'
            first = not _database_exists(PROD_DB)
            if first:
                note('운영 환경 만들기')
                _psql('postgres', f'CREATE DATABASE "{PROD_DB}" OWNER {live.DB_USER};')
            else:
                step = 'backup'
                note('운영 DB 백업')
                dump = _backup_prod(stamp)
                release['backup'] = str(dump)
            step = 'start'
            _place_web(built)
            if _mounted(PROD_CONTAINER, '/app/app.jar') != str(jar) or first:
                note('운영 서버 시작')
                _start_prod(jar, tmp)
            _accounts()
            if first:       # operation starts out looking like development (system name, logo, theme); from then on its settings are its own
                settings = _psql(live.DB_NAME, "SELECT row_to_json(s) FROM sys_settings s", rows=True)
                if settings:
                    _psql(PROD_DB, f"INSERT INTO sys_settings SELECT * FROM json_populate_recordset(NULL::sys_settings, {_literal(settings)}::json) ON CONFLICT (setting_key) DO UPDATE SET setting_value = EXCLUDED.setting_value;")
            step = 'codes'
            note('공통 코드')
            _apply_codes(codes)
            step = 'definitions'
            applied = _apply_definitions(definitions, note, _shipped(state))
            release['shipped'] = _marks(definitions)
            release['screens'] = applied
            if applied['failed']:
                raise ReleaseError('운영에서 받아들여지지 않은 화면: ' + '; '.join(f"{item['title']} - {item['reason']}" for item in applied['failed'][:5]))
            step = 'menus'
            note('메뉴 편성')
            _apply_menus(menus)
        if not ref:
            release['tag'] = f'release-{stamp}'
            vcs.tag(project, release['tag'], '운영 배포 ' + release['started_at'])
        release.update(success=True, first=first)
    except Exception as error:
        release.update(success=False, step=step, error=str(error)[-1200:])
        if dump is not None and step in ('codes', 'definitions', 'menus'):      # operation's data was touched: put it back whole
            try:
                _restore_prod(dump)
                release['restored'] = True
            except Exception as again:
                release['restored'] = False
                release['restore_error'] = str(again)[-400:]
    release['finished_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    (_releases(state) / f'{stamp}.json').write_text(json.dumps(release, ensure_ascii=False, indent=1), encoding='utf-8')
    return release


def rollback(project, state, log=None):
    """Put operation back to the release before the one in effect (definitions, server program and screens; operation's records stay)."""
    done = [item for item in history(state, 200) if item.get('success')]
    if len(done) < 2:
        raise ReleaseError('되돌릴 이전 배포가 없습니다.')
    current = done[0]
    target = next((item for item in done[1:] if item.get('tag') != current.get('tag')), None)
    if not target:
        raise ReleaseError('되돌릴 이전 배포가 없습니다.')
    return deploy(project, state, log, ref=target['tag'])


COMMANDS = (('rollback', re.compile(r'(배포|운영|버전).*(되돌|롤백|이전으로)|(되돌|롤백).*(배포|운영)')),
            ('deploy', re.compile(r'배포|운영 ?(에|으로|서버|환경).*(올려|반영|내보내|적용)|릴리[스즈]')),
            ('record', re.compile(r'커밋|깃 ?(에|으로|허브)|저장소에|버전.*(남겨|기록|저장)|변경.*(기록|저장)해')))


def command(goal):
    """Is this request an order to record or deploy (not a screen to make)? Returns 'record' | 'deploy' | 'rollback' | None."""
    text = ' '.join((goal or '').split())
    # An order is short and does not describe a screen; "배포 현황 화면 만들어줘" is a screen to make.
    if not text or len(text) > 60 or re.search(r'화면|항목|만들|추가|집계|현황|등록 ?해|고쳐|바꿔|삭제', text):
        return None
    return next((name for name, pattern in COMMANDS if pattern.search(text)), None)


def say(kind, result):
    """The outcome in plain words."""
    if kind == 'record':
        if not result.get('commit'):
            return '기록할 변경이 없습니다. 이미 모두 기록되어 있습니다.'
        parts = [f"화면 {len(result['screens'])}개 ({', '.join(result['screens'][:5])}{' …' if len(result['screens']) > 5 else ''})" if result['screens'] else '',
                 '공통 코드' if result.get('codes') else '', '메뉴 편성' if result.get('menus') else '', f"소스 파일 {result['source_files']}개" if result.get('source_files') else '']
        tail = ' 원격 저장소에도 올렸습니다.' if result.get('pushed') is True else f" 원격 저장소에는 올리지 못했습니다: {result['pushed']}" if result.get('pushed') else ''
        return f"기록했습니다 ({result['commit'][:7]}): " + ', '.join(filter(None, parts)) + '.' + tail
    if not result.get('success'):
        back = ' 운영 DB는 배포 전 상태로 되돌렸습니다.' if result.get('restored') else ' 운영 DB를 되돌리지 못했습니다 - 확인이 필요합니다.' if result.get('restored') is False else ' 운영은 그대로입니다.'
        return f"배포하지 못했습니다 ({result.get('step')} 단계): {result.get('error', '')[:400]}{back}"
    screens = result.get('screens') or {}
    lines = [('이전 배포로 되돌렸습니다' if result.get('rollback_of') else '운영 환경을 새로 만들고 배포했습니다' if result.get('first') else '운영에 배포했습니다') + f" - {result['url']}"]
    if screens.get('new'):
        lines.append(f"새 화면 {len(screens['new'])}개: {', '.join(screens['new'][:8])}{' …' if len(screens['new']) > 8 else ''}")
    if screens.get('changed'):
        lines.append(f"바뀐 화면 {len(screens['changed'])}개: {', '.join(screens['changed'][:8])}{' …' if len(screens['changed']) > 8 else ''}")
    if not screens.get('new') and not screens.get('changed'):
        lines.append('화면 정의는 바뀐 것이 없습니다.')
    if screens.get('only_there'):
        lines.append(f"⚠ 개발에는 없고 운영에만 있는 화면 {len(screens['only_there'])}개는 자료 보호를 위해 그대로 두었습니다: {', '.join(screens['only_there'][:5])}")
    if result.get('first'):
        lines.append('운영 관리자(admin)의 비밀번호는 platform/state/auth/prod-login.json 에 있습니다. 처음 들어가서 바꾸세요.')
    return '\n'.join(lines)
