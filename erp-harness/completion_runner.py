import json
from verification_gate import Gate, TOOLS

def extend_completion(base):

    class Completed(base):

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.requirement_gate = Gate(self)

        def plan(self):
            self.requirement_gate.prepare()
            return super().plan()

        def fresh(self, reason=''):
            original_context = super().fresh(reason)
            if self.requirement_gate.enabled:
                for msg in self.messages:
                    if msg.get('role') == 'user':
                        msg['content'] += '\nIMMUTABLE COMPLETION CONTRACT:\n' + self.requirement_gate.context()
            return original_context

        def tools(self):
            if self.requirement_gate.enabled:
                return super().tools() + TOOLS
            return super().tools()

        def apply(self, name, inputs, before=None):
            if not self.requirement_gate.enabled:
                if name in ('inspect_layout', 'verify_requirements'):
                    return {'error': 'Requirement gate not prepared'}
            if name == 'inspect_layout':
                res = self.requirement_gate.inspect()
                self.h.log_event('inspected', res)
                return res
            elif name == 'verify_requirements':
                res = self.requirement_gate.verify()
                self.h.log_event('verification', res)
                return res
            return super().apply(name, inputs, before)

        def batch(self, message):
            (paths, error, finished) = super().batch(message)
            if finished and any((m in self.modes for m in ('frontend', 'framework', 'backend'))):
                cp = getattr(self, 'cp', None)
                if finished and getattr(cp, 'pending', False):
                    self.steps[self.step]['kind'] = 'verify'
                    self.messages.append({'role': 'user', 'content': 'After patch checks commit, the harness will verify completion without another model call.'})
                    return (paths, error, False)
                if not self.requirement_gate.enabled:
                    report = {'success': False, 'error': 'Requirement gate not prepared'}
                else:
                    report = self.requirement_gate.verify()
                if not report.get('success') is True:
                    finished = False
                    self.feedback = json.dumps(report, ensure_ascii=False)
                    self.messages.append({'role': 'user', 'content': 'Completion blocked. Fix unmet criteria:\n' + self.feedback})
            return (paths, error, finished)

        def verify_step(self):
            if self.step >= len(self.steps):
                return False
            current_kind = self.steps[self.step].get('kind')
            if current_kind != 'verify':
                return False
            if self.requirement_gate.enabled:
                report = self.requirement_gate.verify()
                if not report.get('success') is True:
                    self.steps[self.step]['kind'] = 'change'
                    self.feedback = json.dumps(report, ensure_ascii=False)
                    from focused_context import enabled
                    if not enabled(self):
                        # Multi-file (e.g. backend) runs rebuild the context so the committed-progress
                        # anchor lists every current file again.
                        self.fresh('completion evidence missing')
                        return False
                    # Focused screen runs: keep the context: the accepted change and the sources are still in it. Rebuilding
                    # dropped them and made the model reread the whole screen after every failed check.
                    criteria = {c.get('id'): c for c in json.loads(self.requirement_gate.frozen_contract).get('criteria', [])} \
                        if getattr(self.requirement_gate, 'frozen_contract', None) else {}
                    failed = [{'id': r.get('id'), 'description': criteria.get(r.get('id'), {}).get('description'),
                               'check': criteria.get(r.get('id'), {}).get('check'), 'reason': str(r.get('reason', ''))[:700]}
                              for r in report.get('results', []) if r.get('status') != 'passed']
                    self.h.log_event('autonomy.verification_feedback', {'failed': [f['id'] for f in failed], 'model_calls': 0})
                    self.messages.append({'role': 'user', 'content': 'BROWSER VERIFICATION FAILED for the accepted change (still applied). '
                                          'Fix the code so these criteria pass; the DIAGNOSTIC explains the observed state. '
                                          'Do not reread files already in context; use inspect_code edit_ranges for current edit IDs.\n'
                                          + json.dumps(failed, ensure_ascii=False)})
                    return False
            elif any((m in self.modes for m in ('frontend', 'backend'))):
                self.feedback = 'Completion blocked: No requirement gate enabled.'
                self.messages.append({'role': 'user', 'content': self.feedback})
                return False
            return super().verify_step()
    return Completed
