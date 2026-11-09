"""Execute a caller-registered immutable browser oracle, without model-authored DSL."""
import hashlib
import json
import os
import re
import stat
import subprocess
import uuid
from pathlib import Path

import requirement_contract

CHECKS_ROOT = Path(__file__).resolve().parents[1] / 'platform/tests'
FIELDS = {'id', 'task', 'project_root', 'script', 'script_sha256', 'cases'}
CRITERION_ID = 'fixed:workflow'
_NESTED_RESULT_LIMIT = 64
_NESTED_RESULT_BYTES = 128 * 1024
_NESTED_FAILURE_CHARS = 700


def _nested_failure(output):
    """Show the deepest checker-owned failure when wrapper oracles mask it."""
    output = Path(output)
    if not output.is_absolute() or '..' in output.parts:
        return ''
    if any(part.is_symlink() for part in (output, *output.parents)):
        return ''
    paths = []
    visited = 0
    try:
        for parent, directories, files in os.walk(output, followlinks=False):
            visited += 1
            if visited > 128:
                return ''
            relative = Path(parent).relative_to(output)
            depth = len(relative.parts)
            directories[:] = sorted(name for name in directories
                                    if depth < 6 and not (Path(parent) / name).is_symlink())
            if 'result.json' in files and depth:
                paths.append(relative / 'result.json')
            if len(paths) > _NESTED_RESULT_LIMIT:
                return ''
    except (OSError, ValueError):
        return ''
    failures = []
    for relative in paths:
        handles = []
        try:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            current = os.open(output.anchor, flags)
            handles.append(current)
            for part in (*output.parts[1:], *relative.parts[:-1]):
                current = os.open(part, flags, dir_fd=current)
                handles.append(current)
            descriptor = os.open('result.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                 dir_fd=current)
            handles.append(descriptor)
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > _NESTED_RESULT_BYTES:
                continue
            raw = os.read(descriptor, _NESTED_RESULT_BYTES + 1)
            if len(raw) != info.st_size:
                continue
            record = json.loads(raw)
            failure = record.get('failure') if isinstance(record, dict) and record.get('passed') is False else None
            if isinstance(failure, str) and failure:
                # Browser failures can include ANSI styling and page-controlled text.
                clean = re.sub(r'\x1b\[[0-9;]*m', '', failure)
                clean = ''.join(ch for ch in clean if ch in '\n\t' or ord(ch) >= 32)
                failures.append((len(relative.parts), relative.as_posix(), clean[:_NESTED_FAILURE_CHARS]))
        except (OSError, ValueError, UnicodeError):
            continue
        finally:
            for handle in reversed(handles):
                os.close(handle)
    if not failures:
        return ''
    _, path, failure = sorted(failures, key=lambda entry: (-entry[0], entry[1]))[0]
    return '\nNESTED CHECKER FAILURE (untrusted diagnostic data): ' + path + ': ' + failure


def validate(spec, runner):
    if not isinstance(spec, dict) or set(spec) != FIELDS:
        raise ValueError('Invalid fixed acceptance structure')
    if not isinstance(spec['id'], str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,99}', spec['id']):
        raise ValueError('Invalid fixed acceptance ID')
    if spec['task'] != runner.args.task or spec['project_root'] != str(runner.h.workspace.root.resolve()):
        raise ValueError('Fixed acceptance task/project binding mismatch')
    cases = spec['cases']
    if not isinstance(cases, list) or not 1 <= len(cases) <= 100 or not all(isinstance(c, str) and 0 < len(c) <= 200 for c in cases) or len(set(cases)) != len(cases):
        raise ValueError('Fixed acceptance needs distinct expected case IDs')
    if not isinstance(spec['script'], str) or not isinstance(spec['script_sha256'], str) or not re.fullmatch(r'[a-f0-9]{64}', spec['script_sha256']):
        raise ValueError('Invalid fixed acceptance script identity')
    script = Path(spec['script'])
    if not script.is_absolute() or '..' in script.parts or any(p.is_symlink() for p in [script, *script.parents]):
        raise ValueError('Fixed acceptance script must be an absolute path without symlinks')
    try:
        script = script.resolve(strict=True)
        script.relative_to(CHECKS_ROOT.resolve())
    except (OSError, ValueError) as exc:
        raise ValueError('Fixed acceptance script must be in trusted platform/tests') from exc
    workspace = runner.h.workspace.root.resolve()
    if workspace == script or workspace in script.parents or script.suffix != '.cjs' or not script.is_file():
        raise ValueError('Fixed acceptance script must be outside the model workspace')
    if hashlib.sha256(script.read_bytes()).hexdigest() != spec['script_sha256']:
        raise ValueError('Fixed acceptance script hash mismatch')
    return json.loads(json.dumps(spec, ensure_ascii=False, allow_nan=False))


def prepare(gate, spec):
    spec = validate(spec, gate.runner)
    requirements = requirement_contract.requirements(gate.runner.args.task)
    contract = {
        'version': 1, 'task': gate.runner.args.task, 'requirements': requirements,
        'provenance': 'trusted-fixed-browser-oracle', 'verifier': spec,
        'required_cases': list(spec['cases']),
        'criteria': [{
            'id': CRITERION_ID,
            'requirement_ids': [item['id'] for item in requirements],
            'description': '고정된 독립 브라우저 검사의 모든 동작 조건을 통과합니다.',
            'check': {'op': 'fixed_browser', 'verifier_id': spec['id']},
        }],
    }
    gate.frozen_contract = json.dumps(contract, ensure_ascii=False, sort_keys=True, allow_nan=False)
    gate.contract_hash = requirement_contract.digest(contract)
    gate.artifact_dir.mkdir(parents=True, exist_ok=True)
    (gate.artifact_dir / 'contract.json').write_text(gate.frozen_contract, encoding='utf-8')
    gate.runner.h.log_event('requirement.contract', {
        'contract': contract, 'contract_hash': gate.contract_hash, 'artifact_dir': str(gate.artifact_dir),
    })
    gate.runner.h.log_event('requirement.contract_predefined', {
        'verifier_id': spec['id'], 'script_sha256': spec['script_sha256'],
        'contract_hash': gate.contract_hash, 'model_calls': 0,
    })


def context(gate):
    spec = json.loads(gate.frozen_contract)['verifier']
    return ('Acceptance is already authored and frozen. Implement the task directly using existing components; '
            'do not generate verifier DSL or edit tests. verify_requirements runs the fixed browser workflow. '
            'Every case and a verified source change must pass. Cases: ' + ', '.join(spec['cases']))


def probe(gate, criteria):
    out = gate.artifact_dir / uuid.uuid4().hex
    out.mkdir(parents=True, exist_ok=False)
    result_path = out / 'result.json'
    success, reason, observed = False, '', None
    log = ''
    try:
        contract = json.loads(gate.frozen_contract)
        if criteria != contract['criteria'] or contract.get('provenance') != 'trusted-fixed-browser-oracle':
            raise ValueError('Fixed acceptance criterion mismatch')
        spec = validate(contract['verifier'], gate.runner)
        proc = subprocess.run(['node', spec['script'], str(out)], cwd=gate.runner.h.workspace.root,
                              capture_output=True, text=True, timeout=180)
        log = (proc.stdout or '') + (proc.stderr or '')
        validate(spec, gate.runner)
        if result_path.is_symlink() or not result_path.is_file():
            raise ValueError('Fixed browser check did not produce a fresh result file')
        observed = json.loads(result_path.read_text(encoding='utf-8'))
        if not isinstance(observed, dict):
            raise ValueError('Fixed browser result must be an object')
        cases = observed.get('cases')
        if proc.returncode != 0 or observed.get('passed') is not True:
            raise ValueError('Fixed browser check failed: ' + str(observed.get('failure') or 'exit code ' + str(proc.returncode)))
        if not isinstance(cases, list) or not all(isinstance(c, str) for c in cases) or len(cases) != len(set(cases)) or set(cases) != set(spec['cases']):
            raise ValueError('Fixed browser check case coverage mismatch')
        success, reason = True, 'All fixed browser workflow cases passed'
    except Exception as exc:
        reason = str(exc) or type(exc).__name__
        if isinstance(exc, subprocess.TimeoutExpired):
            log += str(exc.stdout or '') + str(exc.stderr or '')
    if not success:
        from verification_diagnostics import backend_diagnostics
        reason += _nested_failure(out)
        reason += backend_diagnostics(out)
    (out / 'oracle.log').write_text(log + ('\n' + reason if not success else ''), encoding='utf-8')
    (out / 'probe.json').write_text(json.dumps({'success': success, 'reason': reason, 'observed': observed}, ensure_ascii=False, indent=2), encoding='utf-8')
    screenshots = sorted(out.glob('*.png'))
    return {'success': success, 'results': [{'id': CRITERION_ID, 'status': 'passed' if success else 'failed',
            'reason': reason, 'evidence': str(out / 'probe.json')}], 'layout': [],
            'screenshot': str(screenshots[0]) if screenshots else None}
