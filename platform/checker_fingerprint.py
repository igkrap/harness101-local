"""Failure evidence belongs to the task and checker definitions that produced it."""
import hashlib
from pathlib import Path


def check_signature(project, runtime, goal):
    project, runtime = Path(project), Path(runtime)
    files = {Path(__file__).with_name('quality.py'), Path(__file__).parent / 'tests/browser_inventory_workflows.cjs'}
    files.update((runtime / 'tests').rglob('*.cjs'))
    for pattern in ('tsconfig*.json', 'eslint.config.*', 'package-lock.json', 'pnpm-lock.yaml', 'yarn.lock'):
        files.update((project / 'frontend').glob(pattern))
    result = hashlib.sha256(goal.encode())
    for file in sorted(files):
        result.update(str(file).encode())
        result.update(file.read_bytes() if file.is_file() else b'ABSENT')
    return result.hexdigest()


def install(project, runtime, goal):
    import failure_memory
    original = failure_memory.FailureMemory._config
    def config(self):
        return hashlib.sha256((original(self) + check_signature(project, runtime, goal)).encode()).hexdigest()
    failure_memory.FailureMemory._config = config
