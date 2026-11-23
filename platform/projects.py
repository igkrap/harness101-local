"""Making a new project: a folder with the base framework in it and a working set of its own.

A project is of a kind (업무 사이트 ...). It starts from the platform's framework (platform/base, see framework_update) -
no project is the template of another. The new project gets
its own git history, development database, server, preview address, sign-in files and - later - setup packs, all
named after it. Nothing of another project is shared with it except the tools (database container, build cache).
"""
import hashlib
import shutil
import socket
import subprocess
from pathlib import Path

import project_git as vcs
import sites
from first_setup import Setup

HOME = sites.ROOT / 'projects'          # where new projects are made (ignored by the platform's own git)


def kinds():
    return [{key: kind[key] for key in ('id', 'label', 'description', 'enabled')} for kind in sites.KINDS]


def _free(start, taken):
    port = start
    while True:
        if port not in taken:
            with socket.socket() as probe:
                try:
                    probe.bind(('127.0.0.1', port))
                    return port
                except OSError:
                    pass
        port += 1


PORT_STARTS = {'api': 8084, 'preview': 5310}
PORT_KEYS = {'api': 'api_port', 'preview': 'preview_port'}


def _bindable(port):
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', port))
            return True
        except OSError:
            return False


def taken_ports(hub, but=None):
    """Ports the platform and its projects hold (one project left out: the one being changed)."""
    with hub.lock:
        owned = [record.get('site') or {} for record in hub.records if record.get('id') != but]
    return {5293, 5390, 8099, 5433} | {int(own[key]) for own in owned for key in PORT_KEYS.values() if own.get(key)}


def free_ports(hub, count=8, but=None):
    """For each service of a project (api: the app's server, preview: its screens) the first ports nobody holds."""
    taken, out = taken_ports(hub, but), {}
    for kind, start in PORT_STARTS.items():
        found, port = [], start
        while len(found) < count and port < start + 400:
            if port not in taken and _bindable(port):
                found.append(port)
            port += 1
        out[kind] = found
    return out


def chosen_ports(hub, body, but=None):
    """The ports asked for (body api_port / preview_port), each checked to be free; the first free one where none is asked."""
    taken, out = taken_ports(hub, but), {}
    for kind, key in PORT_KEYS.items():
        asked = body.get(key)
        if asked in (None, ''):
            port = _free(PORT_STARTS[kind], taken)
        else:
            try:
                port = int(asked)
            except (TypeError, ValueError):
                raise ValueError(f'{key} 는 숫자 포트입니다: {asked}')
            if not 1024 < port < 65536:
                raise ValueError(f'포트 {port} 은(는) 쓸 수 없습니다 (1025~65535).')
            if port in taken or port in out.values() or not _bindable(port):
                raise ValueError(f'포트 {port} 은(는) 다른 곳에서 쓰고 있습니다. 빈 포트 목록에서 고르세요.')
        out[key] = port
        taken = taken | {port}
    return out


def create(hub, body, log=None):
    """Make the project and everything it needs to be worked on. Returns its record (already registered)."""
    note = log or (lambda *_: None)
    title, slug, kind_id = str(body.get('title') or '').strip(), str(body.get('slug') or '').strip().lower(), body.get('kind') or 'business'
    import environment
    problem = environment.ready()
    if problem:
        raise RuntimeError('프로젝트를 만들 수 없습니다: ' + problem)
    kind = next((item for item in sites.KINDS if item['id'] == kind_id), None)
    if not kind or not kind.get('enabled'):
        raise ValueError('아직 만들 수 없는 종류입니다. 지금은 업무 사이트만 만들 수 있습니다.')
    if not title or len(title) > 40 or any(ord(char) < 32 for char in title):
        raise ValueError('프로젝트 이름을 1~40자로 적으세요.')
    if not sites.SLUG.fullmatch(slug):
        raise ValueError('영문 이름은 영문 소문자로 시작하는 3~25자의 소문자·숫자·하이픈입니다 (예: acme-erp). 폴더, 데이터베이스, 셋업 팩 이름에 쓰입니다.')
    root, database = HOME / slug, 'mdi_' + slug.replace('-', '_')
    with hub.lock:
        if any((record.get('site') or {}).get('slug') == slug or Path(record['root']).name == slug for record in hub.records) or (sites.ROOT / slug).exists():
            raise ValueError(f'{slug} 은(는) 이미 있는 프로젝트 이름입니다.')
    if root.exists():
        raise ValueError(f'{root} 폴더가 이미 있습니다.')
    ports = chosen_ports(hub, body)              # as asked, or the first free ones
    api_port, preview_port = ports['api_port'], ports['preview_port']
    try:
        note('플랫폼의 프레임워크 넣기')
        root.mkdir(parents=True)
        import framework_update
        commit = framework_update.copy_into(root)        # the platform's framework, not any project's copy
        (root / 'harness').symlink_to(sites.ROOT / 'erp-harness')
        vcs.ensure_repo(root)
        default = hub.records[0] if hub.records else {}          # model settings as the projects so far have them
        own = {'slug': slug, 'title': title, 'kind': kind_id, 'db': database, 'api_container': f'mdi-{slug}-api', 'api_port': api_port, 'preview_port': preview_port,
               'framework': commit}
        record = {'id': hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:16], 'name': slug, 'root': str(root.resolve()), 'preview_url': f'http://127.0.0.1:{preview_port}',
                  'model_url': default.get('model_url', 'http://127.0.0.1:8099/v1'), 'default_model': default.get('default_model', ''), 'test_db_url': f'jdbc:postgresql://{sites.DB_CONTAINER}:5432/{database}_test',
                  **({'model_config': default['model_config']} if default.get('model_config') else {}), 'site': own}
        state = hub.state / 'projects' / record['id'] / 'runs'
        setup = Setup(sites.ROOT, api_port=api_port, state=state, log=note, project=root, database=database, api=own['api_container'], slug=slug)
        setup.run()
        # The system's name on its own screens is the project's name from the start.
        setup.psql("INSERT INTO sys_settings (setting_key, setting_value) VALUES ('system_name', '" + title.replace("'", "''") + "') "
                   "ON CONFLICT (setting_key) DO UPDATE SET setting_value = EXCLUDED.setting_value", database)
        note('화면 도구 준비')
        installed = subprocess.run(['npm', 'ci', '--prefer-offline', '--no-audit', '--no-fund'], cwd=root / 'frontend', capture_output=True, text=True, timeout=900)
        if installed.returncode != 0:
            raise ValueError('화면 도구를 설치하지 못했습니다: ' + installed.stderr[-300:])
        # The starting state is the project's first record: its codes, menus and settings are in git from the beginning.
        import release
        with sites.use(sites.of(record, state)):
            release.record(root, '프로젝트 시작 상태')
    except Exception:
        # Nothing half made stays: the folder, the server and the databases of a project that was never registered are taken away again.
        subprocess.run(['docker', 'rm', '-f', f'mdi-{slug}-api'], capture_output=True)
        for name in (database, database + '_test'):
            subprocess.run(['docker', 'exec', sites.DB_CONTAINER, 'psql', '-U', sites.DB_USER, '-d', 'postgres', '-c', f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'], capture_output=True)
        shutil.rmtree(root, ignore_errors=True)
        raise
    with hub.lock:
        hub.records.append(record)
        hub.persist()
    hub.previews.ensure(record)
    return record


def remove(hub, project_id, confirm):
    """Take a project away for good: its folder, development database, server and run records. Its setup packs already made
    are kept (they may be installed somewhere). The project's English name must be
    given again as confirmation - this cannot be undone."""
    with hub.lock:
        record = next((item for item in hub.records if item['id'] == project_id), None)
        if record is None:
            raise ValueError('등록된 프로젝트가 아닙니다.')
        own = record.get('site')
        if not own:
            raise ValueError('이 프로젝트는 플랫폼에서 지울 수 없습니다 (플랫폼이 이름을 모르는 예전 기록입니다).')
        if confirm != own['slug']:
            raise ValueError(f"지우려면 프로젝트의 영문 이름({own['slug']})을 그대로 적어 확인해 주세요.")
        app = hub.apps.get(project_id)
        if app is not None and (any(process.poll() is None for process in app.processes.values()) or (getattr(app, 'queues', None) and app.queues.active())):
            raise RuntimeError('이 프로젝트에서 진행 중인 작업이 있습니다. 끝난 뒤 지우세요.')
        hub.records.remove(record)
        hub.persist()
        hub.apps.pop(project_id, None)
        item = hub.previews.items.pop(project_id, None)
    process = (item or {}).get('process')
    if process is not None and process.poll() is None:
        import os, signal
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    slug, root = own['slug'], Path(record['root'])
    subprocess.run(['docker', 'rm', '-f', own['api_container']], capture_output=True)
    from backend_deploy import prune_rollbacks
    prune_rollbacks(keep=0, container=own['api_container'])        # the copies its deploys kept for going back go with it
    for name in (own['db'], own['db'] + '_test'):
        subprocess.run(['docker', 'exec', sites.DB_CONTAINER, 'psql', '-U', sites.DB_USER, '-d', 'postgres', '-c', f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'], capture_output=True)
    copy = sites.SHARE / 'prod' / slug / 'copy'
    if (copy / 'docker-compose.yml').is_file():        # this machine's own operating copy of it, if one was installed
        subprocess.run(['docker', 'compose', 'down', '-v', '--remove-orphans'], cwd=copy, capture_output=True)
    if root.is_dir() and root.resolve().is_relative_to(HOME.resolve()):
        shutil.rmtree(root, ignore_errors=True)
    for folder in (hub.state / 'projects' / project_id, sites.SHARE / 'artifacts' / slug, sites.SHARE / 'backups' / slug, sites.SHARE / 'prod' / slug):
        shutil.rmtree(folder, ignore_errors=True)
    return {'removed': slug, 'packs_kept': str(sites.SHARE / 'packs' / slug) if (sites.SHARE / 'packs' / slug).is_dir() else None}


def _git(root, *args):
    done = subprocess.run(['git', *args], cwd=root, capture_output=True, text=True, timeout=30)
    return done.stdout.strip() if done.returncode == 0 else ''


def environment(hub, project_id):
    """One project's development environment as it stands: its ports, database and server, whether its servers run, its screen packages,
    and where its records (git) stand."""
    import environment as computer
    with hub.lock:
        record = next((item for item in hub.records if item['id'] == project_id), None)
    if record is None:
        raise ValueError('등록된 프로젝트가 아닙니다.')
    own = record.get('site') or {}
    root = Path(record['root'])
    api_running = subprocess.run(['docker', 'inspect', '-f', '{{.State.Running}}', own.get('api_container', '')], capture_output=True, text=True).stdout.strip() == 'true'
    preview_running = bool(own.get('preview_port')) and not _bindable(int(own['preview_port']))
    return {'id': record['id'], 'title': own.get('title') or record.get('title') or record['name'], 'root': str(root),
            'ports': {key: own.get(key) for key in PORT_KEYS.values()}, 'db': own.get('db'), 'api_container': own.get('api_container'),
            'running': {'api': api_running, 'preview': preview_running}, 'items': computer.project(record),
            'git': {'branch': _git(root, 'rev-parse', '--abbrev-ref', 'HEAD'), 'last': _git(root, 'log', '-1', '--format=%h %ad %s', '--date=format:%m-%d %H:%M'),
                    'unrecorded': len([line for line in _git(root, 'status', '--porcelain').splitlines() if line.strip()])},
            'free': free_ports(hub, but=project_id), 'backups': _backups(record, hub), 'remote': _git(root, 'remote', 'get-url', 'origin'),
            'framework': _framework(hub, record)}


def _record(hub, project_id):
    with hub.lock:
        record = next((item for item in hub.records if item['id'] == project_id), None)
    if record is None or not record.get('site'):
        raise ValueError('등록된 프로젝트가 아닙니다.')
    return record


def _site(hub, record):
    return sites.of(record, hub.resolve(record['id']).state)


def _framework(hub, record):
    import framework_update
    return next((item for item in framework_update.status(hub)['projects'] if item['id'] == record['id']), None)


def _backups(record, hub):
    """The copies of the project's development database: made before each server rebuild, and by hand."""
    folder = _site(hub, record).backups
    files = sorted(folder.glob('*.dump'), key=lambda path: path.stat().st_mtime, reverse=True) if folder.is_dir() else []
    import time as _time
    return [{'name': path.name, 'size': path.stat().st_size, 'at': _time.strftime('%Y/%m/%d %H:%M:%S', _time.localtime(path.stat().st_mtime)),
             'by_hand': '-by-hand-' in path.name} for path in files[:30]]


def server_control(hub, project_id, part, action):
    """Start again or stop a project's app server (its container) or its screens (the preview)."""
    record = _record(hub, project_id)
    own = record['site']
    if part == 'api' and action in ('restart', 'stop', 'start'):
        done = subprocess.run(['docker', action, own['api_container']], capture_output=True, text=True, timeout=180)
        if done.returncode != 0:
            raise RuntimeError(f'서버를 {"다시 띄우지" if action == "restart" else "끄지" if action == "stop" else "켜지"} 못했습니다: ' + done.stderr.strip()[-300:])
    elif part == 'preview' and action in ('restart', 'stop', 'start'):
        item = hub.previews.items.pop(project_id, None)
        if item and item.get('process') and item['process'].poll() is None:
            item['process'].terminate()
            try:
                item['process'].wait(10)
            except subprocess.TimeoutExpired:
                item['process'].kill()
        if action != 'stop':
            hub.previews.ensure(record)
    else:
        raise ValueError('알 수 없는 조작입니다.')
    return environment(hub, project_id)


def backup_now(hub, project_id):
    record = _record(hub, project_id)
    site = _site(hub, record)
    import time as _time
    site.backups.mkdir(parents=True, exist_ok=True)
    path = site.backups / f"{site.db}-by-hand-{_time.strftime('%Y%m%d%H%M%S')}.dump"
    with path.open('wb') as out:
        done = subprocess.run(['docker', 'exec', sites.DB_CONTAINER, 'pg_dump', '-U', sites.DB_USER, '-Fc', site.db], stdout=out, stderr=subprocess.PIPE, timeout=900)
    if done.returncode != 0 or path.stat().st_size == 0:
        path.unlink(missing_ok=True)
        raise RuntimeError('백업하지 못했습니다: ' + done.stderr.decode(errors='replace')[-300:])
    return {**environment(hub, project_id), 'said': f'백업했습니다: {path.name}'}


def restore(hub, project_id, name, confirm):
    """Put the development database back to one of its copies (what was entered since is gone). The server is stopped meanwhile."""
    record = _record(hub, project_id)
    site, own = _site(hub, record), record['site']
    path = site.backups / str(name or '')
    if not name or '/' in name or not path.is_file():
        raise ValueError('그런 백업이 없습니다.')
    if confirm != own['slug']:
        raise ValueError(f"되돌리려면 프로젝트의 영문 이름({own['slug']})을 그대로 적어 확인해 주세요.")
    hub.resolve(project_id).require_idle('DB 되돌리기')
    subprocess.run(['docker', 'stop', own['api_container']], capture_output=True, timeout=180)
    try:
        with path.open('rb') as source:
            done = subprocess.run(['docker', 'exec', '-i', sites.DB_CONTAINER, 'pg_restore', '-U', sites.DB_USER, '-d', site.db, '--clean', '--if-exists', '--no-owner'],
                                  stdin=source, capture_output=True, timeout=1800)
    finally:
        subprocess.run(['docker', 'start', own['api_container']], capture_output=True, timeout=180)
    if done.returncode != 0 and b'error' in done.stderr.lower():
        raise RuntimeError('되돌리는 중 문제가 있었습니다: ' + done.stderr.decode(errors='replace')[-400:])
    return {**environment(hub, project_id), 'said': f'개발 DB를 {name} 로 되돌렸습니다.'}


def change_ports(hub, project_id, body, log=None):
    """Move a project's services to other free ports: its server is started again on the new one, its preview opens there next time."""
    note = log or (lambda *_: None)
    with hub.lock:
        record = next((item for item in hub.records if item['id'] == project_id), None)
        if record is None or not record.get('site'):
            raise ValueError('포트를 바꿀 수 있는 프로젝트가 아닙니다.')
        app = hub.apps.get(project_id)
        if app is not None and (any(process.poll() is None for process in app.processes.values()) or (getattr(app, 'queues', None) and app.queues.active())):
            raise RuntimeError('이 프로젝트에서 진행 중인 작업이 있습니다. 끝난 뒤 바꾸세요.')
    own = record['site']
    asked = {key: body.get(key) if body.get(key) not in (None, '') else own.get(key) for key in PORT_KEYS.values()}
    unchanged = {key: value for key, value in asked.items() if str(value) == str(own.get(key))}
    ports = chosen_ports(hub, {key: (None if key in unchanged else value) for key, value in asked.items()}, but=project_id)
    ports.update({key: int(value) for key, value in unchanged.items()})       # (its own current ports are free for it)
    if all(int(ports[key]) == int(own.get(key) or 0) for key in PORT_KEYS.values()):
        return environment(hub, project_id)
    root = Path(record['root'])
    import os, signal
    item = hub.previews.items.pop(project_id, None)
    process = (item or {}).get('process')
    if process is not None and process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    api_moved = int(ports['api_port']) != int(own['api_port'])
    with hub.lock:
        own.update({key: int(value) for key, value in ports.items()})
        record['preview_url'] = f"http://127.0.0.1:{own['preview_port']}"
        hub.persist()
    if api_moved:
        note('서버를 새 포트로 다시 띄움')
        subprocess.run(['docker', 'rm', '-f', own['api_container']], capture_output=True)
        state = hub.state / 'projects' / record['id'] / 'runs'
        Setup(sites.ROOT, api_port=own['api_port'], state=state, log=note, project=root, database=own['db'], api=own['api_container'], slug=own['slug']).run()
    return environment(hub, project_id)


def rename(hub, project_id, title=None, slug=None, allow_queue=False):
    """Give a project another name. title: the name people see (on the platform, on the project's own screens when it still
    carried the old one, on the setup packs made from now on). slug: the English name - the folder, the development
    database, the server and the pack files are renamed with it; only for projects made here, and only while nothing runs in them.
    Returns the project's record (its id changes with the English name)."""
    title = None if title is None else str(title).strip()
    slug = None if slug is None else str(slug).strip().lower()
    with hub.lock:
        record = next((item for item in hub.records if item['id'] == project_id), None)
        if record is None:
            raise ValueError('등록된 프로젝트가 아닙니다.')
        own = record.get('site')
        if title is not None and (not title or len(title) > 40 or any(ord(char) < 32 for char in title)):
            raise ValueError('프로젝트 이름을 1~40자로 적으세요.')
        if slug is not None and own and slug == own['slug']:
            slug = None
        if slug is not None:
            if not own:
                raise ValueError('이 프로젝트는 영문 이름을 바꿀 수 없습니다.')
            if not sites.SLUG.fullmatch(slug):
                raise ValueError('영문 이름은 영문 소문자로 시작하는 3~25자의 소문자·숫자·하이픈입니다 (예: acme-erp).')
            if any((item.get('site') or {}).get('slug') == slug or Path(item['root']).name == slug for item in hub.records) or (HOME / slug).exists() or (sites.ROOT / slug).exists():
                raise ValueError(f'{slug} 은(는) 이미 있는 프로젝트 이름입니다.')
            app = hub.apps.get(project_id)
            # (a rename asked for in the request box is itself the piece of work in the queue)
            if app is not None and (any(process.poll() is None for process in app.processes.values()) or (getattr(app, 'queues', None) and app.queues.active() and not allow_queue)):
                raise RuntimeError('이 프로젝트에서 진행 중인 작업이 있습니다. 끝난 뒤 바꾸세요.')
    old_title = (own or {}).get('title') or record.get('title') or record['name']
    if title is not None and title != old_title:
        database = own['db'] if own else sites.default().db
        # The project's own screens say its name too: they follow when they still carried the old one (a name set there on purpose stays).
        subprocess.run(['docker', 'exec', '-i', sites.DB_CONTAINER, 'psql', '-U', sites.DB_USER, '-d', database, '-q'], capture_output=True, text=True, timeout=60,
                       input="UPDATE sys_settings SET setting_value = '" + title.replace("'", "''") + "' WHERE setting_key = 'system_name' AND setting_value = '" + old_title.replace("'", "''") + "';")
        with hub.lock:
            if own:
                own['title'] = title
            else:
                record['title'] = title
            hub.persist()
    if slug is None:
        return record

    old, root, database = own['slug'], Path(record['root']), own['db']
    # A project is renamed where it is (its folder keeps its place); its runs follow it under the platform's state.
    new_root, new_database, new_api = root.parent / slug, 'mdi_' + slug.replace('-', '_'), f'mdi-{slug}-api'
    state = hub.state / 'projects' / record['id'] / 'runs'
    item = hub.previews.items.pop(project_id, None)
    process = (item or {}).get('process')
    import os, signal
    if process is not None and process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    # A preview started some other way (by hand, by a start script) is serving from the folder that is about to move: it goes too.
    listening = subprocess.run(['lsof', '-nP', f"-iTCP:{own['preview_port']}", '-sTCP:LISTEN', '-t'], capture_output=True, text=True).stdout.split()
    for pid in listening:
        where = subprocess.run(['lsof', '-a', '-p', pid, '-d', 'cwd', '-Fn'], capture_output=True, text=True).stdout
        if str(root.resolve()) in where:
            try:
                os.kill(int(pid), signal.SIGTERM)
            except (ProcessLookupError, ValueError):
                pass
    subprocess.run(['docker', 'rm', '-f', own['api_container']], capture_output=True)

    def sql(text):
        done = subprocess.run(['docker', 'exec', '-i', sites.DB_CONTAINER, 'psql', '-U', sites.DB_USER, '-d', 'postgres', '-v', 'ON_ERROR_STOP=1', '-q'], input=text, capture_output=True, text=True, timeout=120)
        if done.returncode != 0:
            raise RuntimeError('데이터베이스 이름을 바꾸지 못했습니다: ' + done.stderr[-300:])
    moved = []        # what was done, to be taken back in reverse if a later step fails
    try:
        for was, now in ((database, new_database), (database + '_test', new_database + '_test')):
            sql(f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{was}'; ALTER DATABASE \"{was}\" RENAME TO \"{now}\";")
            moved.append(lambda was=was, now=now: sql(f'ALTER DATABASE "{now}" RENAME TO "{was}";'))
        root.rename(new_root)
        moved.append(lambda: new_root.rename(root))
        if new_root.parent == sites.ROOT:
            ignore = sites.ROOT / '.gitignore'        # a project beside the platform stays out of the platform's own git (each keeps its own history)
            if ignore.is_file():        # the folder's line follows the name (the old name's line is not left behind)
                lines = [line for line in ignore.read_text(encoding='utf-8').splitlines() if line.strip() not in (f'{old}/', f'{slug}/')]
                ignore.write_text('\n'.join(lines).rstrip('\n') + f'\n{slug}/\n', encoding='utf-8')
        new_id = hashlib.sha256(str(new_root.resolve()).encode()).hexdigest()[:16]
        new_state = hub.state / 'projects' / new_id
        (hub.state / 'projects' / record['id']).rename(new_state)
        moved.append(lambda: new_state.rename(hub.state / 'projects' / record['id']))
        for part in ('artifacts', 'backups', 'prod', 'packs'):
            source = sites.SHARE / part / old
            if source.is_dir() and not (sites.SHARE / part / slug).exists():
                source.rename(sites.SHARE / part / slug)
                moved.append(lambda part=part: (sites.SHARE / part / slug).rename(sites.SHARE / part / old))
    except Exception:
        for back in reversed(moved):
            try:
                back()
            except Exception:
                pass
        # the server is started again under its old name, so the project is as it was
        Setup(sites.ROOT, api_port=own['api_port'], state=state, project=root, database=database, api=own['api_container'], slug=old).run()
        raise
    with hub.lock:
        hub.apps.pop(project_id, None)
        own.update(slug=slug, db=new_database, api_container=new_api)
        record.update(id=new_id, name=slug, root=str(new_root.resolve()), test_db_url=f'jdbc:postgresql://{sites.DB_CONTAINER}:5432/{new_database}_test')
        hub.persist()
    Setup(sites.ROOT, api_port=own['api_port'], state=new_state / 'runs', project=new_root, database=new_database, api=new_api, slug=slug).run()
    hub.previews.ensure(record)
    return record
