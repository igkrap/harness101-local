"""Put a verified backend live: build the jar, back up the DB, rehearse the upgrade on a copy, swap the container.

The harness verifies backend work against an isolated test DB only. This step makes the result
reach the running app (8083), the way it was done by hand before: the previous container is kept
stopped under a rollback name, the live DB is dumped first, and the new jar must start against a
restored copy of that dump (Flyway upgrade included) before it touches the live DB.
"""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from sites import site      # the project in hand: its server container, database, port and folders

DB_CONTAINER = 'mdi-db'
DB_USER = 'mdi'
NETWORK = 'mdi-internal'
BUILD_IMAGE = 'maven:3.9-eclipse-temurin-17'
SHARE = Path.home() / '.local/share/local-workshop'
START_SECONDS = 180


class DeployError(RuntimeError):
    pass


def sh(cmd, timeout=900, **kw):
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)
    if result.returncode != 0:
        raise DeployError(f'{" ".join(cmd[:4])} 실패: ' + (result.stderr or result.stdout)[-600:])
    return result.stdout


def source_hash(backend):
    digest = hashlib.sha256()
    for path in sorted([*(backend / 'src/main').rglob('*'), backend / 'pom.xml']):
        if path.is_file():
            digest.update(str(path.relative_to(backend)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def build_jar(backend, label, digest):
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp) / 'backend'
        shutil.copytree(backend, scratch, ignore=shutil.ignore_patterns('target', 'node_modules', '.git'), symlinks=False)
        sh(['docker', 'run', '--rm', '-v', f'{scratch}:/app', '-w', '/app', '-v', 'mdi-m2:/root/.m2', BUILD_IMAGE,
            'mvn', '-q', '-B', '-o', '-DskipTests', 'package'], timeout=900)
        jars = [p for p in (scratch / 'target').glob('*.jar') if not p.name.endswith(('-plain.jar', '.original'))]
        if len(jars) != 1:
            raise DeployError(f'빌드 산출 JAR를 하나로 특정하지 못했습니다: {[p.name for p in jars]}')
        site().artifacts.mkdir(parents=True, exist_ok=True)
        target = site().artifacts / f'app-{label}-{digest[:12]}.jar'
        shutil.copy2(jars[0], target)
    return target


def backup(stamp):
    site().backups.mkdir(parents=True, exist_ok=True)
    path = site().backups / f'{site().db}-before-deploy-{stamp}.dump'
    with path.open('wb') as out:
        result = subprocess.run(['docker', 'exec', DB_CONTAINER, 'pg_dump', '-U', DB_USER, '-Fc', site().db],
                                stdout=out, stderr=subprocess.PIPE, timeout=600)
    if result.returncode != 0 or path.stat().st_size == 0:
        raise DeployError('DB 백업 실패: ' + result.stderr.decode(errors='replace')[-400:])
    return path


def live_config():
    info = json.loads(sh(['docker', 'inspect', site().api_container]))[0]
    return {'image': info['Config']['Image'], 'env': info['Config']['Env'],
            'ports': info['HostConfig'].get('PortBindings') or {},
            'networks': list((info.get('NetworkSettings') or {}).get('Networks') or {}) or [NETWORK]}


def env_file(env, directory, db_url=None):
    """Container env (holds the admin password) goes through a 0600 file, never argv or logs."""
    lines = [e for e in env if not e.startswith('DB_URL=')] + ['DB_URL=' + (db_url or next(
        (e.split('=', 1)[1] for e in env if e.startswith('DB_URL=')), f'jdbc:postgresql://{DB_CONTAINER}:5432/{site().db}'))]
    path = Path(directory) / 'app.env'
    path.touch(mode=0o600)
    path.write_text('\n'.join(lines) + '\n')
    return path


def run_app(name, config, jar, envfile, publish=True):
    cmd = ['docker', 'run', '-d', '--name', name, '--network', NETWORK, '--env-file', str(envfile),
           *(['--restart', 'unless-stopped'] if publish else []),
           '-v', f'{jar}:/app/app.jar:ro']
    if publish:
        for port, binds in config['ports'].items():
            for bind in binds or []:
                cmd += ['-p', f"{bind.get('HostIp') or '127.0.0.1'}:{bind['HostPort']}:{port.split('/')[0]}"]
    sh(cmd + [config['image'], 'java', '-jar', '/app/app.jar'], timeout=120)
    if publish:
        # The DB network is internal (no host ports); the live container also sits on a public bridge.
        for network in config.get('networks', []):
            if network != NETWORK:
                sh(['docker', 'network', 'connect', network, name], timeout=60)


def wait_started(name, url=None):
    end = time.time() + START_SECONDS
    while time.time() < end:
        logs = subprocess.run(['docker', 'logs', name], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout
        state = sh(['docker', 'inspect', '-f', '{{.State.Running}}', name]).strip()
        if 'APPLICATION FAILED TO START' in logs or state != 'true':
            raise DeployError(f'{name} 시작 실패: ' + logs[-800:])
        if 'Started ' in logs:
            if not url:
                return
            try:
                urllib.request.urlopen(url, timeout=5)
                return
            except urllib.error.HTTPError:
                return  # any HTTP answer (401/403/404) means the server is serving
            except OSError:
                pass
        time.sleep(3)
    raise DeployError(f'{name}가 {START_SECONDS}초 안에 시작하지 않았습니다.')


def psql(sql):
    sh(['docker', 'exec', DB_CONTAINER, 'psql', '-U', DB_USER, '-d', 'postgres', '-v', 'ON_ERROR_STOP=1', '-c', sql])


def rehearse(config, jar, dump, stamp, tmp):
    """Start the new jar against a restored copy of the live dump; the Flyway upgrade happens there first."""
    clone, name = f'{site().db}_deploycheck_{stamp}', f'mdi-deploy-rehearsal-{stamp}'
    psql(f'CREATE DATABASE "{clone}" OWNER {DB_USER}')
    try:
        with dump.open('rb') as data:
            result = subprocess.run(['docker', 'exec', '-i', DB_CONTAINER, 'pg_restore', '-U', DB_USER, '-d', clone, '--no-owner'],
                                    stdin=data, capture_output=True, timeout=600)
        if result.returncode != 0:
            raise DeployError('백업 복원 시험 실패: ' + result.stderr.decode(errors='replace')[-400:])
        envfile = env_file(config['env'], tmp, f'jdbc:postgresql://{DB_CONTAINER}:5432/{clone}')
        try:
            run_app(name, config, jar, envfile, publish=False)
            wait_started(name)
        finally:
            subprocess.run(['docker', 'rm', '-f', name], capture_output=True)
    finally:
        subprocess.run(['docker', 'exec', DB_CONTAINER, 'psql', '-U', DB_USER, '-d', 'postgres', '-c',
                        f'DROP DATABASE IF EXISTS "{clone}" WITH (FORCE)'], capture_output=True)


def swap(config, jar, stamp, tmp):
    rollback = f'{site().api_container}-before-deploy-{stamp}'
    sh(['docker', 'stop', site().api_container], timeout=120)
    sh(['docker', 'rename', site().api_container, rollback])
    try:
        run_app(site().api_container, config, jar, env_file(config['env'], tmp))
        wait_started(site().api_container, site().api_url + '/')
    except Exception:
        subprocess.run(['docker', 'rm', '-f', site().api_container], capture_output=True)
        subprocess.run(['docker', 'rename', rollback, site().api_container], capture_output=True)
        subprocess.run(['docker', 'start', site().api_container], capture_output=True)
        raise
    return rollback


def flyway_versions():
    out = subprocess.run(['docker', 'exec', DB_CONTAINER, 'psql', '-U', DB_USER, '-d', site().db, '-Atc',
                          'select version from flyway_schema_history where success order by installed_rank'],
                         capture_output=True, text=True).stdout
    return [v for v in out.split() if v]


def deploy(project, state, label='queue', log=None):
    """Deploy project/backend if its sources differ from what is live. Returns a result record."""
    backend = Path(project) / 'backend'
    record_dir = Path(state) / 'deploys'
    record_dir.mkdir(parents=True, exist_ok=True)
    current = record_dir / 'current.json'
    digest = source_hash(backend)
    try:
        live = json.loads(current.read_text())
    except (OSError, ValueError):
        live = {}
    if live.get('source_sha') == digest:
        return {'success': True, 'skipped': True, 'detail': '백엔드 변경 없음', 'source_sha': digest}
    stamp = time.strftime('%Y%m%d%H%M%S')
    record = {'stamp': stamp, 'label': label, 'source_sha': digest, 'started_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
              'flyway_before': flyway_versions()}
    step = 'build'
    note = log or (lambda *_: None)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            note('build')
            jar = build_jar(backend, label, digest)
            record['jar'] = str(jar)
            step = 'backup'
            note('backup')
            record['backup'] = str(backup(stamp))
            config = live_config()
            step = 'rehearsal'
            note('rehearsal')
            rehearse(config, jar, Path(record['backup']), stamp, tmp)
            step = 'swap'
            note('swap')
            record['rollback_container'] = swap(config, jar, stamp, tmp)
        record.update(success=True, flyway_after=flyway_versions())
        current.write_text(json.dumps(record, ensure_ascii=False, indent=1))
    except Exception as error:  # report the failed step truthfully; the live app keeps the old container
        record.update(success=False, step=step, error=str(error)[-1200:])
    record['finished_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    (record_dir / f'{stamp}.json').write_text(json.dumps(record, ensure_ascii=False, indent=1))
    return record
