"""Version history of the managed project (the app the model builds), kept by the platform.

The project has its own git repository, separate from the platform's. Edits made outside a run
(by a person) are committed as a baseline before each agent run, so each successful run becomes
one commit holding exactly the model's change; a live backend deploy is tagged on the commit it shipped.
The harness itself never touches .git (the workspace refuses those paths).
"""
import subprocess
from pathlib import Path

IGNORE = """# managed by the platform (project_git.py)
/harness
node_modules/
dist/
target/
.zvec-grep/
*.tsbuildinfo
*.log
*.env
"""
MODEL_AUTHOR = ('Local model', 'local-model@localhost')
PLATFORM_AUTHOR = ('Platform', 'platform@localhost')
PERSON_AUTHOR = ('사용자', 'user@localhost')


def _git(project, *args, author=None, check=True, raw=False):
    cmd = ['git']
    if not author and args and args[0] in ('commit', 'revert', 'tag') and not subprocess.run(['git', 'config', 'user.name'], cwd=project, capture_output=True, text=True).stdout.strip():
        author = PERSON_AUTHOR       # a machine where git was never told who its user is: the commit must still be made
    if author:
        cmd += ['-c', f'user.name={author[0]}', '-c', f'user.email={author[1]}']
    result = subprocess.run(cmd + list(args), cwd=project, capture_output=True, text=True, timeout=120)
    if check and result.returncode != 0:
        raise RuntimeError(f'git {args[0]} 실패: ' + (result.stderr or result.stdout)[-400:])
    return result.stdout if raw else result.stdout.strip()


def ensure_repo(project):
    """Create the project repository (with its ignore file and a first commit) if it does not exist."""
    project = Path(project)
    if (project / '.git').exists():
        return False
    _git(project, 'init', '-q', '-b', 'main')
    ignore = project / '.gitignore'
    if not ignore.exists():
        ignore.write_text(IGNORE)
    _git(project, 'add', '-A')
    _git(project, 'commit', '-q', '-m', '프로젝트 기준점', author=PLATFORM_AUTHOR)
    return True


def commit(project, message, author=None, only=None):
    """Commit every pending change - or, with `only`, just what changed under those paths (the rest stays pending). Returns the new commit sha, or None when nothing changed."""
    project = Path(project)
    if not (project / '.git').exists():
        return None
    if only:
        _git(project, 'reset', '-q')                      # nothing staged by hand rides along
        _git(project, 'add', '-A', '--', *only)
        if not _git(project, 'diff', '--cached', '--name-only'):
            return None
    else:
        _git(project, 'add', '-A')
        if not _git(project, 'status', '--porcelain'):
            return None
    _git(project, 'commit', '-q', '-m', message, author=author)
    return _git(project, 'rev-parse', 'HEAD')


def head(project):
    return _git(project, 'rev-parse', 'HEAD', check=False) or None


def tag(project, name, message):
    if (Path(project) / '.git').exists():
        _git(project, 'tag', '-a', name, '-m', message, author=PLATFORM_AUTHOR)


def before_run(project, goal):
    """Separate a person's pending edits from the coming run's change."""
    ensure_repo(project)
    return commit(project, '작업 전 변경 사항 (실행 시작 전 기준점)\n\n다음 작업: ' + goal[:200])


def after_run(project, job):
    """One commit per successful run, written by the local model."""
    goal = (job.get('goal') or '').strip()
    title = goal.splitlines()[0][:72] if goal else '모델 작업'
    body = f"요청: {goal[:2000]}\n\n작업 ID: {job['id']}\n모델: {job.get('model', '')}"
    queue = job.get('queue') or {}
    if queue.get('id'):
        body += f"\n작업 큐: {queue['id']} ({queue.get('index', 0) + 1}/{queue.get('total', '?')}) {queue.get('goal', '')[:200]}"
    return commit(project, title + '\n\n' + body, author=(f"{MODEL_AUTHOR[0]} ({job.get('model', '')})".strip(), MODEL_AUTHOR[1]))


# ---- version control as a platform feature (the 형상 관리 page) ----

import re

_SEP, _END = '\x1f', '\x1e'
BRANCH_NAME = re.compile(r'[A-Za-z0-9가-힣][A-Za-z0-9가-힣._/-]{0,60}')
SHA = re.compile(r'[0-9a-f]{7,40}')
MAX_TEXT = 400_000


def _require_repo(project):
    if not (Path(project) / '.git').exists():
        raise ValueError('이 프로젝트에는 아직 형상 관리 저장소가 없습니다. 첫 작업을 실행하면 자동으로 만들어집니다.')


def _sha(project, sha):
    if not isinstance(sha, str) or not SHA.fullmatch(sha):
        raise ValueError('커밋 ID가 올바르지 않습니다.')
    full = _git(project, 'rev-parse', '--verify', '--quiet', sha + '^{commit}', check=False)
    if not full:
        raise ValueError('커밋을 찾을 수 없습니다.')
    return full


def _require_clean(project, action):
    if _git(project, 'status', '--porcelain'):
        raise RuntimeError(f'커밋하지 않은 변경이 있어 {action}할 수 없습니다. 먼저 커밋하세요.')


def _kind(author):
    return 'model' if author.startswith(MODEL_AUTHOR[0]) else 'platform' if author == PLATFORM_AUTHOR[0] else 'person'


def status(project):
    _require_repo(project)
    branch = _git(project, 'branch', '--show-current')
    branches = [b for b in _git(project, 'branch', '--format=%(refname:short)').splitlines() if b]
    dirty = []
    for line in _git(project, 'status', '--porcelain', '-uall').splitlines():
        code, path = line.split(None, 1)          # (the output comes trimmed: the first line may have lost the space its code starts with)
        path = path.split(' -> ')[-1].strip('"')
        dirty.append({'path': path, 'status': 'added' if '?' in code or 'A' in code else 'deleted' if 'D' in code else 'modified'})
    remote = _git(project, 'remote', 'get-url', 'origin', check=False)
    ahead = None
    if remote and branch:
        counts = _git(project, 'rev-list', '--count', f'origin/{branch}..HEAD', check=False)
        ahead = int(counts) if counts.isdigit() else None
    return {'branch': branch, 'branches': branches, 'head': head(project), 'dirty': dirty, 'remote': remote or '', 'ahead': ahead}


HISTORY_START = 'refs/platform/history-start'


def set_history_start(project, ref='HEAD'):
    """Hide everything up to and including ref from the change history list (nothing is deleted). ref=None clears it."""
    _require_repo(project)
    if ref is None:
        _git(project, 'update-ref', '-d', HISTORY_START, check=False)
        return None
    sha = _sha(project, ref)
    _git(project, 'update-ref', HISTORY_START, sha)
    return sha


def history(project, limit=60, ref=None):
    _require_repo(project)
    limit = max(1, min(int(limit or 60), 200))
    fmt = _SEP.join(['%H', '%h', '%an', '%aI', '%s', '%b', '%D']) + _END
    args = ['log', f'--format={fmt}', '-n', str(limit)]
    # The list starts after the marker commit when one is set (set_history_start): earlier commits stay in the
    # repository and can still be reached by tag or sha, they are just not listed.
    start = _git(project, 'rev-parse', '--verify', '--quiet', HISTORY_START, check=False).strip()
    tip = _sha(project, ref) + '^' if ref else 'HEAD'
    args.append(f'{start}..{tip}' if start else tip)
    out = _git(project, *args, check=False, raw=True)  # str.strip() would eat the \x1e/\x1f separators
    commits = []
    for record in out.split(_END):
        parts = record.strip('\n').split(_SEP)
        if len(parts) != 7:
            continue
        sha, short, author, date, subject, body, refs = parts
        job = re.search(r'작업 ID: ([0-9a-f]{32})', body)
        tags = [r.strip()[5:] for r in refs.split(',') if r.strip().startswith('tag: ')]
        commits.append({'sha': sha, 'short': short, 'author': author, 'kind': _kind(author), 'date': date,
                        'subject': subject, 'body': body.strip()[:2000], 'job_id': job.group(1) if job else None, 'tags': tags})
    return commits


def _numstat(project, *args):
    stats = {}
    for line in _git(project, *args, '--numstat', check=False).splitlines():
        parts = line.split('\t')
        if len(parts) == 3:
            stats[parts[2]] = (int(parts[0]) if parts[0].isdigit() else 0, int(parts[1]) if parts[1].isdigit() else 0)
    return stats


def commit_files(project, sha):
    _require_repo(project)
    sha = _sha(project, sha)
    names = _git(project, 'show', '--format=', '--name-status', '--root', sha).splitlines()
    stats = _numstat(project, 'show', '--format=', '--root', sha)
    files = []
    for line in names:
        parts = line.split('\t')
        if len(parts) < 2:
            continue
        path = parts[-1]
        added, removed = stats.get(path, (0, 0))
        files.append({'path': path, 'status': {'A': 'added', 'D': 'deleted'}.get(parts[0][0], 'modified'), 'added': added, 'removed': removed})
    return files


def _blob(project, rev, path):
    result = subprocess.run(['git', 'show', f'{rev}:{path}'], cwd=project, capture_output=True, timeout=60)
    return result.stdout[:MAX_TEXT].decode('utf-8', 'replace') if result.returncode == 0 else ''


def _safe_rel(path):
    if not isinstance(path, str) or not path or path.startswith('/') or '..' in Path(path).parts or '.git' in Path(path).parts:
        raise ValueError('파일 경로가 올바르지 않습니다.')
    return path


def commit_file(project, sha, path):
    sha, path = _sha(project, sha), _safe_rel(path)
    parent = _git(project, 'rev-parse', '--verify', '--quiet', sha + '^', check=False)
    return {'path': path, 'before': _blob(project, parent, path) if parent else '', 'after': _blob(project, sha, path)}


def working_files(project):
    _require_repo(project)
    stats = _numstat(project, 'diff', 'HEAD')
    files = []
    for item in status(project)['dirty']:
        added, removed = stats.get(item['path'], (0, 0))
        if item['status'] == 'added' and not added:
            try:
                added = len((Path(project) / item['path']).read_text(encoding='utf-8', errors='replace').splitlines())
            except OSError:
                pass
        files.append({**item, 'added': added, 'removed': removed})
    return files


def working_file(project, path):
    path = _safe_rel(path)
    target = Path(project) / path
    after = target.read_bytes()[:MAX_TEXT].decode('utf-8', 'replace') if target.is_file() else ''
    return {'path': path, 'before': _blob(project, 'HEAD', path), 'after': after}


def commit_now(project, message):
    _require_repo(project)
    message = (message or '').strip()
    if not 1 <= len(message) <= 2000:
        raise ValueError('커밋 메시지를 입력하세요.')
    sha = commit(project, message)
    if not sha:
        raise ValueError('커밋할 변경이 없습니다.')
    return sha


def revert(project, sha):
    _require_repo(project)
    sha = _sha(project, sha)
    _require_clean(project, '되돌리기')
    result = subprocess.run(['git', 'revert', '--no-commit', sha], cwd=project, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        subprocess.run(['git', 'revert', '--abort'], cwd=project, capture_output=True)
        raise RuntimeError('이후 변경과 겹치는 부분이 있어 자동으로 취소할 수 없습니다. AI에게 "그 변경을 되돌려줘"라고 요청해 보세요.')
    subject = _git(project, 'log', '-1', '--format=%s', sha)
    _git(project, 'commit', '-q', '-m', f'취소: {subject}\n\n취소한 기록: {sha}')
    return head(project)


def switch(project, name, create=False):
    _require_repo(project)
    if not isinstance(name, str) or not BRANCH_NAME.fullmatch(name) or '..' in name or name.endswith(('/', '.lock')):
        raise ValueError('브랜치 이름이 올바르지 않습니다.')
    _require_clean(project, '브랜치를 바꿀')
    _git(project, 'switch', *(['-c'] if create else []), name)
    return status(project)


def push(project):
    st = status(project)
    if not st['remote']:
        raise ValueError('원격 저장소(origin)가 설정되어 있지 않습니다.')
    result = subprocess.run(['git', 'push', '-u', 'origin', st['branch']], cwd=project, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError('push 실패: ' + (result.stderr or result.stdout)[-400:])
    return status(project)
