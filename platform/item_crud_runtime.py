"""Disposable real Spring/PostgreSQL runtime for trusted CRUD acceptance checks.

The source tree is mounted read-only, never copied. Build products live in an
owned Docker volume; the database and role are unique to this invocation.
Stdout is a JSON-lines protocol. Compiler/server diagnostics go to evidence.
"""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / 'local-only'
LABEL = 'local-workshop.item-crud-owner'
IMAGE = 'maven:3.9-eclipse-temurin-17'
QUERY_FIXTURE_ID = 'item-query-v1'
QUERY_FIXTURE = (
    {'itemCode': 'A-100', 'itemName': '육각 볼트', 'specification': 'M8x30', 'unit': 'EA', 'remark': '도금 볼트'},
    {'itemCode': 'B-200', 'itemName': '육각 너트', 'specification': 'M10', 'unit': 'BOX', 'remark': '스테인리스 너트'},
)


def command(args, *, input=None, timeout=15, check=True):
    result = subprocess.run(args, input=input, capture_output=True, text=True,
                            timeout=timeout)
    if check and result.returncode:
        raise RuntimeError((result.stderr or result.stdout or 'Command failed')[-6000:])
    return result


def sql_literal(value):
    return "'" + value.replace("'", "''") + "'"


class ItemRuntime:
    def __init__(self, output, token=None):
        self.output = Path(output).resolve()
        if self.output == APP or APP in self.output.parents:
            raise ValueError('Runtime evidence must be outside the model workspace')
        self.token = token or uuid.uuid4().hex
        if not re.fullmatch(r'[0-9a-f]{32}', self.token):
            raise ValueError('Invalid runtime ownership token')
        self.database = 'mdi_item_' + self.token
        self.role = self.database
        self.container = 'mdi-item-' + self.token
        self.volume = self.container + '-target'
        self.closed = False
        self.cleanup_report = None
        self.parent_pid = os.getppid()

    def state(self):
        return {'version': 1, 'token': self.token, 'database': self.database,
                'role': self.role, 'container': self.container,
                'target_volume': self.volume}

    def write(self, name, value):
        self.output.mkdir(parents=True, exist_ok=True)
        target = self.output / name
        temporary = target.with_suffix(target.suffix + '.tmp')
        temporary.write_text(value, encoding='utf-8')
        os.replace(temporary, target)

    def persist(self, name, value):
        self.write(name, json.dumps(value, ensure_ascii=False, indent=2))

    def psql(self, query, database='postgres', timeout=10):
        return command(['docker', 'exec', '-i', 'mdi-db', 'psql', '-X', '-qAt',
                        '-U', 'mdi', '-d', database, '-v', 'ON_ERROR_STOP=1'],
                       input=query, timeout=timeout).stdout.strip()

    def inspect(self, kind, name):
        result = command(['docker', kind, 'inspect', name], check=False)
        if result.returncode:
            if ('no such' in result.stderr.lower() or 'not found' in result.stderr.lower()):
                return None
            raise RuntimeError(result.stderr[-2000:])
        return json.loads(result.stdout)[0]

    def owned(self, kind, name):
        entry = self.inspect(kind, name)
        if entry is None:
            return None
        labels = entry.get('Config', {}).get('Labels', {}) if kind == 'container' else entry.get('Labels', {})
        if (labels or {}).get(LABEL) != self.token:
            raise RuntimeError('Refusing cleanup of an unowned ' + kind)
        return entry

    def start(self):
        if not (APP / 'backend/pom.xml').is_file():
            raise RuntimeError('Backend source is missing')
        auth = ROOT / 'platform/state/auth/server.env'
        if not auth.is_file():
            raise RuntimeError('Trusted local authentication environment is missing')
        # Publish all exact resource identities before the first side effect so
        # a supervisor can recover after an uncatchable process termination.
        self.persist('runtime.json', self.state())
        if self.inspect('container', self.container) or self.inspect('volume', self.volume):
            raise RuntimeError('Runtime Docker resource already exists')
        if self.psql("SELECT count(*) FROM pg_roles WHERE rolname=" + sql_literal(self.role) + ';') != '0':
            raise RuntimeError('Runtime role already exists')
        if self.psql("SELECT count(*) FROM pg_database WHERE datname=" + sql_literal(self.database) + ';') != '0':
            raise RuntimeError('Runtime database already exists')
        password = secrets.token_urlsafe(32)
        self.psql('BEGIN; CREATE ROLE ' + self.role + ' LOGIN PASSWORD ' + sql_literal(password)
                  + '; COMMENT ON ROLE ' + self.role + ' IS ' + sql_literal(self.token) + '; COMMIT;')
        self.psql('CREATE DATABASE ' + self.database + ' OWNER ' + self.role + ';')
        command(['docker', 'volume', 'create', '--label', LABEL + '=' + self.token, self.volume])
        build = ('mvn -q -B -o -Dmaven.test.skip=true package && '
                 'exec java -jar target/local-inventory-0.0.1-SNAPSHOT.jar')
        created = command(['docker', 'create', '--name', self.container,
            '--label', LABEL + '=' + self.token, '--network', 'mdi-internal',
            '--publish', '127.0.0.1::8080', '--memory', '1536m', '--cpus', '2',
            '--mount', 'type=bind,source=' + str(APP / 'backend') + ',target=/app,readonly',
            '--mount', 'type=volume,source=' + self.volume + ',target=/app/target',
            '--mount', 'type=volume,source=mdi-m2,target=/root/.m2',
            '--workdir', '/app', '--env-file', str(auth),
            '-e', 'DB_URL=jdbc:postgresql://mdi-db:5432/' + self.database,
            '-e', 'SPRING_DATASOURCE_USERNAME=' + self.role,
            '-e', 'SPRING_DATASOURCE_PASSWORD=' + password,
            '-e', 'SERVER_PORT=8080', IMAGE, 'sh', '-c', build])
        self.container_id = created.stdout.strip()
        command(['docker', 'network', 'connect', 'mdi-public', self.container])
        command(['docker', 'start', self.container])
        container = self.owned('container', self.container)
        bindings = container['NetworkSettings']['Ports']['8080/tcp']
        binding = next(item for item in bindings if item['HostIp'] == '127.0.0.1')
        self.base_url = 'http://127.0.0.1:' + binding['HostPort']
        self.persist('runtime.json', {**self.state(), 'container_id': self.container_id,
                                     'base_url': self.base_url})
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if os.getppid() != self.parent_pid:
                raise RuntimeError('Runtime parent exited during startup')
            status = self.owned('container', self.container)
            if not status or not status['State']['Running']:
                raise RuntimeError('Build or server startup failed: ' + self.logs()[-7000:])
            try:
                with urllib.request.urlopen(self.base_url + '/api/auth/session', timeout=2) as response:
                    session = json.load(response)
                seeded = (session.get('authenticated') is False
                          and session.get('csrf', {}).get('token')
                          and self.query('SELECT count(*) AS count FROM workspace_users')[0]['count'] > 0)
                if seeded:
                    return {'event': 'ready', 'base_url': self.base_url,
                            'db_name': self.database, 'container_id': self.container_id,
                            'state_file': str(self.output / 'runtime.json')}
            except (OSError, ValueError, urllib.error.URLError):
                pass
            time.sleep(0.5)
        raise RuntimeError('Isolated backend build/start exceeded 90 seconds: ' + self.logs()[-7000:])

    def query(self, query):
        if not isinstance(query, str) or len(query) > 16000:
            raise ValueError('Expected a bounded SELECT query')
        query = query.strip().rstrip(';').strip()
        if (not re.match(r'^SELECT\s', query, re.I) or ';' in query
                or '--' in query or '/*' in query):
            raise ValueError('Only one read-only SELECT statement is accepted')
        result = self.psql("BEGIN READ ONLY; SET LOCAL statement_timeout='5s'; "
                           "SELECT COALESCE(json_agg(row_to_json(evidence_row)), '[]'::json) "
                           'FROM (' + query + ') AS evidence_row; ROLLBACK;', self.database)
        return json.loads(result)

    def seed_query_fixture(self):
        """Explicit trusted fixture; never accept caller-supplied values or SQL."""
        expected = 'mdi_item_' + self.token
        if (self.closed or self.database != expected or self.role != expected
                or self.container != 'mdi-item-' + self.token):
            raise RuntimeError('Query fixture requires this runtime\'s owned database')
        container = self.owned('container', self.container)
        if not container or not container.get('State', {}).get('Running'):
            raise RuntimeError('Query fixture requires a running owned runtime')
        values = ', '.join('(' + ', '.join(sql_literal(row[key]) for key in
            ('itemCode', 'itemName', 'specification', 'unit', 'remark')) + ')' for row in QUERY_FIXTURE)
        # Identity/ownership, empty-table check, insert and evidence SELECT are
        # one transaction. Restrict writes to the runtime's unprivileged role.
        statement = f"""BEGIN;
SET LOCAL statement_timeout='5s';
SET LOCAL lock_timeout='2s';
DO $fixture_owner$ BEGIN
  IF current_database() <> {sql_literal(expected)}
     OR (SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database()) IS DISTINCT FROM {sql_literal(self.role)}
     OR (SELECT shobj_description(oid,'pg_authid') FROM pg_roles WHERE rolname={sql_literal(self.role)}) IS DISTINCT FROM {sql_literal(self.token)} THEN
    RAISE EXCEPTION 'Query fixture database ownership mismatch';
  END IF;
END; $fixture_owner$;
SET LOCAL ROLE {self.role};
LOCK TABLE public.items IN ACCESS EXCLUSIVE MODE;
DO $fixture_empty$ BEGIN
  IF (SELECT relkind FROM pg_class WHERE oid='public.items'::regclass) <> 'r'
     OR (SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid='public.items'::regclass) IS DISTINCT FROM {sql_literal(self.role)} THEN
    RAISE EXCEPTION 'Query fixture requires an owned ordinary items table';
  END IF;
  IF EXISTS (SELECT 1 FROM public.items) THEN
    RAISE EXCEPTION 'Query fixture requires an empty items table';
  END IF;
END; $fixture_empty$;
INSERT INTO public.items (item_code,item_name,specification,unit,remark) VALUES {values};
SELECT COALESCE(json_agg(row_to_json(fixture_row)), '[]'::json) FROM
  (SELECT id, item_code AS "itemCode", item_name AS "itemName", specification, unit, remark
   FROM public.items ORDER BY item_code) AS fixture_row;
COMMIT;"""
        rows = json.loads(self.psql(statement, self.database, timeout=10))
        if (not isinstance(rows, list) or len(rows) != 2
                or any(not isinstance(row, dict) or type(row.get('id')) is not int
                       or not 0 < row['id'] <= 9007199254740991 for row in rows)
                or len({row['id'] for row in rows}) != 2
                or [{key: value for key, value in row.items() if key != 'id'} for row in rows] != list(QUERY_FIXTURE)):
            raise RuntimeError('Stored query fixture differs from the fixed fixture contract')
        return rows

    def logs(self):
        if not self.owned('container', self.container):
            return ''
        result = command(['docker', 'logs', '--tail', '300', self.container], check=False)
        return result.stdout + result.stderr

    def close(self):
        if self.closed:
            return self.cleanup_report
        # Logs must never prevent teardown; record errors without secrets.
        log = ''
        errors = []
        try:
            log = self.logs()
        except Exception as error:
            errors.append('logs: ' + str(error))
        container_gone = False
        try:
            if self.owned('container', self.container):
                command(['docker', 'rm', '--force', self.container], timeout=15)
            container_gone = self.inspect('container', self.container) is None
        except Exception as error:
            errors.append('container: ' + str(error))
        database_gone = False
        role_gone = False
        if container_gone:
            try:
                role_stamp = self.psql("SELECT COALESCE(shobj_description(oid,'pg_authid'),'') FROM pg_roles WHERE rolname=" + sql_literal(self.role) + ';')
                db_owner = self.psql('SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=' + sql_literal(self.database) + ';')
                if db_owner:
                    if db_owner != self.role or role_stamp != self.token:
                        raise RuntimeError('Refusing cleanup of an unowned database')
                    self.psql('DROP DATABASE ' + self.database + ' WITH (FORCE);', timeout=15)
                database_gone = self.psql('SELECT count(*) FROM pg_database WHERE datname=' + sql_literal(self.database) + ';') == '0'
                if role_stamp:
                    if role_stamp != self.token:
                        raise RuntimeError('Refusing cleanup of an unowned role')
                    self.psql('DROP ROLE ' + self.role + ';')
                role_gone = self.psql('SELECT count(*) FROM pg_roles WHERE rolname=' + sql_literal(self.role) + ';') == '0'
            except Exception as error:
                errors.append('database: ' + str(error))
        volume_gone = False
        if container_gone:
            try:
                if self.owned('volume', self.volume):
                    command(['docker', 'volume', 'rm', self.volume])
                volume_gone = self.inspect('volume', self.volume) is None
            except Exception as error:
                errors.append('volume: ' + str(error))
        report = {'success': container_gone and database_gone and role_gone and volume_gone,
                  'container_removed': container_gone, 'database_removed': database_gone,
                  'role_removed': role_gone, 'target_volume_removed': volume_gone,
                  'errors': errors}
        self.cleanup_report = report
        self.closed = report['success']
        try:
            if log or not (self.output / 'backend.log').exists():
                self.write('backend.log', log)
            self.persist('cleanup.json', report)
        except OSError as error:
            report['evidence_error'] = str(error)
        return report


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--cleanup-state', type=Path)
    args = parser.parse_args()
    if args.cleanup_state:
        state = json.loads(args.cleanup_state.read_text())
        runtime = ItemRuntime(args.cleanup_state.parent, state['token'])
        if any(state.get(key) != value for key, value in runtime.state().items()):
            raise ValueError('Cleanup state identities are invalid')
        report = runtime.close()
        emit({'event': 'cleanup', **report})
        return 0 if report['success'] else 1
    if not args.output:
        parser.error('--output or --cleanup-state is required')
    runtime = ItemRuntime(args.output)
    def interrupted(signum, frame):
        raise RuntimeError('Runtime received termination signal')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    error = None
    closing_id = None
    try:
        emit(runtime.start())
        for line in sys.stdin:
            message = json.loads(line)
            identifier = message.get('id')
            if message.get('op') == 'close':
                closing_id = identifier
                break
            try:
                if message.get('op') == 'seed_query_fixture':
                    if set(message) - {'id', 'op'}:
                        raise ValueError('Query fixture accepts no values, table names, or SQL')
                    emit({'id': identifier, 'ok': True, 'fixture': QUERY_FIXTURE_ID,
                          'rows': runtime.seed_query_fixture()})
                    continue
                if message.get('op') != 'sql':
                    raise ValueError('Unknown runtime operation')
                emit({'id': identifier, 'ok': True, 'rows': runtime.query(message.get('query'))})
            except Exception as failure:
                emit({'id': identifier, 'ok': False, 'error': str(failure)})
    except BaseException as failure:
        error = str(failure)
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        cleanup = runtime.close()
        try:
            if error:
                emit({'event': 'error', 'error': error, 'cleanup': cleanup})
            elif closing_id is not None:
                emit({'id': closing_id, 'ok': cleanup['success'], 'cleanup': cleanup})
            else:
                emit({'event': 'closed', 'cleanup': cleanup})
        except BrokenPipeError:
            pass
    return 1 if error or not cleanup['success'] else 0


if __name__ == '__main__':
    sys.exit(main())
