"""Capture editable model-created sources from explicitly approved successful trials.

The caller supplies a complete supervisor source snapshot and approved artifact
records. Neither membership checks nor manifest serialization reread metadata.
"""
import base64
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from types import MappingProxyType
from typing import Mapping

METADATA_FILES = ('result.json', 'manifest.json', 'generated-sources.json', 'restore-snapshot.json')
POLICY = 'approved-generated-source-lineage-v1'
MAX_METADATA_BYTES = 32 * 1024 * 1024
MAX_SOURCES = 4096


def live_applied_migration_versions():
    query = 'SELECT version FROM flyway_schema_history WHERE success = true ORDER BY installed_rank'
    result = subprocess.run(['docker', 'exec', 'mdi-db', 'sh', '-c',
                             'psql -U "$POSTGRES_USER" -d mdi_local -Atqc "' + query + '"'],
                            capture_output=True, text=True, timeout=5)
    if result.returncode != 0:
        raise OwnershipError('Live Flyway history query failed')
    versions = result.stdout.splitlines()
    if any(not re.fullmatch(r'[0-9]+(?:\.[0-9]+)*', version) for version in versions):
        raise OwnershipError('Invalid live Flyway history')
    return frozenset(versions)


class OwnershipError(ValueError):
    pass


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value):
        raise OwnershipError('Invalid SHA-256 value')
    return value


def _path(value):
    if (not isinstance(value, str) or not value or '\\' in value or ':' in value or
            any(ord(character) < 32 for character in value)):
        raise OwnershipError('Invalid source path')
    path = PurePosixPath(value)
    if (path.is_absolute() or '..' in path.parts or path.as_posix() != value or
            len(path.parts) < 2 or path.parts[0] not in ('frontend', 'backend')):
        raise OwnershipError('Source path must be a canonical project-relative path')
    return value


def _plain_path(path):
    path = Path(path).absolute()
    if '..' in path.parts:
        raise OwnershipError('Noncanonical filesystem path')
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.is_symlink():
            raise OwnershipError('Symlink paths cannot provide ownership evidence')
    return path


def _read_regular(path):
    path = _plain_path(path)
    if not path.is_file():
        raise OwnershipError('Required regular evidence/source file is missing')
    if path.stat().st_nlink != 1:
        raise OwnershipError('Hard-linked evidence/source paths are not allowed')
    if path.stat().st_size > MAX_METADATA_BYTES:
        raise OwnershipError('Evidence/source file exceeds the ownership size bound')
    return path.read_bytes()


def _unique_object(pairs):
    output = {}
    for key, value in pairs:
        if key in output:
            raise OwnershipError('Duplicate JSON key in ownership evidence')
        output[key] = value
    return output


def _json(raw):
    try:
        data = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise OwnershipError('Malformed ownership evidence JSON') from error
    if not isinstance(data, dict):
        raise OwnershipError('Ownership evidence must be a JSON object')
    return data


def _source_map(data, encoded=False):
    if not isinstance(data, dict) or len(data) > MAX_SOURCES:
        raise OwnershipError('Invalid ownership source map')
    output = {}
    for path, value in data.items():
        path = _path(path)
        if encoded:
            if not isinstance(value, str):
                raise OwnershipError('Generated/snapshot source must be base64 text')
            try:
                output[path] = _sha(base64.b64decode(value, validate=True))
            except (ValueError, TypeError) as error:
                raise OwnershipError('Invalid base64 source evidence') from error
        else:
            output[path] = _digest(value)
    return output


def _migration(path):
    return path.startswith('backend/src/main/resources/db/migration/') and path.endswith('.sql')


def _migration_version(path):
    if not _migration(path):
        return None
    name = PurePosixPath(path).name
    matched = re.fullmatch(r'V([0-9]+(?:_[0-9]+)*)__[^/]+\.sql', name)
    return matched.group(1).replace('_', '.') if matched else None


def _editable(path):
    return ((path.startswith('backend/src/main/java/') and path.endswith('.java')) or
            (path.startswith('frontend/src/') and not path.startswith('frontend/src/framework/') and
             path.endswith(('.ts', '.tsx')) and not path.endswith('.d.ts')))


@dataclass(frozen=True)
class ApprovedSuccess:
    directory: Path
    metadata_sha256: tuple

    @classmethod
    def pin(cls, evidence_dir):
        directory = _plain_path(evidence_dir)
        if not directory.is_dir():
            raise OwnershipError('Approved success directory is missing')
        return cls(directory, tuple((name, _sha(_read_regular(directory / name))) for name in METADATA_FILES))


@dataclass(frozen=True)
class SuccessProvenance:
    directory: str
    job_id: str
    model: str
    metadata_sha256: tuple


@dataclass(frozen=True)
class OwnershipSnapshot:
    editable_existing: frozenset
    expected_sha256: Mapping[str, str]
    provenance: tuple
    foundation_file_count: int
    source_file_count: int
    unpublished_migrations: Mapping[str, str]

    def allows_existing(self, path):
        return isinstance(path, str) and path in self.editable_existing

    def to_manifest(self):
        return {'policy': POLICY, 'editable_existing': sorted(self.editable_existing),
                'expected_sha256': dict(self.expected_sha256),
                'foundation_file_count': self.foundation_file_count, 'source_file_count': self.source_file_count,
                'unpublished_migrations': dict(self.unpublished_migrations),
                'approved_successes': [{'evidence': proof.directory, 'job_id': proof.job_id, 'model': proof.model,
                                        'metadata_sha256': dict(proof.metadata_sha256)} for proof in self.provenance]}


def _verified_artifact(approval):
    if not isinstance(approval, ApprovedSuccess):
        raise OwnershipError('Only explicitly pinned ApprovedSuccess records are accepted')
    directory = _plain_path(approval.directory)
    pins = dict(approval.metadata_sha256)
    if len(approval.metadata_sha256) != len(METADATA_FILES) or set(pins) != set(METADATA_FILES):
        raise OwnershipError('Incomplete or duplicated artifact SHA pins')
    records = {}
    for name in METADATA_FILES:
        raw = _read_regular(directory / name)
        if _sha(raw) != _digest(pins[name]):
            raise OwnershipError('Approved artifact SHA pin changed: ' + name)
        records[name] = _json(raw)
    result, manifest = records['result.json'], records['manifest.json']
    required = ('success', 'candidate_retained', 'workspace_verified', 'cleanup_ok', 'scope_respected',
                'frozen_unchanged', 'sources_stable_during_final_checks', 'build_passed', 'browser_passed',
                'prior_state_restored', 'result_written')
    if result.get('status') != 'succeeded' or any(result.get(key) is not True for key in required):
        raise OwnershipError('Artifact is not a retained, verified successful trial')
    if result.get('baseline_restored') is not False or result.get('restore_errors') != [] or result.get('evidence_errors') != []:
        raise OwnershipError('Success artifact has incomplete restoration/evidence status')
    if result.get('evidence') != str(directory):
        raise OwnershipError('Artifact evidence directory does not match its approval')
    for record in (result, manifest):
        if type(record.get('manual_interventions_after_start')) is not int or record['manual_interventions_after_start'] != 0:
            raise OwnershipError('Intervened artifacts cannot grant model ownership')
    if type(result.get('model_calls')) is not int or result['model_calls'] < 1:
        raise OwnershipError('Success artifact has no recorded model execution')
    cases = result.get('oracle_cases')
    if not isinstance(cases, list) or not cases or any(not isinstance(case, str) for case in cases) or len(set(cases)) != len(cases):
        raise OwnershipError('Success oracle cases are missing or duplicated')
    job_id = result.get('job_id')
    cleanup = result.get('cleanup_job', {})
    if (not isinstance(cleanup, dict) or not isinstance(job_id, str) or not job_id or cleanup.get('job_id') != job_id or
            cleanup.get('status') != 'succeeded' or
            cleanup.get('safe_to_restore') is not True or cleanup.get('process_or_group_alive') is not False):
        raise OwnershipError('Success job identity/termination proof is inconsistent')
    oracle_cleanup, runtime_cleanup = result.get('oracle_cleanup'), result.get('isolated_runtime_cleanup')
    if (not isinstance(oracle_cleanup, dict) or oracle_cleanup.get('success') is not True or
            oracle_cleanup.get('errors', []) != [] or not isinstance(runtime_cleanup, list) or any(
                not isinstance(record, dict) or record.get('success') is not True or record.get('errors', []) != []
                for record in runtime_cleanup)):
        raise OwnershipError('Successful verification resources were not cleaned up')
    config, launched, request = manifest.get('model_config', {}), manifest.get('launched_model', {}), manifest.get('request', {})
    if (not all(isinstance(record, dict) for record in (config, launched, request)) or
            any(not isinstance(config.get(key), str) or not config[key] for key in ('id', 'model', 'url')) or
            result.get('model_config_id') != config['id'] or result.get('model') != config['model'] or
            request.get('kind') != 'agent' or request.get('model') != 'config:' + config['id'] or
            launched.get('model_config') != config or launched.get('model') != config['model'] or
            launched.get('llm_url') != config.get('url')):
        raise OwnershipError('Success model identity/configuration is inconsistent')
    before = _source_map(manifest.get('sources_before'))
    if before != _source_map(records['restore-snapshot.json'], encoded=True):
        raise OwnershipError('Before-source hashes do not match the restoration snapshot')
    generated = _source_map(records['generated-sources.json'], encoded=True)
    changed = result.get('changed_paths')
    if (not isinstance(changed, list) or any(not isinstance(path, str) for path in changed) or
            len(changed) != len(set(changed)) or set(changed) != set(generated)):
        raise OwnershipError('Changed/generated paths differ; deletions are not ownership grants')
    if not generated or any(before.get(path) == digest for path, digest in generated.items()):
        raise OwnershipError('Success artifact contains no-op generated source evidence')
    return before, generated, SuccessProvenance(str(directory), job_id, config['model'],
                                               tuple((name, pins[name]) for name in METADATA_FILES))


def _live_source_map(app_root):
    root = _plain_path(app_root)
    output, identities = {}, set()
    for name in ('frontend', 'backend'):
        directory = _plain_path(root / name)
        if not directory.is_dir():
            raise OwnershipError('Project source root is missing')
        for path in [*directory.iterdir(), *(directory / 'src').rglob('*')]:
            path = _plain_path(path)
            if not path.is_file():
                continue
            identity = (path.stat().st_dev, path.stat().st_ino)
            if identity in identities or path.stat().st_nlink != 1:
                raise OwnershipError('Aliased or hard-linked source paths are not allowed')
            identities.add(identity)
            output[_path(path.relative_to(root).as_posix())] = _sha(_read_regular(path))
    return output


def capture_owned_sources(app_root, before_sources, approved_successes, applied_migration_versions=None):
    """Validate the approved chain once and return an immutable permission capture."""
    if not isinstance(before_sources, Mapping) or len(before_sources) > MAX_SOURCES or not approved_successes:
        raise OwnershipError('A complete source snapshot and explicit success approvals are required')
    current = {}
    for path, raw in before_sources.items():
        if not isinstance(raw, bytes):
            raise OwnershipError('Current-source snapshot values must be bytes')
        current[_path(path)] = _sha(raw)
    if applied_migration_versions is not None and (not isinstance(applied_migration_versions, (set, frozenset)) or
            any(not isinstance(version, str) or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)*', version)
                for version in applied_migration_versions)):
        raise OwnershipError('Applied migration versions need a trusted live database set')
    state, foundation, owned, provenance, jobs = None, set(), {}, [], set()
    for approval in tuple(approved_successes):
        before, generated, proof = _verified_artifact(approval)
        if proof.job_id in jobs:
            raise OwnershipError('Duplicate successful job in approved lineage')
        jobs.add(proof.job_id)
        if state is None:
            state, foundation = dict(before), set(before)
        elif state != before:
            raise OwnershipError('Approved success before-source chain does not match')
        for path, digest in generated.items():
            if path in foundation:
                raise OwnershipError('Foundation sources cannot be promoted to model ownership')
            if path in before and path not in owned:
                raise OwnershipError('Existing unowned sources cannot be edited by lineage')
            owned[path] = digest
        state.update(generated)
        provenance.append(proof)
    if state != current or _live_source_map(app_root) != current:
        raise OwnershipError('Launch baseline does not exactly match the final approved success')
    unpublished = {path: owned[path] for path in owned if _migration(path) and
                   applied_migration_versions is not None and
                   _migration_version(path) is not None and
                   _migration_version(path) not in applied_migration_versions}
    editable = frozenset(path for path in owned if _editable(path) or path in unpublished)
    expected = MappingProxyType({path: owned[path] for path in sorted(editable)})
    return OwnershipSnapshot(editable, expected, tuple(provenance), len(foundation), len(state),
                             MappingProxyType(dict(sorted(unpublished.items()))))
