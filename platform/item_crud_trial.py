"""One frozen local-model CRUD trial. Reset failures; retain verified success."""
import base64
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import signal
import stat
import subprocess
import sys
import time
import traceback
import urllib.request

from ast_candidate_buffer import CandidateStore
from fixed_acceptance_registry import load_fixed_acceptance
from trial_safety import TrialEvidence, cleanup_trial, require_free_space, restore_snapshot, stop_and_confirm

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / 'local-only'
STATE = ROOT / 'platform/state'
TARGET = 'frontend/src/screens/ItemMaster.tsx'
MIGRATION = 'backend/src/main/resources/db/migration/V6__create_items.sql'
JAVA_ROOT = 'backend/src/main/java/com/example/localinventory/items/'
ACCEPTANCE = 'item-master-crud-v1'
ORACLE = ROOT / 'platform/tests/browser_gemma_item_crud.cjs'
MAX_CALLS, WALL_SECONDS = 48, 1800
THINKING = True
API = 'http://127.0.0.1:5293'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def select_model_config(registry, stage):
    """Pin the selected/default registered configuration for this trial."""
    identifier = stage.get('model_config') or registry.get('default')
    if not identifier:
        raise ValueError('Select a registered default model before starting a trial')
    matches = [config for config in registry.get('models', []) if config.get('id') == identifier]
    if len(matches) != 1:
        raise ValueError('Selected model configuration is not uniquely registered: ' + str(identifier))
    config = dict(matches[0])
    expected_tokens = stage.get('max_tokens')
    if expected_tokens is not None and config.get('max_tokens') != expected_tokens:
        raise ValueError(f'Selected model must use the stage output budget of {expected_tokens} tokens')
    return config


def collect_sources():
    files = {}
    for name in ('frontend', 'backend'):
        directory = APP / name
        for path in [*directory.iterdir(), *(directory / 'src').rglob('*')]:
            if path.is_file() and not path.is_symlink():
                files[str(path.relative_to(APP))] = path.read_bytes()
    return files


def frozen():
    paths = []
    for base in (APP / 'harness', ROOT / 'platform'):
        paths.extend(p for p in base.rglob('*') if p.suffix in ('.py', '.cjs', '.txt')
                     and not any(part in ('state', 'node_modules', '__pycache__', 'web') for part in p.relative_to(base).parts))
    paths.extend((APP / 'frontend/src/framework').rglob('*'))
    paths.extend((ROOT / 'platform/acceptance').rglob('*.json'))
    return {str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in paths if p.is_file() and not p.is_symlink()}


def allowed(path):
    return path in (TARGET, MIGRATION, 'frontend/src/workspace.json') or (
        path.startswith(JAVA_ROOT) and path.endswith('.java') and '..' not in Path(path).parts)


def new_source_does_not_shadow(path, baseline):
    """New feature files must not replace the resolution of an existing module."""
    suffixes = ('.tsx', '.jsx', '.mts', '.cts', '.mjs', '.cjs', '.json', '.ts', '.js')

    def aliases(relative):
        if not relative.startswith('frontend/src/'):
            return set()
        suffix = next((extension for extension in suffixes if relative.endswith(extension)), None)
        if suffix is None:
            return set()
        stem = relative[:-len(suffix)].casefold()
        return {stem, str(PurePosixPath(stem).parent)} if PurePosixPath(stem).name == 'index' else {stem}

    candidate = aliases(path)
    return not candidate or not any(candidate & aliases(existing) for existing in baseline)


def capture_stage_ownership(stage, baseline):
    """Resolve only the explicitly approved successful stages, before launch."""
    directories = stage.get('approved_success_dirs')
    if directories is None:
        return None
    if not directories:
        raise ValueError('Owned-source editing requires approved successful stages')
    from source_ownership import ApprovedSuccess, capture_owned_sources, live_applied_migration_versions
    approved = tuple(ApprovedSuccess.pin(Path(directory)) for directory in directories)
    applied = live_applied_migration_versions() if stage.get('allow_unpublished_migrations') is True else None
    return capture_owned_sources(APP, baseline, approved, applied_migration_versions=applied)


def check_unpublished_migration_policy(stage, ownership, permitted_change, acceptance, script_sha256):
    """Pin eligible prior SQL from verified lineage before the native job starts."""
    if not stage.get('allow_unpublished_migrations'):
        return
    if set(stage.get('checks', ['frontend', 'backend', 'framework'])) != {'backend'}:
        raise ValueError('Prior migration edits require backend-only fresh-owned verification')
    expected = {path: digest for path, digest in ownership.unpublished_migrations.items()
                if permitted_change(path)}
    if not expected:
        raise ValueError('No approved unpublished migration is in this stage scope')
    policy = ROOT / 'platform/acceptance/policies' / (acceptance + '.json')
    if policy.parent.is_symlink() or policy.is_symlink():
        raise ValueError('Trusted backend workflow policy path is aliased')
    if policy.exists():
        info = policy.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 8192:
            raise ValueError('Trusted backend workflow policy is not a small regular file')
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('Duplicate trusted backend workflow policy key')
                result[key] = value
            return result
        data = json.loads(policy.read_text(), object_pairs_hook=unique)
        if (data.get('version') != 1 or data.get('acceptance_id') != acceptance or
                data.get('script_sha256') != script_sha256 or
                data.get('database_scope') != 'fresh-owned' or
                data.get('job_created_migration_edits') is not True or
                data.get('fixture_owner') not in ('legacy', 'checker') or
                type(data.get('discovery_round_limit')) is not int or
                not 0 <= data['discovery_round_limit'] <= 16 or
                set(data) - {'version', 'acceptance_id', 'script_sha256', 'database_scope',
                             'job_created_migration_edits', 'fixture_owner',
                             'discovery_round_limit', 'prior_unpublished_migrations'}):
            raise ValueError('Existing trusted backend workflow policy is invalid')
    else:
        data = {'version': 1, 'acceptance_id': acceptance,
                'script_sha256': script_sha256, 'database_scope': 'fresh-owned',
                'job_created_migration_edits': True, 'fixture_owner': 'checker',
                'discovery_round_limit': 8}
    data['prior_unpublished_migrations'] = dict(sorted(expected.items()))
    policy.parent.mkdir(parents=True, exist_ok=True)
    policy.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    if json.loads(policy.read_text()).get('prior_unpublished_migrations') != expected:
        raise ValueError('Trusted backend workflow policy pin was not persisted')


def events(identifier):
    path = STATE / identifier / 'events.jsonl'
    result = []
    for line in path.read_text().splitlines() if path.exists() else []:
        try:
            result.append(json.loads(line))
        except ValueError:
            pass
    return result


def check(command, cwd, timeout):
    process = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, start_new_session=True)
    def terminate():
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            output, _ = process.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            output, _ = process.communicate(timeout=5)
        return output
    try:
        output, _ = process.communicate(timeout=timeout)
        return process.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, terminate() + '\nIndependent check timed out'
    except BaseException:
        terminate()
        raise


def main(stage=None):
    # Keep the project reserved through independent checks and restoration,
    # including the interval after the native job is already terminal.
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / 'item-trial.lock').open('a+') as lease:
        try:
            fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('Another item trial supervisor is still active') from exc
        return _main(stage)


def _main(stage=None):
    stage = stage or {}
    acceptance = stage.get('acceptance', ACCEPTANCE)
    selected_checks = stage.get('checks', ['frontend', 'backend', 'framework'])
    max_calls = stage.get('max_calls', MAX_CALLS)
    wall_seconds = stage.get('wall_seconds', WALL_SECONDS)
    thinking = stage.get('thinking', THINKING)
    permitted_change = stage.get('allowed', allowed)
    permitted_new_source = stage.get('allowed_new')
    require_free_space(STATE)
    task = json.loads((ROOT / 'platform/acceptance' / (acceptance + '.json')).read_text())['task']
    specification = load_fixed_acceptance(acceptance, task, APP)
    oracle = Path(specification['script'])
    token = None

    def request(path, body=None):
        headers = {'Content-Type': 'application/json'}
        if body is not None:
            if not token:
                raise ValueError('Native API token unavailable')
            headers['X-Platform-Token'] = token
        req = urllib.request.Request(API + path, None if body is None else json.dumps(body).encode(), headers)
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.load(response)

    state = request('/api/state')
    assert not state.get('active') and not state.get('external'), 'Existing job active'
    assert Path(state['project']['root']).resolve() == APP.resolve(), 'Unexpected active project'
    token = state['token']
    model_config = select_model_config(request('/api/model-configs'), stage)
    with urllib.request.urlopen(model_config['url'].rstrip('/') + '/models', timeout=10) as response:
        assert response.status == 200
    before = collect_sources()
    missing_required = [path for path in stage.get('required_paths', ()) if path not in before]
    if missing_required:
        raise ValueError('Required prior-stage sources are missing: ' + ', '.join(missing_required))
    if not stage or stage.get('require_clean_start'):
        assert TARGET not in before and MIGRATION not in before and not any(p.startswith(JAVA_ROOT) for p in before), 'Trial must start without candidate sources'
    ownership = capture_stage_ownership(stage, before)
    if ownership is not None:
        stage_allows_existing = permitted_change
        permitted_change = lambda path: (ownership.allows_existing(path)
                                         and stage_allows_existing(path))
        check_unpublished_migration_policy(stage, ownership, permitted_change,
                                           acceptance, specification['script_sha256'])
    out = STATE / 'evidence' / (stage.get('evidence_prefix', 'item-crud-') + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True)
    evidence = TrialEvidence(out)
    candidate_state = CandidateStore(STATE / 'candidates', APP, task).file
    prior_paths = [APP / 'harness/state/failures.json', APP / 'harness_evidence.log', candidate_state]
    prior = {path: path.read_bytes() if path.exists() else None for path in prior_paths}
    body = {'kind': 'agent', 'goal': task, 'checks': selected_checks,
            'rounds': max_calls, 'thinking': thinking, 'model': 'config:' + model_config['id'],
            'fixed_acceptance': acceptance}
    if stage.get('context_profile'):
        body['context_profile'] = stage['context_profile']
    manifest = {'request': body, 'model_config': model_config,
                'limits': {'model_calls': max_calls, 'wall_seconds': wall_seconds,
                           'max_tokens': model_config['max_tokens']},
                'sources_before': {p: sha(raw) for p, raw in before.items()}, 'frozen_before': frozen(),
                'oracle_sha256': specification['script_sha256'], 'supervisor_sha256': sha(Path(__file__).read_bytes()),
                'manual_interventions_after_start': 0,
                'implementation_author': f'{model_config["name"]} ({model_config["model"]}); framework/harness/oracle by Codex',
                'database_policy': stage.get('database_policy', 'Fresh owned database and backend for each oracle; existing live database unchanged'),
                'failure_policy': 'restore sources and prior state; retain failed evidence',
                'success_policy': 'retain verified candidate sources and restore prior harness state'}
    if ownership is not None:
        manifest['source_ownership'] = ownership.to_manifest()
        manifest['source_ownership']['permitted_existing_for_stage'] = sorted(
            path for path in before if permitted_change(path))
        manifest['source_ownership']['existing_deletion_policy'] = 'forbidden'
    result = {'evidence': str(out), 'success': False, 'manual_interventions_after_start': 0,
              'model': model_config['model'], 'model_config_id': model_config['id']}
    job_id, launch_attempted, error_trace = None, False, None
    after = before
    started = time.monotonic()

    def dump(path, value):
        if not evidence.json(path, value):
            raise OSError('Evidence write failed: ' + str(path))

    def read_job(identifier):
        return json.loads((STATE / identifier / 'job.json').read_text())

    def stop_job(identifier):
        return request('/api/jobs/' + identifier + '/stop', {})

    def interrupted(signum, frame):
        raise KeyboardInterrupt('Supervisor received signal ' + str(signum))

    signal.signal(signal.SIGTERM, interrupted)

    def finalize():
        # Docker resources can outlive a killed CLI. Reconcile only the exact
        # ownership identities produced by this trial's trusted oracle.
        from item_crud_runtime import ItemRuntime
        runtime_paths = set(out.rglob('runtime.json'))
        for event in events(job_id) if job_id else []:
            if event['type'] == 'requirement.contract':
                artifact = event['data'].get('artifact_dir')
                if artifact:
                    runtime_paths.update(Path(artifact).rglob('runtime.json'))
        cleanup_reports = []
        for state_path in sorted(runtime_paths):
            identity = json.loads(state_path.read_text())
            runtime = ItemRuntime(state_path.parent, identity['token'])
            if any(identity.get(key) != value for key, value in runtime.state().items()):
                raise ValueError('Runtime cleanup identity mismatch')
            report = runtime.close()
            cleanup_reports.append({'state': str(state_path), **report})
        result['isolated_runtime_cleanup'] = cleanup_reports
        if any(not report['success'] for report in cleanup_reports):
            return {'workspace_verified': False, 'prior_state_restored': False,
                    'restore_blocked': 'Owned trial runtime cleanup is incomplete'}
        keep = bool(result['success'] and not evidence.errors)
        report = restore_snapshot(APP, after if keep else before, prior, collect_sources)
        valid = report.pop('completed_sources_restored')
        return {**report, 'workspace_verified': valid, 'candidate_retained': keep and valid,
                'baseline_restored': not keep and valid}

    try:
        evidence.arm_reserve(max(16 * 1024 ** 2, 2 * sum(len(v) for v in before.values())))
        dump(out / 'restore-snapshot.json', {p: base64.b64encode(raw).decode() for p, raw in before.items()})
        dump(out / 'restore-state.json', {str(p): base64.b64encode(raw).decode() if raw is not None else None for p, raw in prior.items()})
        dump(out / 'manifest.json', manifest)
        if not evidence.text(Path(stage.get('pointer', '/tmp/gemma-item-crud-current.txt')), str(out)):
            raise OSError('Cannot publish trial pointer')
        require_free_space(STATE)
        prior_paths[0].write_text('[]')
        prior_paths[1].write_text('')
        candidate_state.unlink(missing_ok=True)
        launch_attempted = True
        job_id = request('/api/jobs', body)['id']
        result['job_id'] = job_id
        launched = read_job(job_id)
        manifest['launched_model'] = {key: launched.get(key) for key in ('model', 'llm_url', 'model_config')}
        dump(out / 'manifest.json', manifest)
        if (launched.get('model_config') != model_config or launched.get('model') != model_config['model']
                or launched.get('llm_url') != model_config['url']):
            raise RuntimeError('Native job model settings differ from the pinned trial configuration')
        dump(out / 'running.json', result)
        print(json.dumps({'started': job_id, 'evidence': str(out)}, ensure_ascii=False), flush=True)
        while True:
            current, journal = read_job(job_id), events(job_id)
            calls = sum(e['type'] == 'model.request' for e in journal)
            elapsed = time.monotonic() - started
            dump(out / 'progress.json', {'status': current['status'], 'elapsed_seconds': round(elapsed),
                 'model_calls': calls, 'last_event': journal[-1]['type'] if journal else None,
                 'last_seq': journal[-1]['seq'] if journal else 0})
            if current['status'] not in ('running', 'stopping'):
                break
            if elapsed >= wall_seconds:
                result['limit_reached'] = 'wall_time'
                evidence.release_reserve()
                proof = stop_and_confirm(job_id, read_job, stop_job)
                result['limit_cleanup'] = proof
                if not proof['safe_to_restore']:
                    raise RuntimeError(proof['blocked'])
                current, journal = read_job(job_id), events(job_id)
                calls = sum(e['type'] == 'model.request' for e in journal)
                break
            time.sleep(3)
        proof = stop_and_confirm(job_id, read_job, stop_job, timeout=5)
        if not proof['safe_to_restore']:
            raise RuntimeError(proof['blocked'])
        result.update(status=current['status'], model_calls=calls, elapsed_seconds=round(time.monotonic() - started))
        after = collect_sources()
        changed = sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))
        dump(out / 'generated-sources.json', {p: base64.b64encode(after[p]).decode() for p in changed if p in after})
        result.update(changed_paths=changed, scope_respected=all(
            (permitted_change(p) and (ownership is None or p in after))
            or (p not in before and permitted_new_source is not None
                                    and permitted_new_source(p) and new_source_does_not_shadow(p, before))
            for p in changed),
                      frozen_unchanged=manifest['frozen_before'] == frozen(), target_exists=TARGET in after)
        for name, command, cwd, limit in (
            ('build', ['npm', 'run', 'build'], APP / 'frontend', 90),
            ('browser', ['node', str(oracle), str(out / 'browser')], ROOT, 180),
        ):
            passed, log = check(command, cwd, limit)
            evidence.text(out / (name + '.log'), log)
            result[name + '_passed'] = passed
        observed = json.loads((out / 'browser/result.json').read_text())
        result['frozen_unchanged'] = manifest['frozen_before'] == frozen()
        result['sources_stable_during_final_checks'] = collect_sources() == after
        result['oracle_cases'] = observed.get('cases', [])
        result['oracle_cleanup'] = observed.get('cleanup')
        if isinstance(observed.get('verificationMode'), str):
            result['verification_mode'] = observed['verificationMode']
        if isinstance(observed.get('browserStarted'), bool):
            result['browser_started'] = observed['browserStarted']
        exact_cases = (len(result['oracle_cases']) == len(specification['cases'])
                       and set(result['oracle_cases']) == set(specification['cases']))
        result['success'] = bool(current['status'] == 'succeeded' and result['target_exists'] and result['build_passed']
                                 and result['browser_passed'] and observed.get('passed') is True and exact_cases
                                 and result['scope_respected'] and result['frozen_unchanged']
                                 and result['sources_stable_during_final_checks'])
    except BaseException as exc:
        result.update(error=str(exc), infrastructure_failure=True, success=False)
        error_trace = traceback.format_exc()
    finally:
        result.update(cleanup_trial(evidence, job_id, launch_attempted, read_job, stop_job, finalize,
                                    timeout=0 if result.get('limit_cleanup', {}).get('blocked') else 85))
        result.pop('completed_sources_restored', None)
        result['cleanup_ok'] = bool(result.get('workspace_verified') and result.get('prior_state_restored'))
        if not result['cleanup_ok']:
            result['success'] = False
        if error_trace:
            evidence.text(out / 'supervisor-error.log', error_trace)
        result['evidence_errors'] = evidence.errors
        if evidence.errors:
            result.update(infrastructure_failure=True, success=False)
        result['result_written'] = True
        if not evidence.json(out / 'result.json', result):
            result.update(result_written=False, infrastructure_failure=True, success=False)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    return 1 if result.get('infrastructure_failure') or not result['cleanup_ok'] else 0


if __name__ == '__main__':
    sys.exit(main())
