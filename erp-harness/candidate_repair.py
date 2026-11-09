import copy
import json
from pathlib import Path
from candidate_tools import TOOLS
from candidate_patch import revise
from ast_editing import editor
from candidate_focus import ask_candidate
from candidate_conflict import resolve_conflict
from candidate_duplicate_reflex import resolve_duplicate

def extend_candidate(base):

    class CandidateRepair(base):

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._ast_attempts = []
            self._failed_ast_candidate = None

        def batch(self, message):
            self._ast_attempts = []
            return super().batch(message)

        def apply(self, name, inputs, before=None):
            if before is None:
                before = {}
            if name == 'repair_ast_candidate':
                if self.cp.pending or not self._failed_ast_candidate:
                    return {'status': 'error', 'error': 'No pending proposal to repair'}
                merged = revise(self._failed_ast_candidate, inputs.get('changes', []), inputs.get('remove', []))
                self._failed_ast_candidate = merged
                ast_inputs = {'path': merged['path'], 'snapshot_id': merged['snapshot_id'], 'edits': merged['edits']}
                return self.apply('apply_ast_edits', ast_inputs, before)
            if name == 'discard_ast_candidate':
                if self.cp.pending:
                    return {'status': 'error', 'error': 'Cannot discard while pending'}
                self._failed_ast_candidate = None
                self._division_ast_focus = False
                return {'status': 'discarded; source unchanged'}
            if name == 'apply_ast_edits':
                root = self.h.workspace.root
                path_obj = self.h.workspace.safe_path(inputs['path'])
                snapshot = editor(self.h).snapshot(inputs['path'])
                capture = {'path': str(path_obj.relative_to(root)), 'snapshot_id': snapshot['snapshot_id'], 'source_hash': snapshot['source_hash'], 'edits': copy.deepcopy(inputs['edits'])}
                result = super().apply(name, inputs, before)
                if not result.get('error'):
                    self._ast_attempts.append(capture)
                return result
            return super().apply(name, inputs, before)

        def verify(self):
            (ok, feedback) = super().verify()
            if self.cp.pending:
                if ok:
                    self._failed_ast_candidate = None
                elif len(self._ast_attempts) == 1:
                    attempt = self._ast_attempts[0]
                    attempt_paths = {attempt['path']}
                    if attempt_paths == set(self.cp._records.keys()):
                        if all((isinstance(self.cp._records[p].get('before'), bytes) for p in attempt_paths)):
                            if len(json.dumps(attempt)) <= 18000:
                                self._failed_ast_candidate = copy.deepcopy(attempt)
                                self.h.log_event('autonomy.strategy', {'reason': 'Retained failed AST batch; revise faulty nodes while preserving companion edits', 'path': attempt['path'], 'node_ids': [e.get('node_id') for e in attempt['edits']]})
                            else:
                                self._failed_ast_candidate = None
                        else:
                            self._failed_ast_candidate = None
                    else:
                        self._failed_ast_candidate = None
                else:
                    self._failed_ast_candidate = None
            return (ok, feedback)

        def fresh(self, reason=''):
            super().fresh(reason)
            if self._failed_ast_candidate:
                prompt_suffix = '\nFAILED ATOMIC AST PROPOSAL (all source was restored; edit ONLY faulty nodes with repair_ast_candidate, every unchanged companion operation is automatically retained. Do not fix just the handler and lose the JSX wiring. Use discard_ast_candidate to abandon. Current source/snapshot IDs above stay authoritative):\n'
                self.messages.append({'role': 'user', 'content': prompt_suffix + json.dumps(self._failed_ast_candidate, ensure_ascii=False)})

        def ask(self, messages, tools=None):
            if messages is self.messages and not self.cp.pending and not self._failed_ast_candidate:
                gate = getattr(self, 'requirement_gate', None)
                report = getattr(gate, 'last_report', {})
                failed = [r for r in report.get('results', []) if r.get('status') != 'passed' and str(r.get('reason', '')).startswith('Native UI requirement:')]
                if failed:
                    paths = getattr(gate, 'stage', {}).get('paths', [])
                    target = next((p for p in paths if str(p).startswith('frontend/src/') and str(p).endswith('.tsx')), None)
                    if target:
                        snap = editor(self.h).snapshot(target)
                        self._failed_ast_candidate = {'path': target, 'snapshot_id': snap['snapshot_id'], 'source_hash': snap['source_hash'], 'edits': []}
                        self.h.log_event('autonomy.strategy', {'reason': 'native_requirement_repair', 'path': target, 'failed_criterion_ids': [r.get('id') for r in failed], 'model_calls': 0})
            if messages is self.messages and self._failed_ast_candidate and not self.cp.pending:
                callback = lambda m,t: super(CandidateRepair,self).ask(m,t)
                resolution = resolve_conflict(self, self._failed_ast_candidate, callback)
                if resolution is not None:
                    return resolution
                duplicate_resolution = resolve_duplicate(self, self._failed_ast_candidate)
                if duplicate_resolution is not None:
                    return duplicate_resolution
                return ask_candidate(self, callback)
            return super().ask(messages, tools)

        def tools(self):
            if self._failed_ast_candidate:
                return copy.deepcopy(TOOLS)
            return super().tools()
    return CandidateRepair
