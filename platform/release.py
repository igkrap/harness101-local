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

"운영에 배포해줘" builds a pack and installs it on this machine's own operating copy (port 5300).
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
import windows_pack

PROD_PORT, PROD_PROJECT, TRIAL_PORT = 5300, 'local-only-ops', 5390
OLD_CONTAINER = 'mdi-prod-api'      # the first operating copy (before packs); stopped when the pack-based one takes its port
PROD_URL = f'http://127.0.0.1:{PROD_PORT}'
PROD_HOME = live.SHARE / 'prod/local-only'
PACKS = live.SHARE / 'packs/local-only'
VENDOR = live.SHARE / 'vendor/windows'      # the Windows runtime pieces (Java, PostgreSQL ...), downloaded once
PWSH = live.SHARE / 'tools/pwsh/pwsh'        # PowerShell, to parse-check the Windows scripts (they cannot be run on this machine)
APP_IMAGE = 'eclipse-temurin:17-jre'


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
    settings = _psql(live.DB_NAME, "SELECT row_to_json(s) FROM sys_settings s WHERE setting_key NOT LIKE 'release\\_%' ORDER BY setting_key", rows=True)
    for name, value in (('codes.json', _codes(live.DB_NAME)), ('menus.json', _menus(live.DB_NAME)), ('settings.json', settings)):
        path, text = folder / name, _dump(value)
        if not path.is_file() or path.read_text(encoding='utf-8') != text:
            path.write_text(text, encoding='utf-8')
    readme = folder / 'README.md'
    if not readme.is_file():
        readme.write_text('# 배포 묶음\n\n플랫폼이 "커밋해줘", "운영에 배포해줘" 요청 때 개발 DB에서 뽑아 적는 파일입니다. 손으로 고치지 않습니다.\n\n'
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


def record(project, message=None):
    """Write the bundle and commit every pending change of the project. Returns what was recorded (commit None = nothing new).
    Another git command may be at work in the project at the same moment (the platform's own pages read its state): then it waits and tries again."""
    for attempt in range(6):
        try:
            return _record(project, message)
        except RuntimeError as error:
            if 'index.lock' not in str(error) or attempt == 5:
                raise
            time.sleep(1.5)


def _record(project, message=None):
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
    built = live.SHARE / 'prod/local-only/builds' / _web_hash(frontend)[:16]
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
        note('기록')
        out['recorded'] = record(project)
        out['commit'] = vcs.head(project)
        step = 'program'
        note('서버 프로그램 확인')
        shipped = live.deploy(project, state, 'pack', note)       # development runs the same sources first, so what is packed is what was tried
        if not shipped.get('success'):
            raise ReleaseError(f"개발 서버 반영 실패({shipped.get('step')}): {shipped.get('error', '')[:300]}")
        jar = Path(_mounted(live.CONTAINER, '/app/app.jar'))
        step = 'screens'
        built = _build_web(project, note)
        step = 'assemble'
        note('팩 조립')
        definitions = _definitions(live.DB_NAME)
        name = f'setup-pack-{stamp}'
        folder = PACKS / name
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
        made = windows_pack.write_zips(folder, version, VENDOR, PACKS, name, PWSH)
        files = {kind: {'name': made[kind].name, 'file': str(made[kind]), 'size': made[kind].stat().st_size} for kind in ('install', 'update')}
        out.update(success=True, folder=str(folder), name=name, files=files, postgres=made['postgres'], scripts_parsed=made['script_check'] is not None,
                   screens=len(definitions), shipped=_marks(definitions), tag=f'pack-{stamp}')
        vcs.tag(project, out['tag'], '운영 셋업 팩 ' + out['started_at'])
        for old in sorted(path for path in PACKS.glob('setup-pack-*') if path.is_dir())[:-5]:       # the five newest packs are kept
            shutil.rmtree(old, ignore_errors=True)
            for file in PACKS.glob(old.name + '*.zip'):
                file.unlink()
    except Exception as error:
        out.update(success=False, step=step, error=str(error)[-1200:])
    out['finished_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    (_releases(state) / f"{stamp.replace('-', '')}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    return out


# ---- this machine's own operating copy: the pack, installed here ----

def _copy_home():
    return live.SHARE / 'prod/local-only/copy'


def _install_here(folder, note):
    """Put a pack's contents into the local copy (its .env and backups stay) and start it. Returns (status, detail, first)."""
    home = _copy_home()
    first = not (home / '.env').is_file()
    home.mkdir(parents=True, exist_ok=True)
    if first:
        subprocess.run(['docker', 'rm', '-f', OLD_CONTAINER], capture_output=True)       # it holds port 5300; its database (mdi_prod) is left where it is
    else:
        note('운영 DB 백업')
        (home / 'backups').mkdir(exist_ok=True)
        dump = _compose(home, 'exec', '-T', 'db', 'pg_dump', '-U', 'mdi', '-Fc', 'app', stdin=b'', check=False)
        if dump.returncode != 0 or not dump.stdout:
            raise ReleaseError('운영 DB 백업 실패: ' + dump.stderr.decode(errors='replace')[-300:])
        (home / 'backups' / f"db-{time.strftime('%Y%m%d-%H%M%S')}.dump").write_bytes(dump.stdout)
    live.sh(['rsync', '-a', '--delete', '--exclude', '.env', '--exclude', 'backups', str(folder) + '/', str(home) + '/'], timeout=300)
    values = _write_env(home, PROD_PROJECT, PROD_PORT, '127.0.0.1')
    login = Path(__file__).resolve().parent / 'state/auth/prod-login.json'
    if first:       # the first administrator's password, where the other sign-in files are kept (0600)
        descriptor = os.open(login, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, 'w') as out:
            json.dump({'username': 'admin', 'password': values['ADMIN_PASSWORD'], 'url': PROD_URL}, out)
    note('운영 서버 시작')
    _compose(home, 'up', '-d', '--force-recreate', 'app') if not first else _compose(home, 'up', '-d')
    status, detail = _wait_copy(home)
    return status, detail, first


def deploy(project, state, log=None, previous=False):
    """Build a pack and install it on this machine's operating copy. previous: install the pack before the one in effect instead."""
    note = log or (lambda *_: None)
    out = {'kind': 'deploy', 'stamp': time.strftime('%Y%m%d%H%M%S') + '1', 'started_at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'url': PROD_URL, 'rollback': previous}
    step = 'pack'
    try:
        if previous:
            done = [item for item in history(state, 200) if item.get('success') and item.get('kind') == 'deploy' and Path(item.get('pack_folder', '')).is_dir()]
            target = next((item for item in done[1:] if item.get('pack_folder') != done[0].get('pack_folder')), None) if done else None
            if not target:
                raise ReleaseError('되돌릴 이전 배포(의 팩)가 남아 있지 않습니다.')
            made = {'folder': target['pack_folder'], 'name': target.get('pack'), 'shipped': target.get('shipped'), 'screens': target.get('screens')}
        else:
            made = pack(project, state, note)
            if not made.get('success'):
                raise ReleaseError(f"팩을 만들지 못했습니다({made.get('step')}): {made.get('error', '')[:600]}")
        out.update(pack=made.get('name'), pack_folder=made['folder'], shipped=made.get('shipped'), screens=made.get('screens'))
        step = 'install'
        status, detail, first = _install_here(Path(made['folder']), note)
        out.update(first=first, detail=detail)
        if status != 'ok':
            before = next((item for item in history(state, 200) if item.get('success') and item.get('kind') == 'deploy' and Path(item.get('pack_folder', '')).is_dir()), None)
            if before:       # the screens were refused as a whole and nothing of them changed; put the earlier program and screens back too
                _install_here(Path(before['pack_folder']), note)
                out['restored'] = True
            raise ReleaseError('운영에서 화면이 받아들여지지 않았습니다: ' + detail)
        out['success'] = True
    except Exception as error:
        out.update(success=False, step=step, error=str(error)[-1200:])
    out['finished_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    (_releases(state) / f"{out['stamp']}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    return out


def rollback(project, state, log=None):
    return deploy(project, state, log, previous=True)


def status(project, state):
    """For the platform's home: the newest pack, this machine's operating copy, and what has been made since the last pack or deployment."""
    last_pack, last_deploy = _last(state, 'pack'), _last(state, 'deploy')
    out = {'url': PROD_URL, 'exists': (_copy_home() / '.env').is_file(), 'last': last_deploy, 'pending': None,
           'pack': last_pack and last_pack.get('files') and {'started_at': last_pack['started_at'], 'screens': last_pack.get('screens'), 'stamp': last_pack['stamp'],
                                                           'files': {kind: {'name': item['name'], 'size': item['size']} for kind, item in last_pack['files'].items()}}}
    try:
        here = _definitions(live.DB_NAME)
        marks, shipped = _marks(here), ((last_deploy or last_pack or {}).get('shipped') or {})
        out['pending'] = {'new': [row['definition']['title'] for key, row in here.items() if key not in shipped],
                          'changed': [row['definition']['title'] for key, row in here.items() if key in shipped and shipped[key] != marks[key]], 'program': False}
    except Exception as error:      # the home page still opens when docker is down
        out['error'] = str(error)[:200]
    return out


def pack_file(state, name):
    """The zip of a pack by its file name (only names this module made)."""
    if not re.fullmatch(r'setup-pack-\d{8}-\d{6}-(install|update)\.zip', name or ''):
        raise ValueError('팩 이름이 올바르지 않습니다.')
    path = PACKS / name
    if not path.is_file():
        raise ValueError('그 팩은 남아 있지 않습니다.')
    return path


COMMANDS = (('rollback', re.compile(r'(배포|운영|버전).*(되돌|롤백|이전으로)|(되돌|롤백).*(배포|운영)')),
            ('pack', re.compile(r'(셋업|셋팅|세팅|설치|운영|배포) ?(팩|패키지|꾸러미|묶음)|setup ?pack')),
            ('deploy', re.compile(r'배포|운영 ?(에|으로|서버|환경).*(올려|반영|내보내|적용|설치)|릴리[스즈]')),
            ('record', re.compile(r'커밋|깃 ?(에|으로|허브)|저장소에|버전.*(남겨|기록|저장)|변경.*(기록|저장)해')))


def command(goal):
    """Is this request an order to record, pack or deploy (not a screen to make)? Returns 'record' | 'pack' | 'deploy' | 'rollback' | None."""
    text = ' '.join((goal or '').split())
    # An order is short and does not describe a screen; "배포 현황 화면 만들어줘" is a screen to make.
    if not text or len(text) > 60 or re.search(r'화면|항목|추가|집계|현황|등록 ?해|고쳐|바꿔|삭제', text):
        return None
    return next((name for name, pattern in COMMANDS if pattern.search(text)), None)


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
    if kind == 'pack':
        if not result.get('success'):
            return f"셋업 팩을 만들지 못했습니다 ({result.get('step')} 단계): {result.get('error', '')[:500]}"
        files = result['files']
        return (f"운영 셋업 팩을 만들었습니다 (윈도우 서버용, 화면 {result['screens']}개):\n"
                f"  최초 셋업 팩  {files['install']['name']} ({_size(files['install']['size'])}) - 빈 서버에 자바·PostgreSQL {result.get('postgres', '')}·DB·서비스까지 설치 (install.bat)\n"
                f"  업데이트 팩   {files['update']['name']} ({_size(files['update']['size'])}) - 설치된 서버를 새 버전으로 (update.bat, 실패하면 자동으로 이전 상태로)\n"
                f"팩에 든 프로그램·화면·화면 정의는 빈 환경에 설치해 확인했습니다 ({result.get('trial', '')}; 관리자 로그인 확인).\n"
                f"⚠ 윈도우용 설치 스크립트는 문법 검사만 했습니다 (이 맥에서는 윈도우 설치를 돌려 볼 수 없음). 실제 윈도우에서 한 번 설치해 보고 쓰세요.\n"
                f"파일 위치: {PACKS}")
    if not result.get('success'):
        back = ' 운영은 이전 팩으로 되돌렸습니다.' if result.get('restored') else ' 운영은 그대로입니다.'
        return f"배포하지 못했습니다 ({result.get('step')} 단계): {result.get('error', '')[:400]}{back}"
    lines = [('이전 팩으로 되돌렸습니다' if result.get('rollback') else '이 맥에 운영 한 벌을 새로 설치했습니다' if result.get('first') else '운영에 배포했습니다') + f" - {result['url']} ({result.get('detail', '')})"]
    if result.get('pack'):
        lines.append(f"설치한 팩: {result['pack']}")
    if result.get('first'):
        lines.append('운영 관리자(admin)의 첫 비밀번호는 platform/state/auth/prod-login.json 에 있습니다. 들어가서 바꾸세요.')
    return '\n'.join(lines)
