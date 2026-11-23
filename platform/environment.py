"""What this computer needs for the platform and its projects, looked at, found and set up from the platform - on macOS and Windows.

Each item says what it is for, whether it is there, and - when it is not - what the platform can do about it:
  찾기       a program that is installed but not where the platform looks (another folder, not on PATH): the usual places are
             searched, or a path is given; what is found is remembered (state/tool_paths.json) and used from then on
  셋업       done by the platform itself: pulling images, making or starting the database, starting Docker and waiting for it,
             the model server, the browser for screen checks, a project's screen packages
  설치       putting a program on the computer, after it is asked once more, by one of several ways: the official build
             (Docker.dmg / the installer, Node.js unpacked into the user's folder, Apple's developer tools for Git), or a package
             tool when there is one (Homebrew on macOS, winget on Windows) - never only through a package tool
`setup_all` takes every missing item in order (Docker, start Docker, images, database, Node.js, Git, model server, browser).
"""
import glob
import json
import os
import platform as host
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

import sites

POSTGRES_IMAGE, BUILD_IMAGE = 'postgres:17-alpine', 'maven:3.9-eclipse-temurin-17'
BROWSER = Path.home() / '.local/share/mlx-server/browser-check'
MODEL_URL = 'http://127.0.0.1:8099/v1/models'
PATHS = sites.ROOT / 'platform/state/tool_paths.json'
WINDOWS, MAC = host.system() == 'Windows', host.system() == 'Darwin'

# where each program usually is when it is not on PATH
_HOME = str(Path.home())
PLACES = {
    'docker': ['/usr/local/bin/docker', '/opt/homebrew/bin/docker', '/Applications/Docker.app/Contents/Resources/bin/docker', _HOME + '/.docker/bin/docker',
               r'C:\Program Files\Docker\Docker\resources\bin\docker.exe'],
    'node': ['/opt/homebrew/bin/node', '/usr/local/bin/node', _HOME + '/.nvm/versions/node/*/bin/node', _HOME + '/.volta/bin/node',
             r'C:\Program Files\nodejs\node.exe', os.path.expandvars(r'%APPDATA%\nvm\*\node.exe')],
    'git': ['/usr/bin/git', '/opt/homebrew/bin/git', '/usr/local/bin/git', r'C:\Program Files\Git\cmd\git.exe'],
    'brew': ['/opt/homebrew/bin/brew', '/usr/local/bin/brew'],
    'winget': [os.path.expandvars(r'%LOCALAPPDATA%\Microsoft\WindowsApps\winget.exe')],
}
PACKAGES = {  # (macOS Homebrew, Windows winget)
    'docker': ('--cask docker', 'Docker.DockerDesktop'),
    'node': ('node', 'OpenJS.NodeJS.LTS'),
    'git': ('git', 'Git.Git'),
}


def remembered():
    try:
        return json.loads(PATHS.read_text()).get('dirs', [])
    except (OSError, ValueError):
        return []


def _apply_paths():
    """Folders found before go in front of PATH for everything the platform runs."""
    current = os.environ.get('PATH', '').split(os.pathsep)
    for folder in reversed(remembered()):
        if folder not in current:
            current.insert(0, folder)
    os.environ['PATH'] = os.pathsep.join(current)


def remember(folder):
    dirs = [one for one in remembered() if one != folder]
    PATHS.parent.mkdir(parents=True, exist_ok=True)
    PATHS.write_text(json.dumps({'dirs': [folder] + dirs}, ensure_ascii=False, indent=1))
    _apply_paths()


_apply_paths()


def _run(cmd, timeout=30, cwd=None):
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
        return done.returncode, (done.stdout or done.stderr).strip()
    except FileNotFoundError:
        return 127, ''
    except subprocess.TimeoutExpired:
        return 124, '시간이 너무 오래 걸렸습니다'


def _find(tool):
    """A program installed where the platform does not look: the first of the usual places that holds it."""
    for place in PLACES.get(tool, []):
        for found in sorted(glob.glob(place), reverse=True):
            if Path(found).is_file():
                return found
    return None


def _item(id, label, why, ok, detail='', fix=None, state=None, find=False):
    return {'id': id, 'label': label, 'why': why, 'state': state or ('ok' if ok else 'missing'), 'detail': detail, 'fix': None if ok else fix,
            'find': bool(find) and not ok}


def _package_tool():
    """macOS: Homebrew; Windows: winget. None when it is not there."""
    return shutil.which('winget') if WINDOWS else shutil.which('brew')


ARCH = 'arm64' if host.machine().lower() in ('arm64', 'aarch64') else 'x64'


def _ways(tool):
    """Every way to put the program on this computer, the ones that need nothing else first. Each: id, label, what it does."""
    brew, winget = PACKAGES[tool]
    ways = []
    if WINDOWS:
        if shutil.which('winget'):
            ways.append({'way': 'winget', 'label': 'winget 으로 설치', 'command': f'winget install -e --id {winget}'})
        ways.append({'way': 'download', 'label': '공식 배포본으로 설치', 'command': {
            'docker': 'Docker Desktop Installer.exe 를 받아 실행 (관리자 확인 창이 뜸)',
            'node': 'Node.js 공식 zip 을 받아 사용자 폴더에 풂 (관리자 권한 필요 없음)',
            'git': 'Git for Windows 설치 파일을 받아 실행'}[tool]})
    else:
        ways.append({'way': 'download', 'label': {'docker': 'Docker.dmg 로 설치', 'node': '공식 배포본으로 설치', 'git': '애플 개발자 도구로 설치'}[tool], 'command': {
            'docker': 'Docker.dmg 를 받아 응용 프로그램 폴더에 넣음',
            'node': 'Node.js 공식 배포본을 받아 사용자 폴더에 풂 (관리자 비밀번호 필요 없음)',
            'git': 'xcode-select --install (설치 창이 뜸)'}[tool]})
        if shutil.which('brew'):
            ways.append({'way': 'brew', 'label': 'Homebrew 로 설치', 'command': f'brew install {brew}'})
    return ways


def _install(tool):
    ways = _ways(tool)
    return {'label': ways[0]['label'], 'command': ways[0]['command'], 'installs': True, 'ways': ways}


def _tool_item(tool, label, why, version_cmd):
    code, version = _run(version_cmd)
    if code == 0:
        return _item(tool, label, why, True, version.splitlines()[0] if version else '있음')
    found = _find(tool)
    return _item(tool, label, why, False, f'설치돼 있지만 플랫폼이 쓰는 경로에 없습니다: {found}' if found else '찾지 못했습니다', _install(tool), find=True)


DISK_LEAST_GB = 8          # a server build, a project's database and the model's swap need room: below this, work that builds or runs stops first


def disk_free_gb():
    return round(shutil.disk_usage(str(sites.ROOT)).free / 2 ** 30, 1)


def ready():
    """What would make building or running fail half way - said before starting, not found out by a crash ('' when nothing).
    A full disk stopped Docker in the middle of a build once (no space left on device), and everything after it failed."""
    problems = []
    free = disk_free_gb()
    if free < DISK_LEAST_GB:
        problems.append(f'디스크 여유가 {free}GB 뿐입니다 ({DISK_LEAST_GB}GB 이상 필요). 공간을 비운 뒤 다시 하세요.')
    if _run(['docker', 'info'], timeout=20)[0] != 0:
        problems.append('Docker 가 응답하지 않습니다. Docker Desktop 을 다시 켠 뒤 다시 하세요.')
    return ' '.join(problems)


def check(hub=None):
    """Every item, as it stands now."""
    out = []
    if MAC and not shutil.which('brew') and _find('brew'):        # installed but not on PATH: offer to use it (it is one way of installing, not a need)
        out.append(_item('brew', 'Homebrew', '설치 방법 중 하나', False, f'있지만 경로에 없습니다: {_find("brew")}', None, find=True))
    code, version = _run(['docker', 'version', '--format', '{{.Server.Version}}'])
    if code == 127:
        found = _find('docker')
        out.append(_item('docker', 'Docker', '개발 DB와 앱 서버를 컨테이너로 돌린다', False, f'설치돼 있지만 경로에 없습니다: {found}' if found else '찾지 못했습니다',
                         _install('docker'), find=True))
    elif code != 0:
        out.append(_item('docker', 'Docker', '개발 DB와 앱 서버를 컨테이너로 돌린다', False, '설치돼 있지만 꺼져 있습니다',
                         {'label': '켜기', 'command': 'Docker Desktop 을 켜고 준비될 때까지 기다림', 'installs': False}, state='off'))
    else:
        out.append(_item('docker', 'Docker', '개발 DB와 앱 서버를 컨테이너로 돌린다', True, f'{version} 실행 중'))
    if code == 0:
        missing = [image for image in (POSTGRES_IMAGE, BUILD_IMAGE) if _run(['docker', 'image', 'inspect', image])[0] != 0]
        out.append(_item('images', 'Docker 이미지 (Postgres, Maven)', 'DB를 띄우고 앱 서버를 빌드한다', not missing, '받아 둠' if not missing else '없음: ' + ', '.join(missing),
                         {'label': '받기', 'command': ' / '.join(f'docker pull {image}' for image in missing), 'installs': False}))
        state = _run(['docker', 'inspect', '-f', '{{.State.Running}}', sites.DB_CONTAINER])
        running, exists = state[1] == 'true', state[0] == 0
        out.append(_item('db', f'개발 DB ({sites.DB_CONTAINER})', '모든 프로젝트의 개발 데이터베이스', running, '실행 중' if running else '꺼져 있습니다' if exists else '없습니다',
                         {'label': '켜기' if exists else '만들기', 'command': f'docker start {sites.DB_CONTAINER}' if exists else '네트워크·볼륨·DB 컨테이너를 만든다', 'installs': False}))
    free = disk_free_gb()
    out.append(_item('disk', '디스크 여유', '앱 서버 빌드, 개발 DB, 모델이 쓰는 공간', free >= DISK_LEAST_GB, f'{free}GB 남음' + ('' if free >= DISK_LEAST_GB else f' ({DISK_LEAST_GB}GB 이상 필요)'),
                     {'label': '안내', 'command': '안 쓰는 Docker 이미지·큰 파일을 지워 공간을 비운다', 'installs': False, 'manual': True, 'note': '플랫폼이 지울 것을 정하지 않습니다. 안 쓰는 Docker 이미지(docker image prune), 큰 파일을 직접 정리하세요.'}))
    out.append(_tool_item('node', 'Node.js', '화면 미리보기 서버와 화면 빌드, 화면 검사', ['node', '--version']))
    out.append(_tool_item('git', 'Git', '프로젝트의 형상관리 (기록·되돌리기·작업 공간)', ['git', '--version']))
    try:
        with urllib.request.urlopen(MODEL_URL, timeout=5) as answer:
            model_ok, model_detail = answer.status == 200, '응답함'
    except Exception:
        model_ok, model_detail = False, '응답하지 않습니다'
    if not model_ok and not (MAC and host.machine() == 'arm64'):
        out.append(_item('model', '로컬 모델 서버 (8099)', '요청을 화면 정의로 바꾼다', False, '이 컴퓨터에서는 MLX(애플 실리콘 맥 전용)를 쓸 수 없습니다. 다른 모델 실행기가 필요합니다',
                         {'label': '안내', 'command': '모델 실행기를 정해야 합니다 (예: llama.cpp, Ollama). AI 모델 설정에서 모델 주소를 바꿀 수 있습니다', 'installs': False, 'manual': True}))
    else:
        out.append(_item('model', '로컬 모델 서버 (8099)', '요청을 화면 정의로 바꾼다', model_ok, model_detail,
                         {'label': '켜기', 'command': 'qwen-serve-forever.sh', 'installs': False}))
    runtime = BROWSER / 'runtime.json'
    browser_ok = False
    if runtime.is_file():
        try:
            config = json.loads(runtime.read_text())
            browser_ok = Path(config.get('playwrightModule', '')).exists() and Path(config.get('executablePath', '')).exists()
        except ValueError:
            pass
    out.append(_item('browser', '화면 검사 도구 (Playwright 크로미움)', '하네스가 브라우저로 화면을 검사한다', browser_ok, '준비됨' if browser_ok else '없거나 경로가 틀립니다',
                     {'label': '셋업', 'command': 'Playwright 와 크로미움을 받는다', 'installs': False}))
    return out


def project(record):
    """What one project needs inside its own folder (shown on that project's 개발 환경, not with the computer's)."""
    root = Path(record['root'])
    ready = (root / 'frontend/node_modules').is_dir()
    return [_item(f"deps:{record['id']}", '화면 개발 부품 (node_modules)', '이 프로젝트의 화면 미리보기와 빌드', ready, '설치됨' if ready else '없음',
                  {'label': '설치', 'command': 'npm ci', 'installs': False})]


def find(hub, tool, path=None):
    """찾기: the usual places, or the path given; what is found is used from then on."""
    if tool not in PLACES:
        raise ValueError(f'찾을 수 있는 것이 아닙니다: {tool}')
    found = path.strip() if path else _find(tool)
    if found and Path(found).is_dir():
        found = next((str(Path(found) / name) for name in (tool, tool + '.exe') if (Path(found) / name).is_file()), None)
    if not found or not Path(found).is_file():
        return {'done': False, 'said': f'{tool} 을(를) 찾지 못했습니다' + (f' ({path})' if path else ' (흔히 설치되는 곳에 없습니다). 설치하거나 경로를 적어 주세요.'), 'items': check(hub)}
    remember(str(Path(found).parent))
    return {'done': True, 'said': f'{found} 를 쓰도록 했습니다.', 'items': check(hub)}


LOCAL = Path.home() / '.local/share/local-workshop/tools'


def _download(url, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=600) as answer, open(target, 'wb') as out:
        shutil.copyfileobj(answer, out)
    return target


def _install_by(tool, way):
    """Put the program on the computer the chosen way. (ok, what happened)"""
    brew, winget = PACKAGES[tool]
    try:
        if way == 'brew':
            code, text = _run(['brew', 'install', *brew.split()], timeout=3600)
            return code == 0, text
        if way == 'winget':
            code, text = _run(['winget', 'install', '-e', '--id', winget, '--accept-package-agreements', '--accept-source-agreements'], timeout=3600)
            return code == 0, text
        if tool == 'node':                     # the official build, unpacked into the user's own folder: no administrator needed
            index = json.loads(urllib.request.urlopen('https://nodejs.org/dist/index.json', timeout=60).read())
            version = next(one['version'] for one in index if one.get('lts'))
            name = f"node-{version}-{'win' if WINDOWS else 'darwin'}-{ARCH}"
            archive = _download(f"https://nodejs.org/dist/{version}/{name}.{'zip' if WINDOWS else 'tar.gz'}", LOCAL / f"{name}.{'zip' if WINDOWS else 'tar.gz'}")
            shutil.unpack_archive(str(archive), str(LOCAL))
            remember(str(LOCAL / name) if WINDOWS else str(LOCAL / name / 'bin'))
            return True, f'Node.js {version} 를 {LOCAL / name} 에 두었습니다.'
        if tool == 'docker' and MAC:
            dmg = _download(f"https://desktop.docker.com/mac/main/{'arm64' if ARCH == 'arm64' else 'amd64'}/Docker.dmg", LOCAL / 'Docker.dmg')
            code, text = _run(['hdiutil', 'attach', '-nobrowse', '-quiet', '-mountpoint', '/Volumes/DockerInstall', str(dmg)], timeout=600)
            if code != 0:
                return False, text
            code, text = _run(['cp', '-R', '/Volumes/DockerInstall/Docker.app', '/Applications/'], timeout=600)
            _run(['hdiutil', 'detach', '-quiet', '/Volumes/DockerInstall'], timeout=120)
            return code == 0, '응용 프로그램 폴더에 Docker 를 넣었습니다.' if code == 0 else text
        if tool == 'docker' and WINDOWS:
            exe = _download('https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe', LOCAL / 'DockerDesktopInstaller.exe')
            code, text = _run([str(exe), 'install', '--quiet', '--accept-license'], timeout=3600)
            return code == 0, text or 'Docker Desktop 을 설치했습니다.'
        if tool == 'git' and MAC:
            _run(['xcode-select', '--install'], timeout=60)
            return True, '애플 개발자 도구 설치 창을 열었습니다. 창에서 설치를 마친 뒤 "다시 점검"을 누르세요.'
        if tool == 'git' and WINDOWS:
            release = json.loads(urllib.request.urlopen('https://api.github.com/repos/git-for-windows/git/releases/latest', timeout=60).read())
            asset = next(one for one in release['assets'] if one['name'].endswith('-64-bit.exe') and 'Portable' not in one['name'])
            exe = _download(asset['browser_download_url'], LOCAL / asset['name'])
            code, text = _run([str(exe), '/VERYSILENT', '/NORESTART'], timeout=3600)
            return code == 0, text or 'Git 을 설치했습니다.'
    except Exception as problem:
        return False, str(problem)
    return False, '이 방법은 이 컴퓨터에서 쓸 수 없습니다.'


def _wait_docker(seconds=180):
    end = time.time() + seconds
    while time.time() < end:
        if _run(['docker', 'info'], timeout=20)[0] == 0:
            return True
        time.sleep(5)
    return False


def _start_docker():
    if WINDOWS:
        exe = r'C:\Program Files\Docker\Docker\Docker Desktop.exe'
        subprocess.Popen([exe], creationflags=getattr(subprocess, 'DETACHED_PROCESS', 0)) if Path(exe).exists() else None
    else:
        _run(['open', '-a', 'Docker'])
    return _wait_docker()


def fix(hub, item_id, sure=False, way=None):
    """Set one item up. Putting a program on the computer is done only with sure=True (asked once more); way: which of its ways."""
    items = {item['id']: item for item in check(hub) + [one for record in hub.records for one in project(record)]}
    item = items.get(item_id)
    if item is None:
        raise ValueError(f'그런 점검 항목이 없습니다: {item_id}')
    if item['state'] == 'ok':
        return {'done': True, 'said': '이미 준비돼 있습니다.', 'items': list(items.values())}
    step = item['fix'] or {}
    if step.get('manual'):
        return {'done': False, 'said': step.get('note') or '', 'command': step['command'], 'items': list(items.values())}
    if item.get('find') and _find(item_id):          # installed somewhere else: use it rather than install again
        return find(hub, item_id)
    if step.get('installs') and not sure:
        chosen = next((one for one in step.get('ways', []) if one['way'] == way), (step.get('ways') or [step])[0])
        return {'done': False, 'ask': f"이 컴퓨터에 프로그램을 설치합니다 - {chosen.get('label', '')}: {chosen['command']}. 진행할까요?", 'way': chosen.get('way'), 'items': list(items.values())}
    if step.get('installs'):
        ok, text = _install_by(item_id, way or step['ways'][0]['way'])
        if ok and item_id == 'docker':
            _start_docker()
        return {'done': ok, 'said': ('설치했습니다. ' if ok else '설치하지 못했습니다: ') + text[-300:], 'items': check(hub)}
    if item_id == 'docker':
        ok = _start_docker()
        return {'done': ok, 'said': 'Docker 를 켰습니다.' if ok else 'Docker 를 켰지만 3분 안에 준비되지 않았습니다. Docker Desktop 창을 확인하세요.', 'items': check(hub)}
    if item_id == 'images':
        for image in (POSTGRES_IMAGE, BUILD_IMAGE):
            if _run(['docker', 'image', 'inspect', image])[0] != 0:
                code, text = _run(['docker', 'pull', image], timeout=3600)
                if code != 0:
                    return {'done': False, 'said': f'{image} 를 받지 못했습니다: {text[-300:]}', 'items': check(hub)}
        return {'done': True, 'said': '이미지를 받았습니다.', 'items': check(hub)}
    if item_id == 'db':
        from first_setup import Setup                  # the same steps as the first setup: networks, volume, the database container
        setup = Setup(sites.ROOT, state=sites.ROOT / 'platform/state', log=lambda *_: None)
        setup.base()
        setup.database()
        return {'done': True, 'said': '개발 DB를 준비했습니다.', 'items': check(hub)}
    if item_id == 'browser':
        BROWSER.mkdir(parents=True, exist_ok=True)
        if not (BROWSER / 'package.json').is_file():
            (BROWSER / 'package.json').write_text('{"dependencies":{}}')
        npm, npx = ('npm.cmd', 'npx.cmd') if WINDOWS else ('npm', 'npx')
        for cmd in ([npm, 'install', '--no-audit', '--no-fund', 'playwright'], [npx, 'playwright', 'install', 'chromium-headless-shell']):
            code, text = _run(cmd, timeout=1800, cwd=BROWSER)
            if code != 0:
                return {'done': False, 'said': f"{' '.join(cmd)} 실패: {text[-300:]}", 'items': check(hub)}
        cache = Path(os.path.expandvars(r'%LOCALAPPDATA%\ms-playwright')) if WINDOWS else Path.home() / 'Library/Caches/ms-playwright'
        shells = sorted(cache.glob('chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell*'))
        shells = [shell for shell in shells if shell.is_file()]
        if not shells:
            return {'done': False, 'said': '브라우저를 받았지만 실행 파일을 찾지 못했습니다.', 'items': check(hub)}
        (BROWSER / 'runtime.json').write_text(json.dumps({'playwrightModule': str(BROWSER / 'node_modules/playwright'), 'executablePath': str(shells[-1])}, indent=2))
        return {'done': True, 'said': '화면 검사 도구를 준비했습니다.', 'items': check(hub)}
    if item_id.startswith('deps:'):
        record = next(one for one in hub.records if one['id'] == item_id.split(':', 1)[1])
        code, text = _run(['npm.cmd' if WINDOWS else 'npm', 'ci', '--prefer-offline', '--no-audit', '--no-fund'], timeout=1800, cwd=Path(record['root']) / 'frontend')
        return {'done': code == 0, 'said': '설치했습니다.' if code == 0 else 'npm ci 실패: ' + text[-300:], 'items': check(hub)}
    if item_id == 'model':
        subprocess.Popen(['nohup', str(sites.ROOT / 'platform/scripts/qwen-serve-forever.sh')], stdout=open('/tmp/qwen-serve.log', 'a'), stderr=subprocess.STDOUT, start_new_session=True)
        return {'done': True, 'said': '모델 서버를 켰습니다. 모델을 올리는 데 몇 분 걸릴 수 있습니다.', 'items': check(hub)}
    return {'done': False, 'said': '이 항목은 플랫폼이 셋업할 수 없습니다.', 'items': check(hub)}


ORDER = ['brew', 'docker', 'images', 'db', 'node', 'git', 'model', 'browser']


def setup_all(hub, sure=False):
    """Every missing item in order; stops at the first that needs a person (a manual step, or installing before it is agreed)."""
    said = []
    for item_id in ORDER:
        current = {item['id']: item for item in check(hub)}
        if item_id not in current or current[item_id]['state'] == 'ok':
            continue
        result = fix(hub, item_id, sure)
        if result.get('ask') or result.get('command') or not result.get('done'):
            result['said'] = ' / '.join(said + [result.get('said') or result.get('ask') or ''])
            return result
        said.append(f"{current[item_id]['label']}: {result.get('said')}")
    return {'done': True, 'said': ' / '.join(said) or '모두 준비돼 있습니다.', 'items': check(hub)}
