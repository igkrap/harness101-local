"""Pin optional repository-owned workflow capabilities for one native job."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess


@dataclass(frozen=True)
class PolicyAuthority:
    acceptance_id: str
    script_sha256: str
    policy_path: str
    policy_sha256: str


@dataclass(frozen=True)
class WorkflowPolicy:
    enabled: bool = False
    job_created_migration_edits: bool = False
    fixture_owner: str = 'legacy'
    discovery_round_limit: int = 0
    database_scope: str = 'unknown'
    authority: PolicyAuthority | None = None
    reason: str = 'No trusted workflow policy'
    prior_unpublished_migrations: tuple = ()

    def to_manifest(self):
        return asdict(self)


_FIELDS = {'version', 'acceptance_id', 'script_sha256', 'database_scope',
           'job_created_migration_edits', 'fixture_owner', 'discovery_round_limit'}
_MIGRATION_PREFIX = 'backend/src/main/resources/db/migration/'


def live_applied_migration_versions():
    """Read the local production-like DB history, failing closed on any query error."""
    query = 'SELECT version FROM flyway_schema_history WHERE success = true ORDER BY installed_rank'
    command = ['docker', 'exec', 'mdi-db', 'sh', '-c',
               'psql -U "$POSTGRES_USER" -d mdi_local -Atqc "' + query + '"']
    result = subprocess.run(command, capture_output=True, text=True, timeout=5)
    if result.returncode != 0:
        raise ValueError('Live Flyway history query failed')
    versions = result.stdout.splitlines()
    if any(not re.fullmatch(r'[0-9]+(?:\.[0-9]+)*', version) for version in versions):
        raise ValueError('Invalid live Flyway history')
    return frozenset(versions)


def _read_policy(path):
    """Read one bounded regular file, without following any parent symlink."""
    path = Path(path).absolute()
    if '..' in path.parts:
        raise ValueError('Noncanonical workflow policy path')
    handles = []
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        current = os.open(path.anchor, flags)
        handles.append(current)
        for part in path.parts[1:-1]:
            current = os.open(part, flags, dir_fd=current)
            handles.append(current)
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=current)
        handles.append(descriptor)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 8192:
            raise ValueError('Workflow policy must be a small regular file')
        raw = b''
        while len(raw) <= 8192:
            chunk = os.read(descriptor, min(8193 - len(raw), 4096))
            if not chunk:
                break
            raw += chunk
        if len(raw) > 8192:
            raise ValueError('Workflow policy exceeds its size limit')
        return raw
    finally:
        for handle in reversed(handles):
            os.close(handle)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate workflow policy key')
        result[key] = value
    return result


def _binding(runner):
    args = getattr(runner, 'args', None)
    spec = getattr(args, 'fixed_acceptance', None)
    workspace = getattr(getattr(runner, 'h', None), 'workspace', None)
    try:
        encoded = json.dumps(spec, sort_keys=True, ensure_ascii=False, allow_nan=False) if isinstance(spec, dict) else None
    except (TypeError, ValueError):
        encoded = None
    return (getattr(args, 'task', None), str(getattr(workspace, 'root', '')), encoded,
            getattr(args, 'context_profile', 'legacy'), tuple(getattr(runner, 'modes', ()) or ()))


def _load(runner):
    from focused_context import enabled
    if not enabled(runner) or set(getattr(runner, 'modes', ())) != {'backend'}:
        return WorkflowPolicy(reason='Workflow capabilities require focused backend-only execution')
    checker = getattr(getattr(runner, 'h', None), 'checker', None)
    if getattr(checker, 'schema_application_scope', None) != 'fresh-owned':
        return WorkflowPolicy(reason='Backend checker has no fresh-owned schema capability')
    spec = getattr(getattr(runner, 'args', None), 'fixed_acceptance', None)
    if not isinstance(spec, dict):
        return WorkflowPolicy(reason='No caller-selected fixed acceptance')
    try:
        import fixed_acceptance
        spec = fixed_acceptance.validate(spec, runner)
        path = fixed_acceptance.CHECKS_ROOT.parent / 'acceptance/policies' / (spec['id'] + '.json')
        raw = _read_policy(path)
        data = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object)
        if (not isinstance(data, dict) or set(data) not in (_FIELDS, _FIELDS | {'prior_unpublished_migrations'}) or
                type(data['version']) is not int or data['version'] != 1 or
                data['acceptance_id'] != spec['id'] or
                data['script_sha256'] != spec['script_sha256'] or
                data['database_scope'] != 'fresh-owned' or
                type(data['job_created_migration_edits']) is not bool or
                data['fixture_owner'] not in ('legacy', 'checker') or
                type(data['discovery_round_limit']) is not int or
                not 0 <= data['discovery_round_limit'] <= 16):
            raise ValueError('Workflow policy binding or fields mismatch')
        prior = data.get('prior_unpublished_migrations', {})
        if (not isinstance(prior, dict) or len(prior) > 32 or
                (prior and data['job_created_migration_edits'] is not True)):
            raise ValueError('Invalid prior migration policy')
        for migration, digest in prior.items():
            if (not isinstance(migration, str) or not migration.startswith(_MIGRATION_PREFIX) or
                    not re.fullmatch(r'V[0-9]+(?:_[0-9]+)*__[^/]+\.sql', migration[len(_MIGRATION_PREFIX):]) or
                    not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest)):
                raise ValueError('Invalid prior unpublished migration pin')
        if prior:
            applied = live_applied_migration_versions()
            if any(migration[len(_MIGRATION_PREFIX):].split('__', 1)[0][1:].replace('_', '.') in applied
                   for migration in prior):
                raise ValueError('Previously generated migration has been applied to the live database')
        authority = PolicyAuthority(spec['id'], spec['script_sha256'], str(path),
                                    hashlib.sha256(raw).hexdigest())
        return WorkflowPolicy(True, data['job_created_migration_edits'], data['fixture_owner'],
                              data['discovery_round_limit'], 'fresh-owned', authority,
                              'Pinned repository workflow policy', tuple(sorted(prior.items())))
    except (OSError, UnicodeError, ValueError, TypeError, AttributeError, subprocess.TimeoutExpired):
        return WorkflowPolicy(reason='Workflow policy unavailable or invalid')


def get_policy(runner):
    """Keep both missing policies and granted capabilities fixed for this job."""
    binding = _binding(runner)
    cached = getattr(runner, '_trusted_workflow_policy', None)
    if cached is not None:
        if getattr(runner, '_trusted_workflow_binding', None) != binding:
            return WorkflowPolicy(reason='Workflow binding changed after policy capture')
        checker = getattr(getattr(runner, 'h', None), 'checker', None)
        if getattr(checker, 'schema_application_scope', None) != 'fresh-owned':
            return WorkflowPolicy(reason='Backend checker capability changed after policy capture')
        return cached
    policy = _load(runner)
    runner._trusted_workflow_policy = policy
    runner._trusted_workflow_binding = binding
    return policy
