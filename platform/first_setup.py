"""First setup of the platform's own working environment on a machine that has none of it yet.

What the platform expects to find (and until now was put together by hand):
  - two docker networks and the Maven cache volume the server is built with
  - the development database (container mdi-db, databases mdi_local and mdi_local_test)
  - the administrator's sign-in files (state/auth/local-login.json, server.env)
  - the app's server built from the project's sources and running (container mdi-local-api, port 8083),
    holding the screens that came with the project (its release/ folder)
  - the platform's own account for checking screens (state/auth/verifier-login.json)

Every step looks first and does nothing where the thing is already there, so it can be run again after a failure.
`--suffix` (with other ports) makes a second, separate set beside an existing one - used to try a platform pack
on a machine that already runs the platform; `--remove` takes such a set away again.
"""
import argparse
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

POSTGRES_IMAGE, BUILD_IMAGE = 'postgres:17-alpine', 'maven:3.9-eclipse-temurin-17'
ADMIN = {'username': 'admin', 'password': 'admin'}       # development only; the operating copies get their own from a setup pack
PERMISSIONS = 'workspace:admin,inventory:read,inventory:write,work-sites:read,work-sites:write'


class SetupError(RuntimeError):
    pass


def sh(cmd, timeout=1800, check=True, **kw):
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)
    if check and result.returncode != 0:
        raise SetupError(f"{' '.join(str(part) for part in cmd[:4])} 실패: " + (result.stderr or result.stdout)[-700:])
    return result


class Setup:
    def __init__(self, root, suffix='', db_port=5433, api_port=8083, state=None, share=None, log=print):
        self.root = Path(root).resolve()                       # holds platform/ and local-only/
        self.project = self.root / 'local-only'
        self.state = Path(state).resolve() if state else self.root / 'platform/state'
        self.share = Path(share).resolve() if share else Path.home() / '.local/share/local-workshop'
        self.suffix, self.db_port, self.api_port, self.log = suffix, db_port, api_port, log
        self.db, self.api = 'mdi-db' + suffix, 'mdi-local-api' + suffix
        self.internal, self.public, self.m2 = 'mdi-internal' + suffix, 'mdi-public' + suffix, 'mdi-m2' + suffix
        self.data = 'mdi-db-data' + suffix

    # ---- docker ----
    def docker(self):
        if sh(['docker', 'info'], check=False, timeout=60).returncode != 0:
            raise SetupError('도커가 실행 중이 아닙니다. 도커(Docker Desktop, OrbStack 또는 colima)를 켠 뒤 다시 실행하세요.')

    def _exists(self, kind, name):
        return sh(['docker', kind, 'inspect', name], check=False, timeout=60).returncode == 0

    def base(self):
        self.log('도커 네트워크와 빌드 캐시')
        if not self._exists('network', self.internal):
            sh(['docker', 'network', 'create', '--internal', self.internal])
        if not self._exists('network', self.public):
            sh(['docker', 'network', 'create', self.public])
        if not self._exists('volume', self.m2):
            sh(['docker', 'volume', 'create', self.m2])
        for image in (POSTGRES_IMAGE, BUILD_IMAGE):
            if not self._exists('image', image):
                self.log(f'  이미지 받는 중: {image}')
                sh(['docker', 'pull', '-q', image], timeout=3600)

    def psql(self, sql, db='postgres'):
        result = subprocess.run(['docker', 'exec', '-i', self.db, 'psql', '-U', 'mdi', '-d', db, '-v', 'ON_ERROR_STOP=1', '-q', '-At'], input=sql, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise SetupError('DB 작업 실패: ' + result.stderr[-400:])
        return result.stdout.strip()

    def database(self):
        self.log('개발 데이터베이스')
        if not self._exists('container', self.db):
            sh(['docker', 'run', '-d', '--name', self.db, '--network', self.internal, '--restart', 'unless-stopped',
                '-e', 'POSTGRES_USER=mdi', '-e', 'POSTGRES_PASSWORD=mdi', '-e', 'POSTGRES_DB=mdi',
                '-v', f'{self.data}:/var/lib/postgresql/data', '-p', f'127.0.0.1:{self.db_port}:5432', POSTGRES_IMAGE])
            sh(['docker', 'network', 'connect', self.public, self.db])
        else:
            sh(['docker', 'start', self.db], check=False)
        end = time.time() + 90
        while sh(['docker', 'exec', self.db, 'pg_isready', '-U', 'mdi', '-d', 'mdi'], check=False, timeout=30).returncode != 0:
            if time.time() > end:
                raise SetupError('데이터베이스가 90초 안에 시작하지 않았습니다.')
            time.sleep(2)
        time.sleep(1)
        for name in ('mdi_local', 'mdi_local_test'):
            if not self.psql(f"SELECT 1 FROM pg_database WHERE datname = '{name}'"):
                self.psql(f'CREATE DATABASE "{name}" OWNER mdi')

    # ---- the app's server ----
    def source_hash(self):
        backend, digest = self.project / 'backend', hashlib.sha256()
        for path in sorted([*(backend / 'src/main').rglob('*'), backend / 'pom.xml']):
            if path.is_file():
                digest.update(str(path.relative_to(backend)).encode())
                digest.update(path.read_bytes())
        return digest.hexdigest()

    def build(self):
        """The server program from the project's sources. The first build fetches what Maven needs into the cache volume; later builds (the platform's own) work without the network."""
        digest = self.source_hash()
        target = self.share / 'artifacts/local-only/backend' / f'app-setup-{digest[:12]}.jar'
        if target.is_file():
            return target, digest
        self.log('서버 프로그램 빌드 (처음에는 필요한 것을 내려받느라 몇 분 걸립니다)')
        self.share.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=str(self.share)) as tmp:
            scratch = Path(tmp) / 'backend'
            shutil.copytree(self.project / 'backend', scratch, ignore=shutil.ignore_patterns('target', 'node_modules', '.git'))
            sh(['docker', 'run', '--rm', '-v', f'{scratch}:/app', '-w', '/app', '-v', f'{self.m2}:/root/.m2', BUILD_IMAGE, 'mvn', '-q', '-B', '-DskipTests', 'package'], timeout=3600)
            # The platform builds with "-o" (no network) from now on: prove now that the cache is complete enough for that.
            sh(['docker', 'run', '--rm', '-v', f'{scratch}:/app', '-w', '/app', '-v', f'{self.m2}:/root/.m2', BUILD_IMAGE, 'mvn', '-q', '-B', '-o', '-DskipTests', 'package'], timeout=1800)
            jars = [path for path in (scratch / 'target').glob('*.jar') if not path.name.endswith(('-plain.jar', '.original'))]
            if len(jars) != 1:
                raise SetupError(f'빌드 산출 JAR를 하나로 특정하지 못했습니다: {[path.name for path in jars]}')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(jars[0], target)
        return target, digest

    def accounts(self):
        """The administrator's sign-in for development: the password file for people and scripts, its hash for the server."""
        folder = self.state / 'auth'
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        login, server = folder / 'local-login.json', folder / 'server.env'
        if login.is_file() and server.is_file():
            return server
        self.log('관리자 계정')
        hashed = self.psql(f"CREATE EXTENSION IF NOT EXISTS pgcrypto; SELECT crypt('{ADMIN['password']}', gen_salt('bf', 12));", 'mdi_local').splitlines()[-1]
        if not re.fullmatch(r'\$2[aby]\$\d\d\$[./A-Za-z0-9]{53}', hashed):
            raise SetupError('관리자 비밀번호 해시를 만들지 못했습니다.')
        for path, content in ((login, json.dumps(ADMIN, indent=2) + '\n'),
                              (server, f"WORKSPACE_ADMIN_USERNAME={ADMIN['username']}\nWORKSPACE_ADMIN_PASSWORD_HASH={{bcrypt}}{hashed}\n")):
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, 'w') as out:
                out.write(content)
        return server

    def _run_api(self, jar, server_env, with_release):
        sh(['docker', 'rm', '-f', self.api], check=False)
        with tempfile.TemporaryDirectory() as tmp:
            envfile = Path(tmp) / 'app.env'
            envfile.touch(mode=0o600)
            envfile.write_text(server_env.read_text() + f'DB_URL=jdbc:postgresql://{self.db}:5432/mdi_local\n')
            sh(['docker', 'run', '-d', '--name', self.api, '--network', self.internal, '--env-file', str(envfile), '--restart', 'unless-stopped',
                '-v', f'{jar}:/app/app.jar:ro', *(['-v', f"{self.project / 'release'}:/app/release:ro"] if with_release else []),
                '-p', f'127.0.0.1:{self.api_port}:8080', BUILD_IMAGE, 'java', '-jar', '/app/app.jar'], timeout=180)
        sh(['docker', 'network', 'connect', self.public, self.api])
        end = time.time() + 240
        while time.time() < end:
            logs = subprocess.run(['docker', 'logs', self.api], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout
            if 'APPLICATION FAILED TO START' in logs:
                raise SetupError('서버 시작 실패: ' + logs[-800:])
            if re.search(r'Started \w*Application', logs):
                time.sleep(2)
                return
            time.sleep(3)
        raise SetupError('서버가 240초 안에 시작하지 않았습니다.')

    def server(self, jar, digest):
        """Start the app's server. The first time it is started once with the project's release/ beside it, so the screens that
        came with the project are in the development database; then again without, because in development screens are made, not loaded."""
        running = sh(['docker', 'inspect', '-f', '{{.State.Running}}', self.api], check=False).stdout.strip() == 'true'
        screens = self.psql("SELECT to_regclass('public.app_definitions') IS NOT NULL", 'mdi_local') == 't' and int(self.psql('SELECT COUNT(*) FROM app_definitions', 'mdi_local') or 0)
        if running and screens:
            return screens
        server_env = self.accounts()
        bundle = (self.project / 'release/definitions').is_dir() and not screens
        if bundle:
            self.log('서버 시작 + 프로젝트에 든 화면 반영')
            self._run_api(jar, server_env, True)
            status = self.psql("SELECT setting_value FROM sys_settings WHERE setting_key = 'release_status'", 'mdi_local')
            if status != 'ok':
                raise SetupError('프로젝트에 든 화면을 반영하지 못했습니다: ' + self.psql("SELECT setting_value FROM sys_settings WHERE setting_key = 'release_detail'", 'mdi_local'))
        self.log('서버 시작')
        self._run_api(jar, server_env, False)
        record = self.state / 'deploys'
        record.mkdir(parents=True, exist_ok=True)
        (record / 'current.json').write_text(json.dumps({'stamp': time.strftime('%Y%m%d%H%M%S'), 'label': 'setup', 'source_sha': digest, 'jar': str(jar), 'success': True}, ensure_ascii=False, indent=1))
        return int(self.psql('SELECT COUNT(*) FROM app_definitions', 'mdi_local') or 0)

    def verifier(self):
        """The platform's own administrator-level account for looking at screens (one live sign-in per account, so it must not share the person's)."""
        target = self.state / 'auth/verifier-login.json'
        if target.is_file() and self.psql("SELECT 1 FROM workspace_users WHERE username = 'verifier'", 'mdi_local'):
            return
        self.log('화면 검증 전용 계정')
        password = secrets.token_urlsafe(24)
        try:
            self.psql(f"""CREATE EXTENSION IF NOT EXISTS pgcrypto;
                INSERT INTO workspace_users (username, password_hash, display_name, permissions, enabled, status)
                VALUES ('verifier', '{{bcrypt}}' || crypt('{password}', gen_salt('bf', 10)), '화면 검증 전용 (플랫폼)', '{PERMISSIONS}', TRUE, 'ACTIVE')
                ON CONFLICT (username) DO UPDATE SET password_hash = EXCLUDED.password_hash, enabled = TRUE, status = 'ACTIVE';
                INSERT INTO sys_user_roles (username, role_code) VALUES ('verifier', 'ADMIN') ON CONFLICT DO NOTHING;""", 'mdi_local')
        except SetupError as error:
            raise SetupError(str(error).replace(password, '***'))
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, 'w') as out:
            json.dump({'username': 'verifier', 'password': password}, out)

    def signs_in(self, file):
        """Can the account in this file sign in to the server, and how many screens does it see?"""
        login = json.loads((self.state / 'auth' / file).read_text())
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        base = f'http://127.0.0.1:{self.api_port}'
        session = json.load(opener.open(base + '/api/auth/session', timeout=30))
        request = urllib.request.Request(base + '/api/auth/login', data=urllib.parse.urlencode({'username': login['username'], 'password': login['password']}).encode(),
                                         headers={session['csrf']['headerName']: session['csrf']['token'], 'Content-Type': 'application/x-www-form-urlencoded'}, method='POST')
        try:
            with opener.open(request, timeout=30) as answer:
                if answer.status != 200:
                    return None
            return len(json.load(opener.open(base + '/api/meta/definitions', timeout=30)))
        except urllib.error.HTTPError:
            return None

    def run(self):
        self.docker()
        self.base()
        self.database()
        jar, digest = self.build()
        screens = self.server(jar, digest)
        self.verifier()
        link = self.project / 'harness'
        if not link.exists() and (self.root / 'erp-harness').is_dir():
            link.symlink_to('../erp-harness')
        seen = {file: self.signs_in(file) for file in ('local-login.json', 'verifier-login.json')}
        if any(count != screens for count in seen.values()):
            raise SetupError(f'계정으로 들어가 화면을 읽지 못했습니다: {seen} (화면 {screens}개)')
        self.log(f'개발 환경 준비 완료: 화면 {screens}개, 관리자·검증 계정 로그인 확인')
        return {'screens': screens, 'jar': str(jar), 'api': f'http://127.0.0.1:{self.api_port}'}

    def remove(self):
        """Take a trial set away (never the real one: a suffix is required)."""
        if not self.suffix:
            raise SetupError('접미사 없는 실제 환경은 이 명령으로 지우지 않습니다.')
        sh(['docker', 'rm', '-f', self.api, self.db], check=False)
        sh(['docker', 'volume', 'rm', '-f', self.data, self.m2], check=False)
        sh(['docker', 'network', 'rm', self.internal, self.public], check=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument('--suffix', default='')
    parser.add_argument('--db-port', type=int, default=5433)
    parser.add_argument('--api-port', type=int, default=8083)
    parser.add_argument('--state')
    parser.add_argument('--share')
    parser.add_argument('--remove', action='store_true')
    args = parser.parse_args()
    setup = Setup(args.root, args.suffix, args.db_port, args.api_port, args.state, args.share, log=lambda text: print('· ' + text, flush=True))
    try:
        if args.remove:
            setup.remove()
        else:
            print(json.dumps(setup.run(), ensure_ascii=False))
    except SetupError as error:
        print('실패: ' + str(error))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
