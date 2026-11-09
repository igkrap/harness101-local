"""Bounded trial cleanup independent of evidence-file availability."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import time


MIN_FREE_BYTES = 2 * 1024 ** 3
TERMINAL_STATUSES = frozenset(('succeeded', 'failed', 'stopped'))


def require_free_space(path, minimum=MIN_FREE_BYTES):
    free = shutil.disk_usage(path).free
    if free < minimum:
        raise OSError('Trial requires at least %d free bytes; available %d' % (minimum, free))
    return free


def atomic_write(path, data):
    """Leave the previous file intact if allocation or writing fails."""
    path = Path(path)
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '-', dir=str(path.parent))
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            os.chmod(temporary, path.stat().st_mode & 0o777)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            try:
                Path(temporary).unlink(missing_ok=True)
            except OSError:
                pass


class TrialEvidence:
    def __init__(self, output):
        self.output = Path(output)
        self.reserve = self.output / '.cleanup-reserve'
        self.errors = []

    def error(self, stage, exc):
        # A full disk must not cause an unbounded in-memory error journal either.
        if len(self.errors) < 40:
            self.errors.append({'stage': stage, 'error': str(exc)[:2000]})

    def arm_reserve(self, size=16 * 1024 ** 2):
        # Actual blocks, not a sparse truncate: available to stop/save/restore later.
        with self.reserve.open('xb') as stream:
            chunk = bytes(1024 ** 2)
            while size:
                amount = min(size, len(chunk))
                stream.write(chunk[:amount])
                size -= amount
            stream.flush()
            os.fsync(stream.fileno())

    def release_reserve(self):
        try:
            self.reserve.unlink(missing_ok=True)
        except OSError as exc:
            self.error('release_reserve', exc)

    def text(self, path, value):
        try:
            atomic_write(path, value.encode('utf-8'))
            return True
        except (OSError, ValueError) as exc:
            self.error('write:' + str(path), exc)
            return False

    def json(self, path, value):
        try:
            serialized = json.dumps(value, ensure_ascii=False, indent=2)
        except (TypeError, ValueError) as exc:
            self.error('serialize:' + str(path), exc)
            return False
        return self.text(path, serialized)


def process_or_group_alive(pid):
    """Only signal 0; never terminate a PID guessed from persisted metadata."""
    if type(pid) is not int or pid <= 1:
        return None
    for probe in (os.kill, os.killpg):
        try:
            probe(pid, 0)
            return True
        except ProcessLookupError:
            continue
        except OSError:
            return None
    return False


def stop_and_confirm(job_id, read_job, stop_job, timeout=85, interval=2,
                     probe=process_or_group_alive, clock=time.monotonic, sleep=time.sleep):
    """A successful stop request is not proof that the writer has exited."""
    deadline = clock() + timeout
    report = {'job_id': job_id, 'safe_to_restore': False}
    requested = False
    while True:
        try:
            current = read_job(job_id)
            report['status'] = current.get('status')
            alive = probe(current.get('pid'))
            report['process_or_group_alive'] = alive
            if (current.get('id') == job_id and current.get('status') in TERMINAL_STATUSES
                    and type(current.get('exit_code')) is int and current.get('finished_at')
                    and alive is False):
                report['safe_to_restore'] = True
                return report
        except Exception as exc:
            report['read_error'] = str(exc)[:2000]
        if not requested:
            requested = True
            try:
                stop_job(job_id)
                report['stop_requested'] = True
            except Exception as exc:
                report['stop_error'] = str(exc)[:2000]
        remaining = deadline - clock()
        if remaining <= 0:
            report['blocked'] = 'Native job termination is unproven; no source restoration attempted'
            return report
        sleep(min(interval, remaining))


def restore_snapshot(app, before, prior, collect):
    """Try every original file and prior-state file even if one write fails."""
    app = Path(app)
    errors = []
    try:
        added = set(collect()) - set(before)
    except Exception as exc:
        added = set()
        errors.append('list sources: ' + str(exc))
    for rel in sorted(added):
        try:
            (app / rel).unlink()
        except OSError as exc:
            errors.append('remove %s: %s' % (rel, exc))
    for path, raw in [(app / rel, raw) for rel, raw in before.items()] + list(prior.items()):
        path = Path(path)
        try:
            if raw is None:
                path.unlink(missing_ok=True)
            elif not path.exists() or path.read_bytes() != raw:
                path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write(path, raw)
        except OSError as exc:
            errors.append('restore %s: %s' % (path, exc))
    try:
        sources_ok = collect() == before
        prior_ok = all((not Path(path).exists()) if raw is None else
                       Path(path).read_bytes() == raw for path, raw in prior.items())
    except OSError as exc:
        sources_ok = prior_ok = False
        errors.append('verify restoration: ' + str(exc))
    return {'completed_sources_restored': sources_ok, 'prior_state_restored': prior_ok,
            'restored_file_count': len(before) if sources_ok else 0, 'restore_errors': errors}


def cleanup_trial(evidence, job_id, launch_attempted, read_job, stop_job, restore, **stop_options):
    """No logging or evidence write may precede critical cleanup."""
    evidence.release_reserve()
    result = {'completed_sources_restored': False, 'prior_state_restored': False}
    if job_id is None and launch_attempted:
        result['restore_blocked'] = 'Launch outcome is unknown; native job identity must be reconciled'
        return result
    if job_id is not None:
        stopped = stop_and_confirm(job_id, read_job, stop_job, **stop_options)
        result['cleanup_job'] = stopped
        if not stopped['safe_to_restore']:
            result['restore_blocked'] = stopped['blocked']
            return result
    try:
        result.update(restore())
    except Exception as exc:
        result['restore_error'] = str(exc)[:2000]
    return result
