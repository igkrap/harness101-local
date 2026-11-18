"""What this computer needs for the platform and its projects, looked at and set up from the platform.

Each item says what it is for, whether it is there, and - when it is not - what setting it up does: some are done by the platform
itself (pulling an image, the screens' tools of a project, the browser for screen checks, starting the database or the model server);
putting a program on the computer (Docker, Node.js, Git) is only offered through Homebrew and is done when asked twice; Docker Desktop
has to be opened by a person.
"""
import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

import sites

POSTGRES_IMAGE, BUILD_IMAGE = 'postgres:17-alpine', 'maven:3.9-eclipse-temurin-17'
BROWSER = Path.home() / '.local/share/mlx-server/browser-check'
MODEL_URL = 'http://127.0.0.1:8099/v1/models'


def _run(cmd, timeout=30, cwd=None):
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
        return done.returncode, (done.stdout or done.stderr).strip()
    except FileNotFoundError:
        return 127, ''
    except subprocess.TimeoutExpired:
        return 124, '시간이 너무 오래 걸렸습니다'


def _item(id, label, why, ok, detail='', fix=None, state=None):
    return {'id': id, 'label': label, 'why': why, 'state': state or ('ok' if ok else 'missing'), 'detail': detail, 'fix': None if ok else fix}


def _brew(formula, cask=False):
    if not shutil.which('brew'):
        return {'label': '설치 방법 안내', 'command': f"https://brew.sh 에서 Homebrew 를 설치한 뒤 brew install {'--cask ' if cask else ''}{formula}", 'installs': True, 'manual': True}
    return {'label': '설치', 'command': f"brew install {'--cask ' if cask else ''}{formula}", 'installs': True}


def check(hub=None):
    """Every item, as it stands now."""
    out = []
    code, version = _run(['docker', 'version', '--format', '{{.Server.Version}}'])
    if code == 127:
        out.append(_item('docker', 'Docker', '개발 DB와 앱 서버를 컨테이너로 돌린다', False, '설치돼 있지 않습니다', _brew('docker', cask=True)))
    elif code != 0:
        out.append(_item('docker', 'Docker', '개발 DB와 앱 서버를 컨테이너로 돌린다', False, '설치돼 있지만 꺼져 있습니다',
                         {'label': 'Docker Desktop 열기', 'command': 'open -a Docker', 'installs': False}, state='off'))
    else:
        out.append(_item('docker', 'Docker', '개발 DB와 앱 서버를 컨테이너로 돌린다', True, f'{version} 실행 중'))
    docker_up = code == 0
    if docker_up:
        missing = [image for image in (POSTGRES_IMAGE, BUILD_IMAGE) if _run(['docker', 'image', 'inspect', image])[0] != 0]
        out.append(_item('images', 'Docker 이미지 (Postgres, Maven)', 'DB를 띄우고 앱 서버를 빌드한다', not missing, '받아 둠' if not missing else '없음: ' + ', '.join(missing),
                         {'label': '받기', 'command': ' && '.join(f'docker pull {image}' for image in missing), 'installs': False}))
        running = _run(['docker', 'inspect', '-f', '{{.State.Running}}', sites.DB_CONTAINER])[1] == 'true'
        out.append(_item('db', f'개발 DB ({sites.DB_CONTAINER})', '모든 프로젝트의 개발 데이터베이스', running, '실행 중' if running else '꺼져 있거나 없습니다',
                         {'label': '켜기', 'command': f'docker start {sites.DB_CONTAINER}', 'installs': False}))
    code, version = _run(['node', '--version'])
    out.append(_item('node', 'Node.js', '화면 미리보기 서버와 화면 빌드, 화면 검사', code == 0, version if code == 0 else '설치돼 있지 않습니다', _brew('node')))
    code, version = _run(['git', '--version'])
    out.append(_item('git', 'Git', '프로젝트의 형상관리 (기록·되돌리기·작업 공간)', code == 0, version if code == 0 else '설치돼 있지 않습니다', _brew('git')))
    out.append(_item('python', 'Python', '플랫폼 자체', sys.version_info >= (3, 9), sys.version.split()[0]))
    try:
        with urllib.request.urlopen(MODEL_URL, timeout=5) as answer:
            model_ok, model_detail = answer.status == 200, '응답함'
    except Exception:
        model_ok, model_detail = False, '응답하지 않습니다'
    script = sites.ROOT / 'platform/scripts/qwen-serve-forever.sh'
    out.append(_item('model', '로컬 모델 서버 (8099)', '요청을 화면 정의로 바꾼다', model_ok, model_detail,
                     {'label': '켜기', 'command': f'nohup {script} >/tmp/qwen-serve.log 2>&1 &', 'installs': False}))
    runtime = BROWSER / 'runtime.json'
    browser_ok = False
    if runtime.is_file():
        try:
            config = json.loads(runtime.read_text())
            browser_ok = Path(config.get('playwrightModule', '')).exists() and Path(config.get('executablePath', '')).exists()
        except ValueError:
            pass
    out.append(_item('browser', '화면 검사 도구 (Playwright 크로미움)', '하네스가 브라우저로 화면을 검사한다', browser_ok, '준비됨' if browser_ok else '없거나 경로가 틀립니다',
                     {'label': '셋업', 'command': 'browser-check 설치', 'installs': False}))
    return out


def project(record):
    """What one project needs inside its own folder (shown on that project's 개발 환경, not with the computer's)."""
    root = Path(record['root'])
    ready = (root / 'frontend/node_modules').is_dir()
    return [_item(f"deps:{record['id']}", '화면 개발 부품 (node_modules)', '이 프로젝트의 화면 미리보기와 빌드', ready, '설치됨' if ready else '없음',
                  {'label': '설치', 'command': 'npm ci', 'installs': False})]


def fix(hub, item_id, sure=False):
    """Set one item up. Putting a program on the computer is done only with sure=True (asked twice)."""
    items = {item['id']: item for item in check(hub) + [one for record in hub.records for one in project(record)]}
    item = items.get(item_id)
    if item is None:
        raise ValueError(f'그런 점검 항목이 없습니다: {item_id}')
    if item['state'] == 'ok':
        return {'done': True, 'said': '이미 준비돼 있습니다.', 'items': list(items.values())}
    step = item['fix'] or {}
    if step.get('manual'):
        return {'done': False, 'said': step['command'], 'items': list(items.values())}
    if step.get('installs') and not sure:
        return {'done': False, 'ask': f"이 컴퓨터에 프로그램을 설치합니다: {step['command']}. 진행할까요?", 'items': list(items.values())}
    if item_id == 'browser':
        BROWSER.mkdir(parents=True, exist_ok=True)
        if not (BROWSER / 'package.json').is_file():
            (BROWSER / 'package.json').write_text('{"dependencies":{}}')
        for cmd in (['npm', 'install', '--no-audit', '--no-fund', 'playwright'], ['npx', 'playwright', 'install', 'chromium-headless-shell']):
            code, text = _run(cmd, timeout=1800, cwd=BROWSER)
            if code != 0:
                return {'done': False, 'said': f"{' '.join(cmd)} 실패: {text[-300:]}", 'items': check(hub)}
        shells = sorted((Path.home() / 'Library/Caches/ms-playwright').glob('chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell'))
        if not shells:
            return {'done': False, 'said': '브라우저를 받았지만 실행 파일을 찾지 못했습니다.', 'items': check(hub)}
        (BROWSER / 'runtime.json').write_text(json.dumps({'playwrightModule': str(BROWSER / 'node_modules/playwright'), 'executablePath': str(shells[-1])}, indent=2))
        return {'done': True, 'said': '화면 검사 도구를 준비했습니다.', 'items': check(hub)}
    if item_id.startswith('deps:'):
        record = next(one for one in hub.records if one['id'] == item_id.split(':', 1)[1])
        code, text = _run(['npm', 'ci', '--prefer-offline', '--no-audit', '--no-fund'], timeout=1800, cwd=Path(record['root']) / 'frontend')
        return {'done': code == 0, 'said': '설치했습니다.' if code == 0 else 'npm ci 실패: ' + text[-300:], 'items': check(hub)}
    if item_id == 'model':
        subprocess.Popen(['nohup', str(sites.ROOT / 'platform/scripts/qwen-serve-forever.sh')], stdout=open('/tmp/qwen-serve.log', 'a'), stderr=subprocess.STDOUT, start_new_session=True)
        return {'done': True, 'said': '모델 서버를 켰습니다. 모델을 올리는 데 몇 분 걸릴 수 있습니다.', 'items': check(hub)}
    code, text = _run(['/bin/sh', '-c', step['command']], timeout=3600)
    return {'done': code == 0, 'said': ('했습니다: ' if code == 0 else '실패했습니다: ') + (text[-300:] or step['command']), 'items': check(hub)}
