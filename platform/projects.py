"""Making a new project: a folder with the base framework in it and a working set of its own.

A project is of a kind (업무 사이트 ...). The kind decides which template it starts from; the template is the
base framework exactly as the reference project holds it, without that project's own screens. The new project gets
its own git history, development database, server, preview address, sign-in files and - later - setup packs, all
named after it. Nothing of another project is shared with it except the tools (database container, build cache).
"""
import hashlib
import io
import shutil
import socket
import subprocess
import tarfile
from pathlib import Path

import project_git as vcs
import sites
from first_setup import Setup

HOME = sites.ROOT / 'projects'          # where new projects are made (ignored by the platform's own git)
LEFT_OUT = ('release/',)                # the reference project's own screens do not belong to the base framework


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


def _template(source, target):
    """The committed files of the reference project, without its own screens."""
    raw = subprocess.run(['git', 'archive', '--format=tar', 'HEAD'], cwd=source, capture_output=True, timeout=300)
    if raw.returncode != 0:
        raise ValueError('기본 프레임워크를 꺼내지 못했습니다: ' + raw.stderr.decode(errors='replace')[-300:])
    with tarfile.open(fileobj=io.BytesIO(raw.stdout)) as archive:
        members = [member for member in archive.getmembers() if not member.name.startswith(LEFT_OUT) and member.name + '/' not in LEFT_OUT]
        archive.extractall(target, members=members)
    return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=source, capture_output=True, text=True).stdout.strip()


def create(hub, body, log=None):
    """Make the project and everything it needs to be worked on. Returns its record (already registered)."""
    note = log or (lambda *_: None)
    title, slug, kind_id = str(body.get('title') or '').strip(), str(body.get('slug') or '').strip().lower(), body.get('kind') or 'business'
    kind = next((item for item in sites.KINDS if item['id'] == kind_id), None)
    if not kind or not kind.get('enabled'):
        raise ValueError('아직 만들 수 없는 종류입니다. 지금은 업무 사이트만 만들 수 있습니다.')
    if not title or len(title) > 40 or any(ord(char) < 32 for char in title):
        raise ValueError('프로젝트 이름을 1~40자로 적으세요.')
    if not sites.SLUG.fullmatch(slug):
        raise ValueError('영문 이름은 영문 소문자로 시작하는 3~25자의 소문자·숫자·하이픈입니다 (예: acme-erp). 폴더, 데이터베이스, 셋업 팩 이름에 쓰입니다.')
    root, database = HOME / slug, 'mdi_' + slug.replace('-', '_')
    with hub.lock:
        if slug == sites.DEFAULT.slug or any((record.get('site') or {}).get('slug') == slug or Path(record['root']).name == slug for record in hub.records):
            raise ValueError(f'{slug} 은(는) 이미 있는 프로젝트 이름입니다.')
        owned = [record.get('site') or {} for record in hub.records]
        taken = {sites.DEFAULT.api_port, sites.DEFAULT.ops_port, 5292, 5293, 5390} | {int(own[key]) for own in owned for key in ('api_port', 'preview_port', 'ops_port') if own.get(key)}
    if root.exists():
        raise ValueError(f'{root} 폴더가 이미 있습니다.')
    source = sites.ROOT / kind['template']
    api_port = _free(8084, taken)
    preview_port = _free(5310, taken | {api_port})
    ops_port = _free(5301, taken | {api_port, preview_port})
    try:
        note('기본 프레임워크 복사')
        root.mkdir(parents=True)
        commit = _template(source, root)
        (root / 'harness').symlink_to(sites.ROOT / 'erp-harness')
        vcs.ensure_repo(root)
        default = hub.records[0]
        own = {'slug': slug, 'title': title, 'kind': kind_id, 'db': database, 'api_container': f'mdi-{slug}-api', 'api_port': api_port, 'preview_port': preview_port, 'ops_port': ops_port,
               'template': kind['template'], 'template_commit': commit}
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
    are kept (they may be installed somewhere). The first project cannot be removed, and the project's English name must be
    given again as confirmation - this cannot be undone."""
    with hub.lock:
        record = next((item for item in hub.records if item['id'] == project_id), None)
        if record is None:
            raise ValueError('등록된 프로젝트가 아닙니다.')
        own = record.get('site')
        if not own or record is hub.records[0]:
            raise ValueError('이 프로젝트는 플랫폼에서 지울 수 없습니다 (처음부터 있던 프로젝트이거나, 플랫폼이 만든 프로젝트가 아닙니다).')
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
