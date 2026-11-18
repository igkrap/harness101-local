"""The platform's own setup pack: everything needed to set the making side up on another machine.

Not to be confused with the operating setup packs (windows_pack.py), which carry the made system to where it is used.
This pack carries the platform (its pages built), the framework every project runs on (platform/base) and the harness -
no project: projects are made on the new machine, where the platform's first page checks and sets up the tools
(Docker, the development database, Node, the browser used for checking screens). The installer itself prepares only
what the platform needs to start and the local model's runtime; the model file (about 15GB) travels separately as a
model pack, or is downloaded by the installer.

This file builds the pack for a Mac with Apple silicon (the local model runs on MLX, which exists only there).
"""
import json
import re
import shutil
import subprocess
import tarfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHARE = Path.home() / '.local/share/local-workshop'
PACKS = SHARE / 'packs/platform'
MLX_VENV = Path.home() / '.local/share/mlx-server/venv'
BROWSER = Path.home() / '.local/share/mlx-server/browser-check'
HF_HUB = Path.home() / '.cache/huggingface/hub'

INSTALL = r'''#!/bin/bash
# 플랫폼 최초 셋업 (맥, 애플 실리콘). 플랫폼을 풀고, 로컬 모델 실행 환경을 갖추고, 플랫폼을 켠다.
# 프로젝트는 들어 있지 않다: 플랫폼이 켜지면 첫 화면에서 개발 환경(도커, 개발 DB, Node, 화면 검사용 브라우저)을 점검·셋업하고 첫 프로젝트를 만든다.
#   bash install.sh                 ~/harness-platform 에 설치
#   bash install.sh /다른/위치
# 이미 설치된 곳에서는 거절한다 (플랫폼만 새 버전으로 바꾸려면 update.sh).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TARGET="${1:-$HOME/harness-platform}"
MODEL="__MODEL__"
MLX_DIR="${PACK_MLX_DIR:-$HOME/.local/share/mlx-server}"
say() { printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
fail() { printf '\n실패: %s\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ] || fail "이 팩은 애플 실리콘 맥용입니다."
[ -f "$TARGET/platform/server.py" ] && fail "$TARGET 에는 이미 설치되어 있습니다. 플랫폼을 새 버전으로 바꾸려면 bash update.sh $TARGET"

say "1/4 플랫폼 실행에 필요한 것 확인"
command -v python3 >/dev/null 2>&1 && python3 -c 'import sys' 2>/dev/null || fail "python3 이 없습니다. 터미널에서 xcode-select --install 을 실행해 애플 개발 도구를 설치한 뒤 다시 하세요."
PY=""
for candidate in python3.13 python3.12 python3.11 python3.10; do command -v "$candidate" >/dev/null 2>&1 && { PY="$(command -v "$candidate")"; break; }; done
[ -n "$PY" ] || fail "로컬 모델 실행 환경에 Python 3.10 이상이 필요합니다. https://www.python.org/downloads/macos/ 의 설치 파일(또는 Homebrew 가 있으면 brew install python@3.13)로 설치한 뒤 다시 하세요."

say "2/4 플랫폼 풀기 → $TARGET"
mkdir -p "$TARGET"
tar -xzf "$HERE/source/platform.tar.gz" -C "$TARGET"
cp "$HERE/VERSION.json" "$TARGET/PLATFORM_VERSION.json"
chmod +x "$TARGET/start.sh" "$TARGET/stop.sh" "$TARGET/platform/scripts/"*.sh 2>/dev/null || true

say "3/4 로컬 모델 실행 환경 (MLX)"
[ -x "$MLX_DIR/venv/bin/python" ] || "$PY" -m venv "$MLX_DIR/venv"
"$MLX_DIR/venv/bin/python" -m pip install -q --upgrade pip
"$MLX_DIR/venv/bin/python" -m pip install -q "mlx-lm==__MLX_LM__"
"$MLX_DIR/venv/bin/python" "$HERE/scripts/patch_mlx.py" "$MLX_DIR/venv"

say "4/4 모델 ($MODEL)"
HUB="${HF_HOME:-$HOME/.cache/huggingface}/hub"
FOLDER="$HUB/models--$(printf '%s' "$MODEL" | sed 's#/#--#g')"
PACKED="$(ls "$HERE"/model-pack-*.tar "$HERE"/../model-pack-*.tar 2>/dev/null | head -1 || true)"
if [ "${PACK_SKIP_MODEL:-}" = "1" ]; then echo "  (시험 설치: 모델은 건너뜀)"
elif [ -d "$FOLDER/snapshots" ]; then echo "  이미 있습니다."
elif [ -n "$PACKED" ]; then echo "  모델 팩에서 풉니다: $PACKED"; mkdir -p "$HUB"; tar -xf "$PACKED" -C "$HUB"
else echo "  모델 팩이 없어 인터넷에서 받습니다 (약 15GB)"; "$MLX_DIR/venv/bin/hf" download "$MODEL" >/dev/null
fi

say "설치했습니다. 플랫폼을 켭니다."
[ "${PACK_NO_START:-}" = "1" ] || bash "$TARGET/start.sh"
echo "  켜기:  bash $TARGET/start.sh   ·   끄기:  bash $TARGET/stop.sh"
echo "  처음 열리는 화면에서 개발 환경을 셋업하고 첫 프로젝트를 만드세요."
'''

UPDATE = r'''#!/bin/bash
# 플랫폼만 새 버전으로: 플랫폼·하네스 프로그램을 이 팩의 것으로 바꾼다.
# 그 맥에서 만든 것(프로젝트들, 실행 기록과 계정 platform/state, 개발 DB)은 건드리지 않는다. 프레임워크는 플랫폼이 켜질 때 모든 프로젝트에 맞춘다.
#   bash update.sh                  ~/harness-platform 에 설치된 것을
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TARGET="${1:-$HOME/harness-platform}"
fail() { printf '\n실패: %s\n' "$*" >&2; exit 1; }
[ -f "$TARGET/platform/server.py" ] || fail "$TARGET 에 설치된 플랫폼이 없습니다. 처음 설치는 install.sh 로 합니다."
NEW="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['stamp'])" "$HERE/VERSION.json")"
OLD="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['stamp'])" "$TARGET/PLATFORM_VERSION.json" 2>/dev/null || echo 0)"
[ "$NEW" = "$OLD" ] && { echo "이미 이 버전($NEW)입니다."; exit 0; }
[ "$NEW" \< "$OLD" ] && [ "${2:-}" != "--force" ] && fail "설치된 버전($OLD)이 이 팩($NEW)보다 새것입니다. 일부러 되돌리려면 끝에 --force 를 붙이세요."
[ "${PACK_NO_STOP:-}" = "1" ] || bash "$TARGET/stop.sh" platform || true      # (시험 설치에서는 끄지 않는다: 같은 맥의 실제 플랫폼이 꺼지므로)
KEEP="$TARGET/previous-platform-$OLD"
rm -rf "$KEEP"; mkdir -p "$KEEP"
STAGE="$(mktemp -d)"
tar -xzf "$HERE/source/platform.tar.gz" -C "$STAGE"
for part in $(ls "$STAGE"); do
  if [ -e "$TARGET/$part" ] && [ "$part" != "platform" ]; then mv "$TARGET/$part" "$KEEP/$part"; fi
done
# platform/: 그 맥의 기록(state)과 받아 둔 도구(node_modules)는 남기고 나머지를 바꾼다.
mkdir -p "$KEEP/platform"
( cd "$TARGET/platform" && for item in $(ls -A); do case "$item" in state) ;; *) mv "$item" "$KEEP/platform/$item";; esac; done )
( cd "$STAGE" && tar -cf - --exclude './platform/web/node_modules' . ) | ( cd "$TARGET" && tar -xf - )
rm -rf "$STAGE"
cp "$HERE/VERSION.json" "$TARGET/PLATFORM_VERSION.json"
chmod +x "$TARGET/start.sh" "$TARGET/stop.sh" "$TARGET/platform/scripts/"*.sh "$TARGET/platform/start.sh" 2>/dev/null || true
echo "플랫폼을 $OLD → $NEW 로 바꿨습니다. 이전 것은 $KEEP 에 있습니다. 켜기: bash $TARGET/start.sh"
echo "(프로젝트들은 플랫폼이 켜지면 새 프레임워크로 함께 맞춰지고, 점검 결과는 개발 환경 화면에 나옵니다.)"
'''

START = r'''#!/bin/bash
# 모델 서버와 플랫폼을 켠다 (이미 켜져 있으면 그대로 둔다).
ROOT="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$ROOT/platform/state"
if docker info >/dev/null 2>&1; then
  docker start mdi-db >/dev/null 2>&1 || true          # (없으면 플랫폼의 개발 환경 화면에서 만든다)
  for name in $(docker ps -a --format '{{.Names}}' | grep -E '^mdi-.*-api$'); do docker start "$name" >/dev/null 2>&1 || true; done
else echo "도커가 꺼져 있습니다. 플랫폼의 개발 환경 화면에서 확인하세요."; fi
if ! curl -fsS --max-time 2 http://127.0.0.1:8099/v1/models >/dev/null 2>&1; then
  nohup "$ROOT/platform/scripts/qwen-serve-forever.sh" >/dev/null 2>&1 &
  echo "모델 서버를 켰습니다 (모델을 올리는 데 1분쯤 걸립니다)."
fi
if ! curl -fsS --max-time 2 http://127.0.0.1:5293/api/state >/dev/null 2>&1; then
  ( cd "$ROOT/platform" && nohup sh start.sh >> state/platform.log 2>&1 & )
  for i in $(seq 1 60); do curl -fsS --max-time 2 http://127.0.0.1:5293/api/state >/dev/null 2>&1 && break; sleep 2; done
fi
echo "플랫폼: http://127.0.0.1:5293"
[ "${1:-}" = "--no-open" ] || open http://127.0.0.1:5293 2>/dev/null || true
'''

STOP = r'''#!/bin/bash
# 플랫폼과 모델 서버를 끈다 (개발 DB와 앱 서버 컨테이너는 그대로 둔다).  bash stop.sh platform = 플랫폼만
ROOT="$(cd "$(dirname "$0")" && pwd)"
for port in 5293; do pid="$(lsof -iTCP:$port -sTCP:LISTEN -P -t 2>/dev/null | head -1)"; [ -n "$pid" ] && kill "$pid" 2>/dev/null; done
if [ "${1:-}" != "platform" ]; then
  for file in qwen-supervisor.pid qwen-model-server.pid; do [ -f "$ROOT/platform/state/$file" ] && kill "$(cat "$ROOT/platform/state/$file")" 2>/dev/null; done
fi
echo "껐습니다."
'''

PATCH = r'''"""Make the local model server keep its prompt cache within --prompt-cache-bytes.

mlx_lm's server enforces that limit only for models served in batches; a model served one request at a time
(this one) let the cache grow until the Mac ran out of memory for the model. Applied again after every install or
upgrade of mlx_lm; does nothing when it is already in, and says so when the line it changes is no longer there.
"""
import sys
from pathlib import Path

OLD = "    prompt_cache = LRUPromptCache(model_provider.cli_args.prompt_cache_size)\n"
NEW = ("    # Local fix: also enforce --prompt-cache-bytes for sequentially served models\n"
       "    # (upstream only trims by bytes in the batched path, so the cache grew without bound).\n"
       "    _bytes = model_provider.cli_args.prompt_cache_bytes\n"
       "    prompt_cache = LRUPromptCache(model_provider.cli_args.prompt_cache_size,\n"
       "                                  **({'max_bytes': _bytes} if _bytes else {}))\n")
found = list(Path(sys.argv[1]).glob('lib/python*/site-packages/mlx_lm/server.py'))
if not found:
    sys.exit('mlx_lm 이 설치되어 있지 않습니다.')
text = found[0].read_text()
if "'max_bytes': _bytes" in text:
    print('  모델 서버 보정: 이미 들어 있습니다.')
elif OLD in text:
    found[0].with_suffix('.py.orig').write_text(text)
    found[0].write_text(text.replace(OLD, NEW, 1))
    print('  모델 서버 보정: 넣었습니다.')
else:
    sys.exit('모델 서버 보정을 넣을 자리를 찾지 못했습니다 (mlx_lm 버전이 달라졌습니다). 메모리 부족으로 모델 서버가 죽을 수 있습니다.')
'''


def _readme(version):
    return f"""# 플랫폼 셋업 팩 (맥, 애플 실리콘)

버전 {version['stamp']} · 만든 때 {version['made_at']} · 프레임워크 {version['framework']}

말로 업무 시스템을 만드는 쪽(플랫폼)을 다른 맥에 올리는 팩입니다. 프로젝트는 들어 있지 않습니다 - 설치한 뒤 플랫폼에서 만듭니다.
(만든 시스템을 쓰는 서버에 올리는 것은 프로젝트마다 "셋업 팩 만들어줘" 로 만드는 **운영 셋업 팩**입니다.)

## 필요한 것

- 애플 실리콘 맥, 메모리 32GB 이상 (로컬 모델 {version['model']} 이 약 16GB 를 씁니다), 빈 디스크 40GB 이상
- 애플 개발 도구 (`xcode-select --install`), Python 3.10 이상 (python.org 설치 파일 또는 Homebrew)
- 인터넷 (모델 실행 환경을 받습니다). 모델 파일은 모델 팩이 있으면 받지 않습니다.

## 최초 셋업

1. 이 zip 을 풉니다. 모델 팩(`model-pack-….tar`)이 있으면 푼 폴더 안이나 바로 옆에 둡니다.
2. 터미널에서 `bash install.sh` (다른 위치에 두려면 `bash install.sh /원하는/위치`). 기본 위치는 `~/harness-platform` 입니다.
3. 끝나면 플랫폼이 브라우저에 열립니다. 첫 화면에서 **개발 환경**(도커, 개발 DB, Node, 화면 검사용 브라우저)을 점검하고
   버튼으로 셋업한 뒤, **새 프로젝트**를 만듭니다.

## 플랫폼만 새 버전으로

새 팩을 풀고 `bash update.sh`. 플랫폼, 하네스, 프레임워크가 바뀝니다. 그 맥에서 만든 프로젝트·실행 기록·계정·개발 DB는 그대로이고,
프로젝트들은 플랫폼이 켜질 때 새 프레임워크로 함께 맞춰집니다 (점검 결과는 개발 환경 화면에).
설치된 것보다 오래된 팩은 거절합니다(`bash update.sh ~/harness-platform --force` 로 일부러 되돌릴 수 있음). 이전 것은 `previous-platform-…` 폴더에 남습니다.

## 들어 있는 것

- `source/platform.tar.gz` 플랫폼(화면은 미리 빌드됨), 프레임워크(platform/base), 하네스
- `install.sh`, `update.sh`, `scripts/patch_mlx.py`, `VERSION.json`
- 들어 있지 않은 것: 프로젝트, 모델 파일(모델 팩으로 따로), 실행 기록, 비밀번호 파일
"""


def _git_archive(repo, target, extra=None):
    """The repository's committed files as a tar.gz (what is not committed does not travel)."""
    with tarfile.open(target, 'w:gz') as archive:
        raw = subprocess.run(['git', 'archive', '--format=tar', 'HEAD'], cwd=repo, capture_output=True, timeout=300)
        if raw.returncode != 0:
            raise RuntimeError('git archive 실패: ' + raw.stderr.decode(errors='replace')[-300:])
        import io
        with tarfile.open(fileobj=io.BytesIO(raw.stdout)) as source:
            for member in source.getmembers():
                archive.addfile(member, source.extractfile(member) if member.isfile() else None)
        for name, text, mode in extra or []:
            data = text if isinstance(text, bytes) else text.encode('utf-8')
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(data), mode, int(time.time())
            archive.addfile(info, io.BytesIO(data))


def _model_id():
    script = (ROOT / 'platform/scripts/qwen-serve-forever.sh').read_text()
    return re.search(r'--model (\S+)', script).group(1)


def _version_of(package, python):
    out = subprocess.run([str(python), '-m', 'pip', 'show', package], capture_output=True, text=True, timeout=60).stdout
    found = re.search(r'^Version: (\S+)', out, re.M)
    return found.group(1) if found else ''


def build(project=None, note=None):
    """Make the platform pack from what the platform's repository holds - no project goes in. Returns its record."""
    note = note or (lambda *_: None)
    dirty = [ROOT.name] if subprocess.run(['git', 'status', '--porcelain'], cwd=ROOT, capture_output=True, text=True).stdout.strip() else []
    stamp = time.strftime('%Y%m%d-%H%M%S')
    name = f'platform-pack-{stamp}-mac'
    folder = PACKS / name
    (folder / 'source').mkdir(parents=True)
    (folder / 'scripts').mkdir()
    note('플랫폼 화면 빌드')
    built = subprocess.run(['npm', 'run', 'build'], cwd=ROOT / 'platform/web', capture_output=True, text=True, timeout=600)
    if built.returncode != 0:
        raise RuntimeError('플랫폼 화면을 빌드하지 못했습니다: ' + (built.stdout + built.stderr)[-400:])
    dist = ROOT / 'platform/web/dist'
    pages = [(f'platform/web/dist/{path.relative_to(dist)}', path.read_bytes(), 0o644) for path in sorted(dist.rglob('*')) if path.is_file()]
    note('소스 묶기')
    _git_archive(ROOT, folder / 'source/platform.tar.gz', extra=[('start.sh', START, 0o755), ('stop.sh', STOP, 0o755)] + pages)
    playwright = json.loads((BROWSER / 'node_modules/playwright/package.json').read_text())['version'] if (BROWSER / 'node_modules/playwright/package.json').is_file() else 'latest'
    import framework_update
    version = {'stamp': stamp, 'made_at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'platform': 'mac-arm64', 'model': _model_id(), 'mlx_lm': _version_of('mlx-lm', MLX_VENV / 'bin/python') or '0.31.3',
               'playwright': playwright, 'framework': framework_update.version(),
               'platform_commit': subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True).stdout.strip()}
    (folder / 'VERSION.json').write_text(json.dumps(version, ensure_ascii=False, indent=1), encoding='utf-8')
    install = INSTALL.replace('__MODEL__', version['model']).replace('__MLX_LM__', version['mlx_lm']).replace('__PLAYWRIGHT__', version['playwright'])
    for file, text in (('install.sh', install), ('update.sh', UPDATE), ('scripts/patch_mlx.py', PATCH), ('README.md', _readme(version))):
        (folder / file).write_text(text, encoding='utf-8')
        if file.endswith('.sh'):
            (folder / file).chmod(0o755)
    for script in ('install.sh', 'update.sh'):
        check = subprocess.run(['bash', '-n', str(folder / script)], capture_output=True, text=True)
        if check.returncode != 0:
            raise RuntimeError(f'{script} 문법 오류: {check.stderr[-300:]}')
    archive = PACKS / f'{name}.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as out:
        for file in sorted(folder.rglob('*')):
            if file.is_file():
                info = zipfile.ZipInfo.from_file(file, f'{name}/{file.relative_to(folder)}')
                info.compress_type = zipfile.ZIP_DEFLATED
                out.writestr(info, file.read_bytes())
    for old in sorted(path for path in PACKS.glob('platform-pack-*-mac') if path.is_dir())[:-3]:
        shutil.rmtree(old, ignore_errors=True)
        (PACKS / (old.name + '.zip')).unlink(missing_ok=True)
    return {'kind': 'platform-pack', 'success': True, 'name': archive.name, 'file': str(archive), 'folder': str(folder), 'size': archive.stat().st_size, 'version': version, 'uncommitted': dirty}


def model_pack(note=None):
    """The local model's files as one tar (to carry to a machine without internet). Made once per model; about 15GB."""
    model = _model_id()
    source = HF_HUB / ('models--' + model.replace('/', '--'))
    if not (source / 'snapshots').is_dir():
        raise RuntimeError(f'이 맥에 모델 파일이 없습니다: {source}')
    PACKS.mkdir(parents=True, exist_ok=True)
    target = PACKS / ('model-pack-' + model.split('/')[-1].lower() + '.tar')
    if not target.is_file():
        (note or (lambda *_: None))('모델 파일 묶기 (약 15GB, 몇 분 걸립니다)')
        part = target.with_suffix('.part')
        result = subprocess.run(['tar', '-cf', str(part), '-C', str(HF_HUB), source.name], capture_output=True, text=True, timeout=7200)
        if result.returncode != 0:
            part.unlink(missing_ok=True)
            raise RuntimeError('모델 팩을 만들지 못했습니다: ' + result.stderr[-300:])
        part.rename(target)
    return {'kind': 'model-pack', 'success': True, 'name': target.name, 'file': str(target), 'size': target.stat().st_size, 'model': model}
