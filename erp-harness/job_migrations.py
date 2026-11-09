"""Narrow edit authority for this job's unpublished, isolated-only migrations.

The caller supplies trusted workflow and checker capabilities, calls require_edit
before a mutation, and records only successful model writes. Checkpoint commits
do not publish migrations; this ledger expires with the Runner that owns it.
"""
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import stat


_MIGRATIONS = 'backend/src/main/resources/db/migration/'


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _canonical(path):
    if not isinstance(path, str) or not path or '\\' in path or '\x00' in path:
        raise ValueError('Migration path must be canonical and project-relative')
    parts = path.split('/')
    if any(part in ('', '.', '..') for part in parts) or PurePosixPath(path).is_absolute():
        raise ValueError('Migration path must be canonical and project-relative')
    return path


@dataclass(frozen=True)
class _Owned:
    sha256: str
    identity: tuple


class JobMigrationProvenance:
    @classmethod
    def capture(cls, workspace, enabled=False, fresh_backend_checks=False, prior_unpublished=None):
        return cls(workspace, enabled is True and fresh_backend_checks is True,
                   prior_unpublished or {})

    def __init__(self, workspace, enabled, prior_unpublished):
        root = Path(workspace.root)
        if not root.is_absolute() or root != root.resolve(strict=True):
            raise ValueError('Migration workspace must have a canonical root')
        self._root = root
        self._enabled = enabled
        self._baseline_paths = frozenset()
        self._baseline_identities = frozenset()
        self._protected_identities = frozenset()
        self._approved_baseline = frozenset()
        self._approved_initial_identities = {}
        self._accepted = {}
        self._pending = {}
        self._authorized = {}
        if not isinstance(prior_unpublished, dict) or (prior_unpublished and not enabled):
            raise ValueError('Prior migration authority needs an enabled trusted backend workflow')
        if enabled:
            paths, identities = set(), set()
            directory = self._target(_MIGRATIONS.rstrip('/'))
            if directory.exists():
                if not directory.is_dir():
                    raise ValueError('Migration directory is not a directory')
                for folder, directories, filenames in os.walk(directory, followlinks=False):
                    for name in directories:
                        self._target(str((Path(folder) / name).relative_to(root)))
                    for name in filenames:
                        if not name.endswith('.sql'):
                            continue
                        relative = str((Path(folder) / name).relative_to(root))
                        target = self._target(relative)
                        info = target.lstat()
                        if not stat.S_ISREG(info.st_mode):
                            raise ValueError('Baseline migration must be a regular file')
                        paths.add(relative)
                        identities.add((info.st_dev, info.st_ino))
            self._baseline_paths = frozenset(paths)
            self._baseline_identities = frozenset(identities)
            approved = set()
            protected = set(identities)
            for path, digest in prior_unpublished.items():
                if (not isinstance(path, str) or not path.startswith(_MIGRATIONS) or not path.endswith('.sql') or
                        not isinstance(digest, str) or len(digest) != 64 or
                        any(char not in '0123456789abcdef' for char in digest) or path not in paths):
                    raise ValueError('Invalid prior unpublished migration authority')
                _, observed = self._observe(path)
                if observed.sha256 != digest:
                    raise ValueError('Prior unpublished migration SHA does not match current source')
                approved.add(path)
                protected.discard(observed.identity)
                self._approved_initial_identities[observed.identity] = path
                self._accepted[path] = observed
            self._approved_baseline = frozenset(approved)
            self._protected_identities = frozenset(protected)

    @property
    def enabled(self):
        return self._enabled

    def _target(self, path):
        path = _canonical(path)
        target = self._root
        for part in path.split('/'):
            target = target / part
            if target.is_symlink():
                raise ValueError('Migration symlinks are forbidden')
        if target.resolve() != target:
            raise ValueError('Migration path escapes its canonical workspace path')
        return target

    def _observe(self, path):
        target = self._target(path)
        info = target.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('Migration must be a regular file without hard links')
        descriptor = os.open(target, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(descriptor, 'rb') as stream:
            opened = os.fstat(stream.fileno())
            identity = (opened.st_dev, opened.st_ino)
            if identity != (info.st_dev, info.st_ino) or not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                raise ValueError('Migration identity changed while reading')
            data = stream.read()
        after = self._target(path).lstat()
        if (identity != (after.st_dev, after.st_ino) or after.st_nlink != 1 or
                not stat.S_ISREG(after.st_mode) or
                (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) !=
                (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise ValueError('Migration identity changed while reading')
        return data, _Owned(_digest(data), identity)

    def _not_baseline(self, path, observed):
        if ((path in self._baseline_paths and path not in self._approved_baseline) or
                observed.identity in self._protected_identities or
                (observed.identity in self._approved_initial_identities and
                 self._approved_initial_identities[observed.identity] != path) or
                any(other != path and owned.identity == observed.identity for other, owned in self._accepted.items())):
            raise ValueError('Job-start Flyway migrations are immutable')

    def _forget(self, path):
        self._accepted.pop(path, None)
        self._pending.pop(path, None)
        self._authorized.pop(path, None)

    def require_edit(self, path, current_bytes, fully_read_sha256, operation):
        """Authorize one write/edit using an exact current full-source read SHA."""
        path = _canonical(path)
        if not self._enabled or not path.startswith(_MIGRATIONS) or not path.endswith('.sql'):
            raise ValueError('Existing Flyway migrations are immutable without fresh-owned workflow authority')
        if operation not in ('write_file', 'edit_file'):
            raise ValueError('Job-created migrations may be written or edited, never deleted')
        if path in self._baseline_paths and path not in self._approved_baseline:
            raise ValueError('Job-start Flyway migrations are immutable')
        expected = self._pending.get(path, self._accepted.get(path))
        try:
            actual, observed = self._observe(path)
            self._not_baseline(path, observed)
            if expected is None or observed != expected:
                self._forget(path)
                raise ValueError('Migration is not a current, model-created file owned by this job')
        except (OSError, ValueError):
            self._forget(path)
            raise
        if not isinstance(current_bytes, bytes) or actual != current_bytes or fully_read_sha256 != observed.sha256:
            raise ValueError('Read the complete current migration before editing; source SHA must match')
        self._authorized[path] = observed

    def record_write(self, path, before_bytes, after_bytes):
        """Record an actual successful model write after the checkpoint records it.

        Ordinary files are ignored. A present migration needs require_edit first;
        an absent migration is admitted only from an actual before=None creation.
        """
        path = _canonical(path)
        if not self._enabled or not path.startswith(_MIGRATIONS) or not path.endswith('.sql'):
            return
        if not isinstance(after_bytes, bytes):
            raise ValueError('Deleting job-created migrations is forbidden')
        actual, observed = self._observe(path)
        self._not_baseline(path, observed)
        if actual != after_bytes:
            raise ValueError('Migration write result does not match the actual file')
        expected = self._pending.get(path, self._accepted.get(path))
        if before_bytes is None:
            if expected is not None:
                raise ValueError('An owned migration disappeared before this write')
        else:
            authorized = self._authorized.pop(path, None)
            if not isinstance(before_bytes, bytes) or expected is None or authorized != expected or _digest(before_bytes) != expected.sha256:
                raise ValueError('Existing migration write has no matching full-read authorization')
        self._pending[path] = observed

    def wrap_checkpoint(self, checkpoint):
        if isinstance(checkpoint, _CheckpointObserver):
            if checkpoint._owner is not self:
                raise ValueError('Checkpoint already belongs to another migration ledger')
            return checkpoint
        if Path(checkpoint.workspace.root) != self._root:
            raise ValueError('Checkpoint workspace does not match migration ledger')
        return _CheckpointObserver(checkpoint, self)

    def _commit(self, checkpoint):
        for path, expected in list(self._pending.items()):
            try:
                _, observed = self._observe(path)
                self._not_baseline(path, observed)
                if observed != expected:
                    raise ValueError('Migration changed before checkpoint commit')
            except (OSError, ValueError):
                self._forget(path)
                raise
        result = checkpoint.commit()
        self._accepted.update(self._pending)
        self._pending.clear()
        self._authorized.clear()
        return result

    def _rollback(self, checkpoint):
        # A tool may fail after changing bytes, before record_write is called.
        # Its successful checkpoint rollback must also rebind an accepted inode.
        pending = set(self._pending) | (set(self._accepted) & set(checkpoint._records))
        try:
            result = checkpoint.rollback()
        except BaseException:
            for path in pending:
                self._forget(path)
            self._authorized.clear()
            raise
        for path in pending:
            accepted = self._accepted.get(path)
            self._pending.pop(path, None)
            if accepted is None or path not in result:
                self._forget(path)
                continue
            try:
                _, observed = self._observe(path)
                self._not_baseline(path, observed)
                if observed.sha256 != accepted.sha256:
                    raise ValueError('Rollback did not restore accepted migration bytes')
                # Checkpoint rollback atomically replaces the file, so its inode
                # changes. Only a successful observed rollback may rebind it.
                self._accepted[path] = observed
            except (OSError, ValueError):
                self._forget(path)
        self._authorized.clear()
        return result


class _CheckpointObserver:
    def __init__(self, checkpoint, owner):
        self._checkpoint = checkpoint
        self._owner = owner

    def __getattr__(self, name):
        return getattr(self._checkpoint, name)

    def commit(self):
        return self._owner._commit(self._checkpoint)

    def rollback(self):
        return self._owner._rollback(self._checkpoint)
