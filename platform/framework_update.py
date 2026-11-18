"""The framework belongs to the platform: one copy of the app's base (platform/base - the backend and screens every project
runs on, with the framework's parts, its description for the model and its migrations), used by every project alike. A project
owns only what was made in it (release/ - its screen definitions, menus, codes, flows - and principles.md).

When the platform's copy changes (the platform was updated), every project is brought to it together: the files are put in,
the server is rebuilt when the backend changed (built and tried on a copy of the database first - a failed build leaves the
running server as it was), the screens are type-checked, and the project's own flows are run end to end. A project whose new
build fails is put back to the files it had; one whose flows break keeps the new framework and says what broke. A project busy
with a request waits and is brought up when it is free. Nothing here is chosen per project: there are no modules to pick and
no versions to hold back.
"""
import hashlib
import json
import subprocess
import threading
import time
from pathlib import Path

import sites

BASE = sites.ROOT / 'platform/base'
OWN = ('release/', 'principles.md')


def _base_files():
    return sorted(str(path.relative_to(BASE)) for path in BASE.rglob('*') if path.is_file() and path.name != '.DS_Store')


_cache = {'stamp': None, 'version': None}


def version():
    """The platform's framework as a short name: the same files give the same name."""
    files = _base_files()
    stamp = (len(files), max((BASE / name).stat().st_mtime_ns for name in files) if files else 0)
    if _cache['stamp'] != stamp:
        digest = hashlib.sha256()
        for name in files:
            digest.update(name.encode() + b'\0' + (BASE / name).read_bytes() + b'\0')
        _cache.update(stamp=stamp, version=digest.hexdigest()[:10])
    return _cache['version']


def _tracked(root):
    done = subprocess.run(['git', 'ls-files', '-z'], cwd=root, capture_output=True, text=True, timeout=60)
    return [name for name in done.stdout.split('\0') if name and not name.startswith(OWN) and name not in OWN]


def plan(root):
    """What bringing the project to the platform's framework changes: files to write, files to take away."""
    root = Path(root)
    write = [name for name in _base_files() if not (root / name).is_file() or (root / name).read_bytes() != (BASE / name).read_bytes()]
    base = set(_base_files())
    drop = [name for name in _tracked(root) if name not in base and (root / name).exists()]
    return write, drop


def copy_into(root):
    """A new project's files: the platform's framework as it is (the project's own parts start empty)."""
    root = Path(root)
    for name in _base_files():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes((BASE / name).read_bytes())
    return version()


def _state(app):
    return Path(app.state) / 'framework.json'


def _read(app):
    try:
        return json.loads(_state(app).read_text())
    except (OSError, ValueError):
        return {}


def _write(app, **values):
    _state(app).parent.mkdir(parents=True, exist_ok=True)
    _state(app).write_text(json.dumps(dict(values, at=time.strftime('%Y/%m/%d %H:%M:%S')), ensure_ascii=False, indent=1))


def _busy(app):
    try:
        app.require_idle('프레임워크 업데이트')
        return False
    except RuntimeError:
        return True


def _checks(root, frontend_changed, note):
    """The screens type-check, the definitions still read, and the project's own flows run end to end."""
    problems = []
    if frontend_changed and (Path(root) / 'frontend/node_modules').is_dir():
        note('화면 타입 검사')
        done = subprocess.run(['npx', 'tsc', '--noEmit'], cwd=Path(root) / 'frontend', capture_output=True, text=True, timeout=600)
        if done.returncode != 0:
            problems.append('화면 타입 검사 실패: ' + (done.stdout + done.stderr).strip()[-600:])
    import devtools
    devtools._harness()
    import flows
    from framework import Framework
    note('화면 정의 읽기, 업무 흐름 시험')
    try:
        framework = Framework()
        screens = [screen['key'] for screen in framework.ok('GET', '/api/meta/process')['screens']]
        passed, _, lines = flows.judge(screens, framework)
        if not passed:
            problems += lines
    except Exception as error:
        problems.append(f'화면 정의를 읽지 못했습니다: {str(error)[:300]}')
    return problems


def apply(hub, record, log=None):
    """Bring one project to the platform's framework. Returns what happened, in words."""
    note = log or (lambda *_: None)
    app = hub.resolve(record['id'])
    now = version()
    if (_read(app).get('version') == now and _read(app).get('state') in ('ok', 'broken')) or (_read(app).get('state') == 'held' and _read(app).get('tried') == now):
        return _read(app)        # done, or tried and put back: tried again when the platform's framework changes again
    if not Path(record['root']).is_dir():
        return {'state': 'missing'}
    if _busy(app):
        _write(app, **{**_read(app), 'state': 'waiting', 'waiting_for': now, 'said': '요청을 처리하는 중이라 끝나면 맞춥니다.'})
        return _read(app)
    import release
    import project_git
    from backend_deploy import deploy
    root = Path(record['root'])
    with sites.use(sites.of(record, app.state)), release.exclusive('프레임워크 업데이트'):
        write, drop = plan(root)
        if not write and not drop:
            _write(app, version=now, state='ok', said='이미 최신 프레임워크입니다.')
            return _read(app)
        before = {name: (root / name).read_bytes() for name in write + drop if (root / name).is_file()}
        for name in write:
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_bytes((BASE / name).read_bytes())
        for name in drop:
            (root / name).unlink()
        changed = write + drop
        if any(name.startswith('backend/') for name in changed):
            note('서버 다시 만들기')
            done = deploy(root, app.state, 'framework', note)
            if not done.get('success'):
                for name in write:
                    if name in before:
                        (root / name).write_bytes(before[name])
                    else:
                        (root / name).unlink()
                for name in drop:
                    (root / name).parent.mkdir(parents=True, exist_ok=True)
                    (root / name).write_bytes(before[name])
                said = f"새 프레임워크로 서버를 만들지 못해 원래대로 두었습니다 ({done.get('step')}): {str(done.get('error', ''))[-400:]}"
                _write(app, version=_read(app).get('version'), state='held', tried=now, said=said)
                return _read(app)
        problems = _checks(root, any(name.startswith('frontend/') for name in changed), note)
        project_git.commit(root, f'프레임워크 업데이트 {now} (플랫폼)', only=changed)
        if problems:
            _write(app, version=now, state='broken', said='새 프레임워크로 바꿨는데 점검에서 문제가 나왔습니다.', problems=problems[:20], files=len(changed))
        else:
            _write(app, version=now, state='ok', said=f'새 프레임워크로 바꿨습니다 (파일 {len(changed)}개). 점검 통과.', files=len(changed))
        return _read(app)


def status(hub):
    out = []
    for record in hub.records:
        app = hub.resolve(record['id'])
        state = _read(app)
        if not state.get('version'):
            state = {**state, 'state': state.get('state') or 'unknown'}
        out.append({'id': record['id'], 'title': (record.get('site') or {}).get('title') or record['name'], **state,
                    'current': state.get('version') == version()})
    return {'version': version(), 'projects': out}


def update_all(hub, log=None):
    return [{'id': record['id'], **apply(hub, record, log)} for record in list(hub.records)]


def adopt(hub):
    """Projects from before the framework lived in the platform: one whose files already are the platform's is marked so,
    without rebuilding anything."""
    for record in hub.records:
        app = hub.resolve(record['id'])
        if not _read(app).get('version') and Path(record['root']).is_dir():
            write, drop = plan(record['root'])
            if not write and not drop:
                _write(app, version=version(), state='ok', said='플랫폼의 프레임워크와 같습니다.')


def watch(hub, every=60):
    """Keep every project on the platform's framework: checked now and then, a busy project taken when it is free."""
    def loop():
        while True:
            try:
                adopt(hub)
                update_all(hub)
            except Exception as error:      # the next round tries again; the platform keeps serving
                print('framework update:', error, flush=True)
            time.sleep(every)
    threading.Thread(target=loop, name='framework-update', daemon=True).start()
