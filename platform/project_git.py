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


def _git(project, *args, author=None, check=True):
    cmd = ['git']
    if author:
        cmd += ['-c', f'user.name={author[0]}', '-c', f'user.email={author[1]}']
    result = subprocess.run(cmd + list(args), cwd=project, capture_output=True, text=True, timeout=120)
    if check and result.returncode != 0:
        raise RuntimeError(f'git {args[0]} 실패: ' + (result.stderr or result.stdout)[-400:])
    return result.stdout.strip()


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


def commit(project, message, author=None):
    """Commit every pending change; returns the new commit sha, or None when nothing changed."""
    project = Path(project)
    if not (project / '.git').exists():
        return None
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
