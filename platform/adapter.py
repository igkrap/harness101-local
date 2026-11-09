"""Observe the local harness in a child process without changing its source."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import time
from datetime import datetime, timezone
from server import file_signature
from quality import checked_result
from changes import Changes


def execute(project, job_dir, request):
    project, job_dir = Path(project).resolve(), Path(job_dir).resolve()
    job_dir.mkdir(parents=True, exist_ok=True)
    journal = job_dir / 'events.jsonl'
    lock = threading.Lock()
    sequence = 0
    completion_events = {}

    def emit(kind, data):
        nonlocal sequence
        with lock:
            sequence += 1
            event = {'seq': sequence, 'time': datetime.now(timezone.utc).isoformat(), 'type': kind, 'data': data}
            if kind in ('requirement.contract', 'verification.finished', 'autonomy.accepted'):
                completion_events[kind] = json.loads(json.dumps(event, ensure_ascii=False))
            with journal.open('a', encoding='utf-8') as f:
                f.write(json.dumps(event, ensure_ascii=False, default=str) + '\n')

    # Qwen3.8 accepts 262k tokens; append-only history up to 40k stays cached; larger KV overflows Metal memory on this 32GB machine on the MLX server.
    # Set before the harness modules are imported because they read it at import time.
    os.environ.setdefault('LOCAL_LLM_CONTEXT', '40000')
    os.environ['HARNESS_JOB_DIR'] = str(Path(job_dir).resolve())  # per-run checker notes (framework baseline)
    os.environ['HARNESS_CHANGED_PATHS'] = '[]'
    # Implementation direction written by the task-queue planner (a hint, not a requirement).
    os.environ['HARNESS_QUEUE_ITEM'] = '1' if request.get('queue') else ''
    os.environ['HARNESS_TASK_APPROACH'] = str((request.get('queue') or {}).get('approach') or '')[:600]
    runtime = Path(request.get('harness_root') or project / 'harness').resolve()
    sys.path.insert(0, str(runtime))
    spec = importlib.util.spec_from_file_location('observed_local_harness', runtime / 'harness.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    buffer_store = None
    if (runtime / 'candidate_repair.py').is_file() and (runtime / 'candidate_focus.py').is_file():
        from virtual_candidate_runner import install
        buffer_store = install(job_dir.parent / 'candidates', project, request['goal'])
        from structured_tool_transport import install as require_ast_actions
        require_ast_actions()
        from checker_fingerprint import install as track_checker_definitions
        track_checker_definitions(project, runtime, request['goal'])
    base = module.Harness
    attempt_number = 0
    changes = Changes(project, job_dir)

    class ObservedHarness(base):
        def __init__(self, args):
            nonlocal attempt_number
            super().__init__(args)
            attempt_number += 1
            self.attempt = attempt_number
            self.evidence_path = job_dir / 'harness.jsonl'
            original_chat = self.llm.chat
            original_check = self.checker.run_check

            def chat(messages, tools=None):
                started = time.monotonic()
                estimate = (len(json.dumps(messages)) + len(json.dumps(tools or []))) // 3
                context = None
                if (runtime/'context_budget.py').is_file():
                    try:
                        from context_budget import measure
                        context = measure(messages,tools,int(os.environ.get('LOCAL_LLM_MAX_TOKENS','4096')),getattr(module,'MAX_BUDGET',32768))
                    except (ValueError,TypeError): pass
                emit('model.request', {'attempt': self.attempt, 'model': args.model, 'estimated_input_tokens': estimate, 'context': context,
                      'timeout_seconds': int(os.environ.get('LOCAL_LLM_TIMEOUT', '600')),
                      'timeout_policy': {'connect_seconds': 10, 'headers_seconds': int(os.environ.get('LOCAL_LLM_TIMEOUT', '600')),
                          'body_idle_seconds': int(os.environ.get('LOCAL_LLM_TIMEOUT', '600')), 'request_retries': 4, 'job_deadline_seconds': None}})
                try:
                    reply = original_chat(messages, tools=tools)
                    choice = (reply.get('choices') or [{}])[0]
                    emit('model.response', {'attempt': self.attempt, 'duration_ms': round((time.monotonic()-started)*1000),
                         'usage': reply.get('usage'), 'finish_reason': choice.get('finish_reason'),
                         'text': str(choice.get('message', {}).get('content') or '')[:16000],
                         'text_truncated': len(str(choice.get('message', {}).get('content') or ''))>16000,
                         'message_keys': sorted(choice.get('message', {})),
                         'provider_recovery': reply.get('provider_recovery'),
                         'reasoning_chars': len(str(choice.get('message', {}).get('reasoning_content') or choice.get('message', {}).get('reasoning') or '')),
                         'tool_calls': choice.get('message', {}).get('tool_calls') or []})
                    return reply
                except Exception as exc:
                    emit('model.error', {'attempt': self.attempt, 'error': str(exc), 'duration_ms': round((time.monotonic()-started)*1000)})
                    raise

            def check(mode):
                started = time.monotonic()
                signature = file_signature(project, mode)
                emit('check.started', {'mode': mode, 'attempt': self.attempt})
                try:
                    result = checked_result(mode, original_check(mode))
                    if signature != file_signature(project, mode):
                        result = {**result, 'success': False, 'stderr': result.get('stderr', '')+'\n검사 중 소스 변경: 재검사가 필요합니다.'}
                    emit('check.finished', {'mode': mode, 'attempt': self.attempt, 'success': bool(result['success']),
                         'source_hash': signature, 'lint': result.get('lint'),
                         'error': result.get('error',''),
                         'exit_code': result.get('exit_code'), 'duration_ms': round((time.monotonic()-started)*1000),
                         'stdout': result.get('stdout', '')[-16000:], 'stderr': result.get('stderr', '')[-16000:]})
                    return result
                except Exception as exc:
                    emit('check.finished', {'mode': mode, 'attempt': self.attempt, 'success': False, 'error': str(exc),
                         'duration_ms': round((time.monotonic()-started)*1000)})
                    raise

            self.llm.chat, self.checker.run_check = chat, check

        def run(self):
            emit('attempt.started', {'attempt': self.attempt, 'round_budget': self.args.max_rounds})
            ok = super().run()
            emit('attempt.finished', {'attempt': self.attempt, 'success': bool(ok)})
            return ok

        def log_event(self, event_type, data):
            super().log_event(event_type, data)
            if event_type == 'autonomy.accepted':
                changes.accept(data.get('paths', []))
                if buffer_store:
                    buffer_store.accept(data.get('paths', []))
            if event_type.startswith(('autonomy.', 'requirement.', 'verification.')):
                emit(event_type, {**data,'success':data.get('approved') is True} if event_type=='requirement.review' else data)
            if event_type == 'tool_call' and data.get('name') in ('inspect_layout','verify_requirements'):
                result=data.get('result') or {}
                body=json.dumps(result,ensure_ascii=False,default=str)
                emit('tool.finished', {'attempt':self.attempt,'name':data['name'],
                    'success':not bool(result.get('error')) and result.get('success',True) is not False,
                    'stdout':body[:16000],'truncated':len(body)>16000,'error':str(result.get('error') or '')})

        def _execute_tool(self, name, args):
            started = time.monotonic()
            if name in ('write_file','edit_file','delete_file') and isinstance(args.get('path'),str): changes.capture(args['path'])
            if name in ('write_file','edit_file','delete_file','apply_ast_edits','apply_edits','apply_insertions','insert_text') and isinstance(args.get('path'),str):
                # Checks spawned later in this run inherit this: framework checks use it to tell an
                # intentional common-component change from an accidental regression.
                edited = json.loads(os.environ.get('HARNESS_CHANGED_PATHS', '[]'))
                if args['path'] not in edited:
                    os.environ['HARNESS_CHANGED_PATHS'] = json.dumps(edited + [args['path']])
            search = {'query': str(args.get('query', ''))[:300], 'search_mode': args.get('mode', 'exact'), 'scope': args.get('scope', 'all')} if name == 'search_code' else {}
            if name == 'inspect_code': search = {key: args.get(key) for key in ('action','symbol','line','column') if key in args}
            emit('tool.started', {'attempt': self.attempt, 'name': name, 'path': args.get('path'), 'text': json.dumps(args, ensure_ascii=False)[:16000],
                  'text_truncated': len(json.dumps(args, ensure_ascii=False))>16000, **search})
            result = super()._execute_tool(name, args)
            ok = isinstance(result, dict) and 'error' not in result
            emit('tool.finished', {'attempt': self.attempt, 'name': name, 'path': args.get('path'), 'success': ok,
                 'changed': ok and name in ('write_file', 'edit_file', 'delete_file'),
                 'error': str(result.get('error', ''))[:2000] if isinstance(result, dict) else '',
                 **search,
                 'stdout': json.dumps(result, ensure_ascii=False, default=str)[:16000],
                 'truncated': len(json.dumps(result, ensure_ascii=False, default=str))>16000 or bool(result.get('truncated')) if isinstance(result,dict) else len(str(result))>16000,
                 'duration_ms': round((time.monotonic()-started)*1000)})
            if name in ('write_file','edit_file','delete_file','apply_ast_edits','apply_edits','apply_insertions','insert_text') and isinstance(args.get('path'),str):
                changes.note_written(args['path'])
            return result

    module.Harness = ObservedHarness
    args = argparse.Namespace(task=request['goal'], workspace=str(project), check='|'.join(request['checks']),
                              max_rounds=request['rounds'], llm_url=request.get('llm_url','http://127.0.0.1:8099/v1'),
                              model=request.get('model') or module.DEFAULT_MODEL,
                              context_profile=request.get('context_profile', 'legacy'),
                              ponytail='off' if request.get('context_profile') == 'focused' else 'full')
    if request.get('edit_format') in ('auto', 'diff'):
        args.edit_format = request['edit_format']
    if request.get('resume_contract') is not None:
        args.resume_contract = request['resume_contract']
    if request.get('fixed_acceptance') is not None:
        args.fixed_acceptance = request['fixed_acceptance']
    if request.get('test_db_url'): os.environ['HARNESS_TEST_DB_URL'] = request['test_db_url']
    if request.get('preview_url'):
        os.environ['HARNESS_PREVIEW_URL'] = request['preview_url']
        os.environ['HARNESS_API_URL'] = request.get('api_url') or request['preview_url']
    os.environ['PONYTAIL_SKILL_PATH'] = str(Path.home()/'.local/share/mlx-server/skills/ponytail/SKILL.md')
    os.environ['LOCAL_LLM_THINKING'] = 'true' if request.get('thinking') else 'false'
    settings = request.get('model_config') or {}
    os.environ['LOCAL_LLM_MAX_TOKENS'] = '4096'
    for setting, variable in [('temperature','LOCAL_LLM_TEMPERATURE'),('max_tokens','LOCAL_LLM_MAX_TOKENS'),('timeout','LOCAL_LLM_TIMEOUT')]:
        if setting in settings: os.environ[variable] = str(settings[setting])
    os.environ['DEPENDENCY_ROOT'] = str(Path.home()/'.local/share/mlx-server/astryx-docs/node_modules')
    os.environ['PATH'] = '/Applications/Docker.app/Contents/Resources/bin:' + os.environ.get('PATH', '')
    emit('run.started', {'goal': args.task, 'checks': request['checks'], 'round_budget': args.max_rounds,
                        'model': args.model, 'thinking': request.get('thinking', False)})
    try:
        supervisor = runtime/'supervisor.py'
        if supervisor.exists():
            sys.path.insert(0, str(supervisor.parent))
            runner_spec = importlib.util.spec_from_file_location('observed_supervisor', supervisor)
            runner = importlib.util.module_from_spec(runner_spec)
            runner_spec.loader.exec_module(runner)
            ok = runner.run_supervised(args, ObservedHarness)
        else:
            ok = module.run_task(args) if hasattr(module, 'run_task') else ObservedHarness(args).run()
        if ok:
            from verification_report import completion_evidence
            verified, reason = completion_evidence(completion_events, args.task)
            if not verified:
                ok = False
                emit('run.error', {'error': reason, 'stage': 'completion_gate'})
        if ok and not changes.accepted: changes.accept(list(changes.before))
        if not ok:
            # Only a verified run may leave edits behind; accepted-but-unverified patches would
            # otherwise silently change the live workspace and the next run's baseline.
            restored = changes.restore_unverified()
            if restored:
                emit('run.restored', {'paths': restored, 'reason': 'run did not complete successfully'})
        stopped = bool(getattr(args, 'stop_requested', False))
        clean_stop = stopped and not getattr(args, 'stop_cleanup_failed', False)
        emit('run.finished', {'success': bool(ok), 'stopped': stopped, 'clean_stop': clean_stop, 'reason': 'user' if stopped else None})
        return 0 if ok or clean_stop else 1
    except BaseException as exc:
        emit('run.error', {'error': str(exc)})
        try:
            restored = changes.restore_unverified()
            if restored:
                emit('run.restored', {'paths': restored, 'reason': 'run aborted'})
        except Exception:
            pass
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', required=True)
    parser.add_argument('--job-dir', required=True)
    args = parser.parse_args()
    request = json.loads((Path(args.job_dir)/'request.json').read_text())
    sys.exit(execute(args.project, args.job_dir, request))
