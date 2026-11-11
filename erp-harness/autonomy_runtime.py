import json
import re
from pathlib import Path
import hashlib
import os
import signal
import threading
from checkpoints import Checkpoint
from failure_memory import FailureMemory
from edit_tools import INSERT_TOOL, insert_arguments
from batch_edits import BATCH_TOOL, batch_arguments
from patch_edits import PATCH_TOOL, patch_arguments
from java_annotations import ANNOTATION_TOOL, annotation_arguments
from test_isolation import ISOLATION_TOOL, isolation_arguments
from project_context import project_files, project_context, missing_path_message, new_screen_error
from focused_repair import repair_new
from screen_context import screen_reference

class StopLoop(BaseException):
    pass

class BudgetEnd(Exception):
    pass


def rejected_new_file_context(records, max_chars=18000):
    """Keep complete model-authored files after rollback; report every omission."""
    candidates = [(path, data['expected'].decode('utf-8', 'replace'))
                  for path, data in records.items()
                  if data.get('before') is None and isinstance(data.get('expected'), bytes)]
    if not candidates:
        return ''
    notes = {path: f'OMITTED REJECTED NEW FILE: {path} ({len(source)} chars; whole file exceeds remaining context budget)\n'
             for path, source in candidates}
    reserve = min(4096, sum(len(note) for note in notes.values()) + 100)
    blocks, omitted, size = [], [], 0
    for path, source in candidates:
        block = f'REJECTED NEW FILE reference, not present in workspace after rollback; complete model-authored source: {path}\n{source}\n'
        if size + len(block) <= max_chars - reserve:
            blocks.append(block)
            size += len(block)
        else:
            omitted.append(path)
    for index, path in enumerate(omitted):
        note = notes[path]
        if size + len(note) + 100 > max_chars:
            blocks.append(f'OMITTED REJECTED NEW FILES: {len(omitted) - index} additional paths (context budget).\n')
            break
        blocks.append(note)
        size += len(note)
    return ''.join(blocks)


class Runner:

    def __init__(self, args, harness_class):
        self.args = args
        self.h = harness_class(args)
        self.rejected_candidate = None
        from rejected_new_files import RejectedNewFiles
        self.rejected_new_files = RejectedNewFiles(self.h.workspace)
        self.initial_screens = {p for p in project_files(self.h.workspace.root) if p.startswith('frontend/src/screens/')}
        self.initial_frontend_files = {str(p.relative_to(self.h.workspace.root)) for p in (self.h.workspace.root / 'frontend/src').rglob('*') if p.is_file() and p.suffix in ('.ts', '.tsx', '.js', '.jsx')}
        self.cp = Checkpoint(self.h.workspace)
        self.memory = FailureMemory(self.h.workspace.root)
        self.compiled_before = False
        self.modes = args.check.split('|')
        self.used = 0
        self.steps = []
        self.step = 0
        self.accepted = False
        self.read = set()
        self.listed = {}
        self.progress = 0
        self.messages = []
        self.feedback = ''
        self.idle = 0
        self._migration_full_reads = {}
        self._job_migrations = None
        from workflow_policy import get_policy
        policy = get_policy(self)
        if policy.enabled:
            self.h.log_event('workflow.policy', policy.to_manifest())
        if policy.job_created_migration_edits:
            from job_migrations import JobMigrationProvenance
            self._job_migrations = JobMigrationProvenance.capture(
                self.h.workspace, enabled=policy.enabled,
                fresh_backend_checks=(getattr(self.h.checker, 'schema_application_scope', None) == 'fresh-owned'),
                prior_unpublished=dict(policy.prior_unpublished_migrations))
            if self._job_migrations.enabled:
                self.cp = self._job_migrations.wrap_checkpoint(self.cp)

    def _remember_migration_read(self, path, raw):
        ledger = getattr(self, '_job_migrations', None)
        if (ledger is not None and ledger.enabled and isinstance(raw, bytes) and
                path.startswith('backend/src/main/resources/db/migration/') and path.endswith('.sql')):
            self._migration_full_reads[path] = hashlib.sha256(raw).hexdigest()

    def ask(self, messages, tools):
        if self.args.max_rounds > 0 and self.used >= self.args.max_rounds:
            raise BudgetEnd
        self.used += 1
        reply = self.h.llm.chat(messages, tools=tools)
        return reply['choices'][0]['message']

    def verify(self):
        import time
        from test_feedback import feedback
        results = []
        self.last_check_results = {}
        lines = []
        frontend_failed = False
        for mode in self.modes:
            started = time.time()
            if mode == 'framework' and frontend_failed:
                results.append(False)
                lines.append((False, '[framework] skipped because frontend compile/lint failed; fix frontend errors first'))
                self.h.log_event('autonomy.strategy', {'mode': 'framework', 'reason': 'Browser check skipped after frontend failure', 'success': False})
                continue

            r = self.h.checker.run_check(mode)
            if mode == 'frontend' and not r.get('success', False) and self.cp.pending:
                from import_reflex import repair_imports
                if repair_imports(self, r):
                    r = self.h.checker.run_check(mode)
            self.last_check_results[mode] = r
            self.h.log_event('check', {'mode': mode, 'result': r})
            success = bool(r.get('success', False))
            if mode == 'frontend' and not success:
                frontend_failed = True
            
            results.append(success)
            lines.append((True, feedback(self.h.workspace.root, mode, r, started)))
        important = [l[1] for l in lines if l[0]]
        others = [l[1] for l in lines if not l[0]]
        diag = '\n'.join(important + others[-30:])[:5000]
        return (all(results), diag)

    def plan(self):
        from runtime_policy import plan_prompt
        prompt = plan_prompt(self.args.task, self.feedback)
        reply = self.ask([{'role': 'user', 'content': prompt}], tools=[])
        content = reply.get('content') or ''
        try:
            start_idx = content.find('{')
            end_idx = content.rfind('}')
            if start_idx == -1 or end_idx == -1:
                raise ValueError('No JSON found')
            data = json.loads(content[start_idx:end_idx + 1])
            steps = data.get('steps')
            if not isinstance(steps, list):
                raise ValueError('steps is not a list')
            valid_steps = []
            for s in steps[:4]:
                if not isinstance(s, dict):
                    continue
                title = str(s.get('title', '')).strip()
                kind = str(s.get('kind', '')).strip()
                if title and title[:600] and (kind in ('change', 'verify')):
                    valid_steps.append({'title': title[:600], 'kind': kind})
            if not valid_steps:
                raise ValueError('No valid steps')
            self.steps = valid_steps
        except Exception:
            self.steps = [{'title': self.args.task, 'kind': 'change'}]
        self.h.log_event('autonomy.plan', {'steps': self.steps})

    def fresh(self, reason=''):
        from focused_context import enabled, feedback as context_feedback
        focused_context = enabled(self)
        if not reason:
            self.failed_calls = {}
            self.blocked_tools = set()
        sys_msg = f'Task: {self.args.task}. Current step: {self.steps[self.step]}. Read existing files before editing. Old text is exact, new text is FULL replacement. One response may use multiple tools for ONE atomic step. Never weaken tests. Finish tool after step checks pass. No arbitrary commands. For additive changes use insert_text rather than rewriting the file. Java annotations can use fully qualified names so imports need not change. After a rejected rewrite, preserve all learned working imports and make a small additive edit. If an additive fix needs edits at multiple locations, use apply_insertions with ALL blocks in one call so checks see the complete fix. Use insert_text only when one addition alone can pass checks. Do not inspect unrelated directories after current files are provided. For an existing file, prefer apply_edits with several small exact snippets when imports and JSX must change together. Preserve all unrelated imports and hooks; never reconstruct the whole file. implement the current user goal, cosmetic edits alone do not complete functional requests, and for multi-screen work modify one relevant file per model response using small exact edits.'
        if focused_context:
            sys_msg = sys_msg.replace(f'Current step: {self.steps[self.step]}.', f'Current step: {self.step + 1}/{len(self.steps)}.')
        if ('frontend' in self.modes or 'framework' in self.modes) and getattr(self.args, 'edit_format', 'auto') not in ('diff', 'whole'):
            sys_msg = sys_msg.replace('For additive changes use insert_text rather than rewriting the file.', '').replace('Use insert_text only when one addition alone can pass checks.', '').replace('For an existing file, prefer apply_edits with several small exact snippets when imports and JSX must change together.', '')
            sys_msg = sys_msg.replace('If an additive fix needs edits at multiple locations, use apply_insertions with ALL blocks in one call so checks see the complete fix.', '')
            sys_msg += ' EXISTING FRONTEND TS/TSX: use provided AST IDs with apply_ast_edits; raw file/snippet/insertion tools are unavailable for existing source. For layout choose the named return JSX node; for attributes choose its opening-tag node. Metadata nodes change meta only. Function insertion slots accept local statements only, never imports/exports or whole screens/files. Imports use import nodes or after-imports slot. New files and workspace JSON retain normal file tools. On AST_EDIT_FEEDBACK repair the failed node using current layout_targets IDs, do not reread unchanged sources.'
        approach = os.environ.get('HARNESS_TASK_APPROACH', '').strip()
        if os.environ.get('HARNESS_QUEUE_ITEM') == '1':
            sys_msg = _plain_brief(self, approach)
        elif approach:
            sys_msg += (' IMPLEMENTATION DIRECTION from the task planner (it saw the target screen and the components it renders; '
                        'verify against the actual sources, the completion contract still decides): ' + approach[:600])
        if os.environ.get('HARNESS_QUEUE_ITEM') != '1':
            sys_msg = _legacy_context(self, sys_msg, focused_context)
        user_content = f"CURRENT SOURCE CHECK: {getattr(self, 'baseline_feedback', '')[:1800]}\n\nLAST ATTEMPT FEEDBACK: {context_feedback(self)}\n\n" + self.memory.context()
        if focused_context:
            user_content += '\n\n' + self.rejected_new_context()
        if self.listed:
            user_content += '\nAlready discovered directories/files (do not repeat):\n' + json.dumps(self.listed, ensure_ascii=False)[:2200]
        if reason:
            user_content += ' Current workspace sources and selected-check patch progress follow. Only supplied current sources count as read; read omitted files before editing.'
        if 'frontend' in self.modes or 'framework' in self.modes:
            from recipe_context import prefer_recipe
            if not prefer_recipe(self):
                self.read.add('frontend/src/App.tsx')
        (snapshot_text, snapshot_paths) = self.current_context()
        user_content += '\n\n' + snapshot_text
        self.messages = [{'role': 'system', 'content': sys_msg}, {'role': 'user', 'content': user_content}]
        self.read = set(snapshot_paths)
        no_screen = not {'frontend', 'framework'} & set(self.modes or ())
        (reference_text, reference_paths) = ('', set()) if focused_context or no_screen else screen_reference(self.h.workspace.root, self.args.task)
        self.messages[-1]['content'] += reference_text
        self.read.update(reference_paths)
        from source_progress import sync_read_context
        sync_read_context(self, self.read)
        self.idle = 0
        self.focused = bool(reason)
        if reason:
            self.h.log_event('autonomy.retry', {'reason': reason, 'round': self.used})

    def batch(self, message):
        before = {}
        errors = []
        finished = (message.get('content') or '').strip().lower() == 'finish'
        # Failure memory evaluates a proposal together with its declared sibling
        # files, regardless of tool order. Actual writes still validate and the
        # entire batch rolls back if any tool/check fails.
        self._proposed_dependencies = {}
        for proposal in message.get('tool_calls') or []:
            if proposal.get('function', {}).get('name') != 'write_file':
                continue
            try:
                from divide_plan import duplicate_hook
                from tool_input_validation import validate_arguments
                values = json.loads(proposal['function'].get('arguments', '{}'), object_pairs_hook=duplicate_hook)
                validate_arguments(self, 'write_file', values)
                target = self.h.workspace.safe_path(values['path'])
                if not self.h.workspace.is_protected(target):
                    relative = str(target.relative_to(self.h.workspace.root))
                    self._proposed_dependencies[relative] = values['content'].encode('utf-8')
            except Exception:
                pass  # The normal tool path reports invalid arguments below.
        for tc in message.get('tool_calls') or []:
            inputs = {}
            name = tc.get('function', {}).get('name', '')
            try:
                from divide_plan import duplicate_hook
                args_str = tc.get('function', {}).get('arguments', '{}')
                inputs = json.loads(args_str, object_pairs_hook=duplicate_hook)
                if not isinstance(inputs, dict):
                    raise ValueError('Arguments must be a dictionary')
                if name in getattr(self, 'blocked_tools', set()):
                    raise ValueError('Tool disabled after repeated rejected operation; choose another available tool')
                from tool_input_validation import validate_arguments
                validate_arguments(self, name, inputs)
                result = self.apply(name, inputs, before)
                if name in ('finish', 'update_seed_rows') and (not result.get('error')):
                    finished = True
            except Exception as exc:
                result = {'error': str(exc)}
            self.h.log_event('tool_call', {'name': name, 'args': inputs, 'result': result})
            if result.get('error'):
                err_msg = f"Tool {name} failed: {result['error']}"
                errors.append(err_msg)
                self.reject_repeat(name, inputs, result['error'])
                self.h.log_event('autonomy.blocked', {'name': name, 'path': inputs.get('path') if isinstance(inputs, dict) else None, 'error': str(result['error'])})
            serialized = json.dumps(result, ensure_ascii=False)
            from focused_context import enabled
            limit = (32000 if name == 'inspect_code' and inputs.get('action') == 'edit_ranges'
                     else 12000 if name == 'read_file' and enabled(self) else 6000)
            if name == 'read_file' and result.get('status') == 'rejected_candidate' and result.get('exists') is False:
                # This result is bounded by RejectedNewFiles. Never silently
                # truncate its complete model-authored source at the tool cap.
                limit = len(serialized)
            if len(serialized) > limit:
                serialized = json.dumps({'summary': serialized[:limit]}, ensure_ascii=False)
                if enabled(self) and name == 'read_file':
                    from source_progress import sync_read_context
                    sync_read_context(self, self.read - {inputs.get('path')})
            self.messages.append({'role': 'tool', 'tool_call_id': tc.get('id'), 'content': serialized})
        self._proposed_dependencies = {}
        return (list(before), '\n'.join(errors), finished)

    def run(self):
        import json
        self.feedback = self.verify()[1]
        self.baseline_feedback = self.feedback
        self.compiled_before = not any((token in self.feedback.upper() for token in ('COMPILATION ERROR', 'CANNOT FIND SYMBOL')))
        self.plan()
        self.fresh()
        no_call_replies = 0
        while (self.args.max_rounds <= 0 or self.used < self.args.max_rounds) or (self.step < len(self.steps) and self.steps[self.step].get('kind') == 'verify'):
            if self.verify_step():
                no_call_replies = 0
                if self.step == len(self.steps):
                    return True
                else:
                    continue
            from focused_context import enabled
            # History size is handled by the token-budget compaction in ask(); resetting on a small
            # character count discarded every read each round and defeated the prompt cache.
            if self.idle >= 3:
                self.fresh('context reset after repeated reads or long history')
            reply_round = self.used
            if self.rejected_candidate is not None:
                record = self.rejected_candidate
                self.rejected_candidate = None
                repair_round = self.used
                try:
                    msg = repair_new(self, record)
                except ValueError as exc:
                    record['repair_error'] = str(exc)
                    # A source conflict rejected before ask must return to normal
                    # discovery, not spin forever without consuming the budget.
                    preserved = self.used > repair_round
                    if preserved:
                        self.rejected_candidate = record
                        no_call_replies = 0
                    self.feedback = record['error'] + '\nFocused repair rejected: ' + str(exc)
                    self.h.log_event('autonomy.focused_repair_rejected', {
                        'path': record['path'], 'error': str(exc), 'candidate_preserved': preserved,
                    })
                    self.fresh('repair arguments rejected')
                    continue
            else:
                if not getattr(self, '_prompt_dumped', False) and os.environ.get('HARNESS_JOB_DIR'):
                    # The first agent prompt, kept for diagnosis (what the model was actually told).
                    self._prompt_dumped = True
                    try:
                        (Path(os.environ['HARNESS_JOB_DIR']) / 'first-prompt.json').write_text(
                            json.dumps(self.messages, ensure_ascii=False, indent=1), encoding='utf-8')
                    except OSError:
                        pass
                msg = __import__('call_budget').ask_with_recovery(self)
            if isinstance(msg, dict) and not msg.get('role'):
                # Synthetic replies from repair helpers carry only content/tool_calls; the chat
                # template rejects a message without a role ("Unexpected message role").
                msg = {'role': 'assistant', **msg}
            self.messages.append(msg)
            prior_reads = set(self.read)
            prior_progress = self.progress
            (paths, error, finished) = self.batch(msg)
            executable = finished or bool(paths) or bool(msg.get('tool_calls') and not error)
            progressed = self.read != prior_reads or self.progress > prior_progress
            if self.used != reply_round or executable or progressed:
                no_call_replies = 0
            else:
                no_call_replies += 1
            if no_call_replies >= 3:
                detail = str(error or msg.get('content') or 'Empty reply')[:1200]
                self.feedback = 'Stopped after 3 consecutive replies without a model call or executable action: ' + detail
                self.h.log_event('autonomy.stalled', {
                    'reason': 'no_model_no_executable_reply', 'consecutive_replies': no_call_replies,
                    'step': self.step + 1, 'model_calls': self.used, 'error': detail,
                })
                return False
            from workflow_progress import stop_if_stalled, note_read_streak
            if not finished and not paths and not error and stop_if_stalled(self):
                return False
            if not finished and note_read_streak(self, msg, bool(paths)):
                self.feedback = 'Stopped: many responses in a row only read files without changing anything.'
                return False
            (checked, diag) = (None, '')
            if self.cp.pending:
                if not error:
                    (checked, diag) = self.verify()
                    if not checked:
                        error = diag or 'Checks failed'
                if error:
                    self.rejected_candidate = None
                    # A Java failure can need a migration or sibling class. A
                    # multi-file failure must retain access to normal file tools.
                    # The legacy repair tool can only repair one new frontend
                    # file. The focused context profile keeps ordinary tools
                    # and the whole rejected source for model-owned rewrites.
                    frontend_failed = (checked is False and
                                       self.last_check_results.get('frontend', {}).get('success') is False)
                    if len(self.cp._records) == 1 and frontend_failed:
                        candidate = next(({'path': path, 'source': data['expected'].decode('utf-8', 'replace'), 'error': error}
                            for path, data in self.cp._records.items()
                            if data.get('before') is None and isinstance(data.get('expected'), bytes)
                            and len(data['expected']) <= 12000 and path.startswith('frontend/')
                            and path.endswith(('.tsx', '.ts'))), None)
                        from focused_context import enabled
                        if candidate and enabled(self):
                            self.h.log_event('autonomy.strategy', {
                                'reason': 'new_file_repair_uses_standard_tools',
                                'path': candidate['path'], 'model_calls': 0,
                            })
                        else:
                            self.rejected_candidate = candidate
                    from focused_context import enabled
                    if enabled(self):
                        self.rejected_new_files.replace(self.cp._records, error)
                        rejected_context = ''
                    else:
                        rejected_context = rejected_new_file_context(self.cp._records)
                    self.memory.record(self.cp._records, error, self.compiled_before)
                    restored = self.cp.rollback()
                    self.h.log_event('autonomy.rollback', {'paths': restored, 'reason': error})
                    # The same failure again and again is a loop, not progress: stop instead of running for an hour.
                    key = re.sub(r'\d+', '#', str(error))[:300]
                    repeats = self.__dict__.setdefault('_failure_repeats', {})
                    repeats[key] = repeats.get(key, 0) + 1
                    if repeats[key] >= 4:
                        self.feedback = 'Stopped: the same check failed 4 times in a row with the same error.\n' + str(error)[:800]
                        self.h.log_event('autonomy.stalled', {'reason': 'same_failure_repeated', 'repeats': repeats[key], 'model_calls': self.used, 'error': str(error)[:300]})
                        return False
                    self.feedback = f'{error}\nRejected changes restored; reread actual files.'
                    if rejected_context:
                        self.feedback += f'\n\n{rejected_context}'
                    self.fresh('failed patch')
                    continue
                accepted_records = dict(self.cp._records)
                self.cp.commit()
                self.rejected_new_files.discard(accepted_records)
                from source_progress import remember_accepted
                remember_accepted(self, accepted_records)
                self.baseline_feedback = diag
                self.accepted = True
                self.idle = 0
                self.h.log_event('autonomy.accepted', {'step': self.step + 1, 'paths': paths})
                self.feedback = 'Patch passed selected checks'
                if getattr(getattr(self,'requirement_gate',None),'enabled',False):
                    self.steps[self.step]['kind']='verify'
                    self.h.log_event('autonomy.strategy', {'reason': 'automatic_requirement_verification', 'model_calls': 0})
                self.feedback = 'Patch passed selected checks'
                self.messages.append({'role': 'user', 'content': self.feedback})
            elif error and all(('READ SUSPENDED' in line or 'OUT OF SCOPE' in line) for line in error.splitlines() if line.strip()):
                # A refused read is guidance, not a failure: keep the context (and the files already
                # read) so the model can act on them; a rebuild would drop them and invite rereads.
                self.feedback = error
                continue
            elif error:
                # A failed tool call leaves the workspace unchanged, so the sources already in context are
                # still exact. Keep them (and the cached prompt prefix) and add the error instead of
                # rebuilding the whole context, which dropped every read and forced rereads.
                self.feedback = error
                self.h.log_event('autonomy.tool_error_feedback', {'error': error[:500], 'model_calls': 0})
                self.messages.append({'role': 'user', 'content': 'TOOL ERROR (workspace unchanged): ' + error[:4000]
                                      + '\nCorrect the call using the sources already in context; do not reread unchanged files.'})
                continue
            else:
                self.idle = 0 if self.read != prior_reads or self.progress > prior_progress else self.idle + 1
            if finished:
                gate_error = new_screen_error(self.h.workspace.root, self.args.task, self.initial_screens)
                if gate_error:
                    self.feedback = gate_error
                    self.messages.append({'role': 'user', 'content': gate_error})
                    continue
                current_step = self.steps[self.step]
                if not self.accepted and current_step.get('kind') == 'change':
                    self.messages.append({'role': 'user', 'content': 'Cannot finish change step without a verified mutation.'})
                    continue
                if checked is None:
                    (checked, diag) = self.verify()
                if not checked:
                    self.feedback = diag or 'Checks failed'
                    self.messages.append({'role': 'user', 'content': self.feedback})
                    continue
                self.h.log_event('autonomy.step_finished', {'step': self.step + 1, 'title': current_step['title']})
                self.step += 1
                if self.step == len(self.steps):
                    return True
                self.accepted = False
                self.feedback = 'Previous step verified; work on next step'
                self.fresh()
                continue
            if not finished and (not any((t.get('type') == 'function' for t in msg.get('tool_calls', [])))):
                self.messages.append({'role': 'user', 'content': 'Use tools to complete current step. Plain text is not a completed change.'})
        return False

    def apply(self, name, inputs, before):
        from seed_updates import seed_edits
        if name == 'update_seed_rows':
            return __import__('seed_executor').apply_seed(self, inputs, before)
        original_name = name
        if name in ('write_file', 'edit_file', 'apply_edits', 'apply_insertions', 'insert_text') and str(self.h.workspace.safe_path(inputs.get('path')).relative_to(self.h.workspace.root)) in self.initial_frontend_files and (getattr(self.args, 'edit_format', 'auto') not in ('diff', 'whole')):
            raise ValueError('Existing frontend source requires inspect_code action edit_ranges then apply_ast_edits; raw text or whole-file edits are disabled')
        if name == 'read_file':
            target = self.h.workspace.safe_path(inputs['path'])
            from focused_context import enabled
            if enabled(self):
                draft = self.rejected_new_files.read(str(target.relative_to(self.h.workspace.root)))
                if not target.exists() and draft is not None:
                    return draft  # Deliberately does not add this path to self.read.
                service = getattr(self.h, '_code_intelligence', None)
                if service is not None:
                    # Eviction makes a fresh full read necessary, even when
                    # the underlying bytes have not changed since an old read.
                    service.retain_reads(self.read)
                    if not service.allow_reads():
                        raise ValueError('Repeated unchanged source reads are blocked; inspect the retained source or edit it')
            if not target.is_file():
                raise ValueError(missing_path_message(self.h.workspace.root, inputs['path']))
        if name == 'isolate_spring_test':
            inputs = isolation_arguments(inputs, self.h.workspace.safe_path(inputs['path']).read_text())
            name = 'edit_file'
        if name == 'apply_edits':
            inputs = patch_arguments(inputs, self.h.workspace.safe_path(inputs['path']).read_text())
            name = 'edit_file'
        if name == 'apply_insertions':
            inputs = batch_arguments(inputs, self.h.workspace.safe_path(inputs['path']).read_text())
            name = 'edit_file'
        if name == 'add_java_annotations':
            inputs = annotation_arguments(inputs, self.h.workspace.safe_path(inputs['path']).read_text())
            name = 'edit_file'
        if name == 'apply_ast_edits':
            from ast_editing import editor
            result = editor(self.h).apply(inputs['path'], inputs.get('snapshot_id'), inputs['edits'])
            inputs = {k: result[k] for k in ('path', 'old_text', 'new_text')}
            name = 'edit_file'
        if name not in ('insert_text', 'write_file', 'edit_file', 'delete_file'):
            result = self.h._execute_tool(name, inputs)
            if name == 'list_files' and (not result.get('error')):
                path = inputs['path']
                files = result.get('files', [])
                if self.listed.get(path) != files:
                    self.progress += 1
                    self.listed[path] = files
            if name == 'read_file' and (not result.get('error')):
                from focused_context import enabled
                if not enabled(self):
                    self.read.add(inputs['path'])
                else:
                    from source_progress import current_bytes
                    content = result.get('content')
                    if not result.get('unchanged') and result.get('exists') is not False and isinstance(content, str) and current_bytes(self, inputs['path']) == content.encode('utf-8'):
                        self.read.add(inputs['path'])
                        self._remember_migration_read(inputs['path'], content.encode('utf-8'))
                return result
            return result
        if name == 'insert_text':
            inputs = insert_arguments(inputs)
            name = 'edit_file'
        path = inputs['path']
        target = self.h.workspace.safe_path(path)
        exists = target.exists()
        if name in ('write_file', 'edit_file', 'delete_file'):
            migration = False
            if target.suffix == '.sql':
                relative = target.relative_to(self.h.workspace.root).as_posix()
                migration = relative.startswith('backend/src/main/resources/db/migration/')
            if migration and exists:
                from workflow_policy import get_policy
                ledger = getattr(self, '_job_migrations', None)
                if ledger is None or not ledger.enabled or not get_policy(self).job_created_migration_edits:
                    raise ValueError('existing Flyway migrations cannot be edited or deleted: create a NEW next-version migration with UPDATE existing seed IDs, never repair checksums.')
                ledger.require_edit(path, target.read_bytes(),
                    getattr(self, '_migration_full_reads', {}).get(path) if path in self.read else None, name)
            if exists and path not in self.read:
                raise ValueError('Read existing file first')
            current = target.read_bytes() if exists else None
            candidate = None
            if name == 'write_file':
                candidate = inputs['content'].encode('utf8')
            elif name == 'delete_file':
                candidate = None
            elif name == 'edit_file':
                current_text = current.decode('utf8') if current else ''
                (old, new) = (inputs['old_text'], inputs['new_text'])
                if (len(old) > 5000 or len(new) > 5000) and original_name not in ('apply_edits', 'apply_insertions', 'add_java_annotations', 'apply_ast_edits'):
                    raise ValueError('Use a small exact edit')
                if old and current_text.count(old) == 1:
                    candidate = current_text.replace(old, new).encode('utf8')
                else:
                    candidate = current
            if name == 'write_file' and current is not None and (candidate == current):
                return {'status': 'unchanged', 'hint': 'Already current. Do not rewrite this file; finish if complete, or create the requested separate screen.'}
            proposed = getattr(self, '_proposed_dependencies', {})
            if proposed:
                self.memory.guard(path, current, candidate, name, dependency_overrides=proposed)
            else:
                self.memory.guard(path, current, candidate, name)
            if path not in before:
                before[path] = current.decode('utf8') if current is not None else ''
            self.cp.stage(path)
            try:
                result = self.h._execute_tool(name, inputs)
            finally:
                self.cp.record(path)
            ledger = getattr(self, '_job_migrations', None)
            if migration and ledger is not None and ledger.enabled and not result.get('error'):
                ledger.record_write(path, current, candidate)
            if path.endswith('.java') and '@Test' in before[path] and (not result.get('error')):
                after_text = target.read_text() if target.exists() else ''

                def get_lines(txt):
                    return [l.strip() for l in txt.splitlines()]
                old_lines = get_lines(before[path])
                new_lines = get_lines(after_text)
                old_asserts = [l for l in old_lines if '.andExpect(' in l]
                new_asserts = [l for l in new_lines if '.andExpect(' in l]
                old_tests = before[path].count('@Test')
                new_tests = after_text.count('@Test')
                if not __import__('runtime_policy').preserve_java_assertions(before[path], after_text, self.args.task):
                    return {'error': 'Existing Java assertions and test count must be preserved'}
            return result

    def verify_step(self) -> bool:
        current_step = self.steps[self.step]
        if current_step['kind'] != 'verify':
            return False
        (passed, diag) = self.verify()
        gate_error = new_screen_error(self.h.workspace.root, self.args.task, self.initial_screens)
        if gate_error:
            (passed, diag) = (False, gate_error)
        if passed:
            self.h.log_event('autonomy.step_finished', {'step': self.step + 1, 'title': current_step['title']})
            self.step += 1
            self.accepted = False
            if self.step < len(self.steps):
                self.feedback = 'Verification passed; work on next step'
                self.fresh()
            return True
        self.steps[self.step]['kind'] = 'change'
        self.accepted = False
        self.feedback = f'{diag}\nFix failed checks before finishing this step.'
        self.fresh('verification failed')
        return False

    def tools(self):
        from seed_updates import SEED_TOOL, is_seed_request
        native = self.h._get_tool_schemas()
        from focused_context import enabled
        blocked = set() if enabled(self) else set(getattr(self, 'blocked_tools', set()))
        if not enabled(self) and getattr(self, 'focused', False) and (self.read or self.listed):
            blocked.add('list_files')
        if 'backend' in self.modes and is_seed_request(self.args.task):
            allowed_names = {'read_file', 'list_files', 'finish', 'SEED_TOOL'}
            filtered_native = [t for t in native if t['function']['name'] in allowed_names and t['function']['name'] not in blocked]
            return filtered_native + [SEED_TOOL]
        extras = [INSERT_TOOL, BATCH_TOOL, PATCH_TOOL]
        if 'backend' in self.modes:
            extras.append(ANNOTATION_TOOL)
        if 'backend' in self.modes:
            extras.append(ISOLATION_TOOL)
        normalized_extras = []
        for extra in extras:
            if extra.get('type') == 'function' and 'function' in extra:
                normalized_extras.append(extra)
            else:
                normalized_extras.append({'type': 'function', 'function': extra})
        return [t for t in native + normalized_extras if t['function']['name'] not in blocked]

    def current_context(self) -> tuple[str, set[str]]:
        from call_budget import snapshot
        return snapshot(self)

    def rejected_new_context(self):
        from focused_context import enabled
        return self.rejected_new_files.context() if enabled(self) else ''

    def frontend_context(self) -> str:
        from runtime_policy import frontend_contract
        return frontend_contract(self.modes)

    def backend_context(self) -> str:
        import json, re
        from pathlib import Path
        if getattr(self, '_backend_context_cache', None):
            return self._backend_context_cache
        if 'backend' not in self.modes:
            return ''
        reference = getattr(self, '_new_api_reference', lambda: '')()
        if reference:
            self._backend_context_cache = reference
            return reference
        from workflow_progress import checker_owned_fixtures
        if checker_owned_fixtures(self):
            folder = self.h.workspace.root / 'backend/src/main/resources/db/migration'
            paths = sorted(str(path.relative_to(self.h.workspace.root)) for path in folder.glob('V*.sql')
                           if path.is_file() and not path.is_symlink())
            result = ('CHECKER-OWNED VERIFICATION FIXTURES: Baseline schema, migrations, and existing application rows must be preserved. '
                      'The trusted verifier creates its own fixtures in fresh owned test databases. Those fixtures are not application sample rows. '
                      'Do not add application sample data unless explicitly requested. Read relevant schema migrations when needed. '
                      'Actual Flyway paths: ' + json.dumps(paths, ensure_ascii=False))[:4500]
            self._backend_context_cache = result
            return result
        context_parts = ['Actual locally cached APIs:']
        api_path = Path.home() / '.local/share/mlx-server/java-api/spring-test-api.json'
        try:
            if api_path.is_file():
                with api_path.open('r') as f:
                    data = json.load(f)
                classes = data.get('classes', {})
                sigs = data.get('signatures', {})
                targets = ['Transactional', 'Sql', 'AutoConfigureMockMvc', 'Rollback']
                found_facts = []
                for t in targets:
                    fqns = classes.get(t, [])
                    if fqns:
                        found_facts.append(f"{t}: {', '.join(fqns)}")
                    sig = sigs.get(t)
                    if sig:
                        found_facts.append(f'{t} sig: {sig}')
                if found_facts:
                    context_parts.append(' '.join(found_facts))
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        context_parts.append('Preserve test assertions, seeded rows, and production code when fixing fixture isolation. Test transactions roll back new writes but do not remove old committed fixtures. Scoped SQL cleanup for known test-created rows can run inside the same test transaction before each test; never delete the seed table wholesale. Fully qualified Java annotation names avoid accidental import changes. Prefer add_java_annotations with fully qualified class names to add ALL required transaction and scoped SQL annotations together; this retains every import and inserts them before the class automatically. When using isolate_spring_test, prefer a raw single DELETE WHERE cleanup_sql matching known test-created rows. The tool automatically creates valid Java strings and transaction annotations; do not delete/reinsert seeded fixtures.')
        try:
            match = re.search('backend/src/test/[^\\s`]+?\\.java', self.args.task)
            if match:
                rel_path = match.group(0)
                safe_path = self.h.workspace.safe_path(rel_path)
                if safe_path.is_file():
                    self.read.add(str(rel_path))
        except (OSError, ValueError):
            pass
        resources = self.h.workspace.root / 'backend/src/test/resources'
        names = [str(p.relative_to(resources)) for p in resources.rglob('*.sql')][:20] if resources.is_dir() else []
        context_parts.insert(0, 'Actual test SQL resources: ' + str(names) + '. Prefer inline Sql.statements for scoped cleanup; never invent a SQL resource path.')
        migration_dir = self.h.workspace.root / 'backend/src/main/resources/db/migration'
        migration_files = sorted(migration_dir.glob('V*.sql'))
        versions = [int(re.search('V(\\d+)', f.name).group(1)) for f in migration_files if re.search('V(\\d+)', f.name)]
        next_v = max(versions) + 1 if versions else 1
        seed_sql = ' '.join((p.read_text(encoding='utf-8') for p in migration_files))[:2200]
        contract = f'CONTRACT: Existing migration paths are immutable. NEW migration path must begin backend/src/main/resources/db/migration/V{next_v}__. Seed examples must use UPDATE by existing IDs and keep count. Update existing exact-name test assertions consistently. Actual test files: backend/src/test/java/**/*Test*.java.'
        context_parts.insert(0, contract)
        context_parts.insert(0, 'Existing schema and seed SQL; preserve these rows and their IDs: ' + seed_sql)
        result = ' '.join(context_parts)[:4500]
        self._backend_context_cache = result
        return result

    # A complete existing master-data API (create/read/update/delete) shown as the example for new APIs.
    REFERENCE_API = ['backend/src/main/resources/db/migration/V6__create_items_table.sql',
                     'backend/src/main/java/com/example/localinventory/Item.java',
                     'backend/src/main/java/com/example/localinventory/ItemRepository.java',
                     'backend/src/main/java/com/example/localinventory/ItemController.java']

    def _new_api_reference(self):
        """For a task that adds a new backend API: a short brief plus one complete existing example."""
        import re
        task = str(self.args.task)
        if not re.search(r'API|엔티티|테이블|컨트롤러|entity|controller', task, re.I) or re.search(r'테스트|test|fixture', task, re.I):
            return ''
        root = self.h.workspace.root
        files = [rel for rel in self.REFERENCE_API if (root / rel).is_file()]
        if len(files) < 3:
            return ''
        folder = root / 'backend/src/main/resources/db/migration'
        versions = [int(m.group(1)) for p in folder.glob('V*.sql') for m in [re.match(r'V(\d+)__', p.name)] if m]
        next_v = max(versions, default=0) + 1
        text = ('새 API는 아래 품목 API와 같은 방식으로 만든다: 마이그레이션 → 엔티티 → 저장소 → 컨트롤러, 같은 패키지. '
                f'새 마이그레이션 파일 이름은 V{next_v}__ 로 시작하고, 기존 마이그레이션 파일은 고치지 않는다. '
                '엔티티는 Item처럼 AuditedEntity를 상속한다. 주의: 주어진 V6 품목 마이그레이션은 옛 파일이라 등록/수정자 열이 빠져 있다. '
                '새 CREATE TABLE에는 업무 열 뒤에 반드시 다음 네 열을 넣는다(없으면 빌드 전에 거절된다): '
                'created_by VARCHAR(100), created_at TIMESTAMP, updated_by VARCHAR(100), updated_at TIMESTAMP. '
                '선택 항목(단위·구분·상태 등)은 코드 값을 담는 VARCHAR(50) 열 하나로 두고 따로 코드 테이블을 만들지 않는다. '
                '이 네 값은 저장할 때 자동으로 채워지므로 컨트롤러나 요청 본문에서 다루지 않는다. '
                '로그인한 사용자는 /api/** 를 쓸 수 있으므로 보안 설정이나 화면 정의(DefinedScreen) 파일은 건드리지 않는다. '
                '참고할 품목 API 파일은 CURRENT FILE로 이미 주어져 있다: ' + ', '.join(files) + '. 다시 읽지 말고 필요한 파일을 바로 새로 만든다.')
        self.read.update(files)
        return text

    def reject_repeat(self, name, inputs, error):
        if name not in ('write_file', 'edit_file', 'apply_edits', 'apply_insertions', 'insert_text', 'add_java_annotations', 'isolate_spring_test'):
            return
        self.failed_calls = getattr(self, 'failed_calls', {})
        key = name + '|' + json.dumps(inputs, sort_keys=True, ensure_ascii=False)
        count = self.failed_calls.get(key, 0) + 1
        self.failed_calls[key] = count
        if count >= 2:
            self.h.log_event('autonomy.strategy', {'repeated_tool': name, 'path': inputs.get('path'),
                'reason': 'same rejected operation repeated; tool remains available for different files or corrected arguments and dependencies'})
        return
from runner_extensions import extend_runner
from context_budget import extend_context
from completion_runner import extend_completion
def _legacy_context(self, sys_msg, focused_context):
    sys_msg += ' ' + self.frontend_context()
    sys_msg += ' ' + self.backend_context()
    sys_msg += ' ' + (project_context(self.h.workspace.root, scope=self.modes) if focused_context else project_context(self.h.workspace.root))
    if any(mode in self.modes for mode in ('frontend', 'framework')):
        from component_catalog import context_for_task
        sys_msg += context_for_task(self)
        sys_msg += ' Prefer composing suitable retrieved components. Keep business-specific fields, API adapters and payload mapping in the screen. Use search_components for a different pattern; create only missing pieces and register a *.component.json descriptor beside reusable source.'
    from seed_updates import is_seed_request
    from workflow_progress import checker_owned_fixtures
    checker_fixtures = checker_owned_fixtures(self)
    if 'backend' in self.modes and is_seed_request(self.args.task):
        sys_msg += '\n\nSeed Update Guide: Use update_seed_rows for requested sample rows (include original id, old_values, and new values). To replace a complete set, request a replacement. No raw SQL. Tool creates migration and aligns test values atomically; read actual migration first to obtain exact old values.'
    if checker_fixtures:
        sys_msg += ' Preserve baseline schema, migrations, and application rows. Checker fixtures belong to fresh owned verification databases; do not reproduce them as application sample data. Create application sample rows only when the task explicitly requests them. Job-created migration edits follow the trusted workflow policy.'
    elif not focused_context or 'backend' in self.modes:
        sys_msg += ' For schema and sample-data work use the actual listed backend resource and Flyway paths. Never invent data.sql or schema.sql. Existing applied V*.sql are immutable; add the next version migration and preserve seed row IDs and count. When user explicitly changes example names, update exact test expected names to the new values without removing assertions or changing validation behavior.'
    sys_msg += ' Use search_code before guessing file paths. exact mode finds known identifiers or API routes; hybrid mode finds behavior described in words. Read returned source files before editing. Avoid repeated searches once the relevant source is provided.'
    if not focused_context and self.args.ponytail in ['full', 'ultra']:
        path = os.environ.get('PONYTAIL_SKILL_PATH', os.path.expanduser('~/.local/share/mlx-server/skills/ponytail/SKILL.md'))
        if os.path.exists(path):
            with open(path, 'r') as f:
                sys_msg += f'\n\n{f.read()[:12000]}'
    return sys_msg

def _plain_brief(self, approach):
    """Queue items get a short brief, the way a person hands over a task: what, where, when done."""
    text = f'할 일: {self.args.task}\n'
    if approach:
        text += f'방향: {approach[:600]}\n'
    text += ('필요한 파일만 읽고 바로 고치거나 새로 만든다. 테스트를 약하게 바꾸지 않는다. '
             '검사가 통과하면 finish를 호출한다.\n')
    if 'frontend' in self.modes or 'framework' in self.modes:
        text += ('기존 .tsx 파일은 edit_file 로 고친다(old_text 는 파일의 해당 줄들 그대로). 새 파일은 write_file로 만든다.\n'
                 if getattr(self, '_plain_edits_only', False) else
                 '기존 .tsx 파일은 apply_ast_edits로 고친다(제공된 AST ID 사용). 새 파일은 write_file로 만든다.\n')
        screen = _new_screen_brief(self)
        if screen:
            text += screen
        else:
            text += project_context(self.h.workspace.root, scope=self.modes)
            from component_catalog import context_for_task
            text += context_for_task(self)
    if 'backend' in self.modes:
        text += '\n' + self.backend_context()
    # Standard tasks: the field sheet the checks were built from (names, labels, required marks).
    text += getattr(self, '_field_sheet_note', '')
    return text


REFERENCE_SCREEN = 'frontend/src/screens/ItemMaster.tsx'


def _new_screen_brief(self):
    """A task that adds a new screen: how screens are added, one complete example screen, the usable APIs."""
    import re
    root = self.h.workspace.root
    task = str(self.args.task) + ' ' + os.environ.get('HARNESS_TASK_APPROACH', '')
    if not re.search(r'화면|screen', task, re.I) or not (root / REFERENCE_SCREEN).is_file():
        return ''
    titles, codes = [], []
    for path in (root / 'frontend/src/screens').glob('*.tsx'):
        source = path.read_text(encoding='utf-8')
        titles += re.findall(r"title:\s*'([^']+)'", source)[:1]
        codes += re.findall(r"code:\s*'([A-Z]{3}\d{4})'", source)[:1]
    if any(t and t in str(self.args.task) for t in titles):
        return ''  # an existing screen is being changed, not a new one added
    apis = []
    for path in (root / 'backend/src/main/java').rglob('*Controller.java'):
        m = re.search(r'@RequestMapping\("(/api/[^"]+)"\)', path.read_text(encoding='utf-8'))
        if m and not m.group(1).startswith(('/api/auth', '/api/spec', '/api/screens')):
            apis.append(f'{m.group(1)} ({path.name})')
    from framework_docs import usage
    # The sections a screen author needs, in document order (API.txt is split so each stays small).
    docs = usage(root, ['BusinessWorkspace', 'QueryPanel', 'RecordGrid', 'RecordEditor', 'ScreenActions', 'FieldDefinition',
                        'useCommonCodes', 'exportRows', 'keywords', 'TextArea'], budget=11000)
    self.read.add(REFERENCE_SCREEN)
    used = ', '.join(sorted(codes)) or '없음'
    return ('새 화면은 frontend/src/screens/<이름>.tsx 파일 하나로 만든다. export const meta = { code, title, icon, keywords } 와 default 컴포넌트가 있으면 '
            '프로그램으로 자동 등록되어 메뉴(관리자에게는 미편성 프로그램)와 사이드바 검색에 나온다. '
            "keywords에는 사용자가 이 화면을 찾을 때 칠 만한 낱말을 2개 이상 적는다(예: 사원 등록이면 ['사원', '직원', '인사']). "
            '메뉴 배치·권한·시스템명은 공통 시스템이 관리하므로 코드로 건드리지 않는다. App.tsx, Home.tsx, workspace 폴더는 고치지 않는다. '
            f'code는 영문 3자리+숫자 4자리이고 이미 쓰는 code({used})와 겹치지 않게 한다. '
            f'구성은 CURRENT FILE로 주어진 {REFERENCE_SCREEN}(품목 등록)과 같게 한다: BusinessWorkspace에 조회 조건, 그리드, 편집 패널, 공통 버튼. '
            '이 파일의 구조(toRow, failure, handleQuery/handleSave/handleNew/handleDelete, 저장 후 재조회)를 그대로 따르고 '
            '필드와 API 주소만 이 화면에 맞게 바꾼다. 관리자가 값을 바꿀 수 있어야 하는 선택 항목(단위, 구분, 상태 등)은 '
            "선택지를 코드에 적지 말고 필드에 codeGroup:'<공통 코드 그룹>'을 준다. 엑셀·인쇄·즐겨찾기·탭·권한은 프레임워크에 있으므로 만들지 않는다.\n"

            '쓸 수 있는 API: ' + '; '.join(sorted(apis)) + '\n\n'
            'FRAMEWORK USAGE (frontend/src/framework/API.txt):\n' + docs + '\n')


from divide_runner import extend_divide
from candidate_repair import extend_candidate
from java_member_focus import extend_java_members
from ast_recovery import extend_recovery
from output_recovery import extend_output
Runner = extend_divide(extend_java_members(extend_recovery(extend_candidate(extend_context(extend_output(extend_completion(extend_runner(Runner))))))))
