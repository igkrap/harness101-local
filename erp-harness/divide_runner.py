import json
import os
from divide_plan import create
from divide_execute import execute

def extend_divide(base):
    class Divided(base):
        def __init__(self, args, harness_class):
            self._division_harness_class = harness_class
            super().__init__(args, harness_class)

        def run(self):
            gate = getattr(self, "requirement_gate", None)
            if gate is None or not gate.enabled or not hasattr(gate, "frozen_contract"):
                return super().run()

            _, feedback = self.verify()
            self.feedback = feedback
            self.baseline_feedback = feedback
            self.compiled_before = not any(
                token in feedback.upper() 
                for token in ['COMPILATION ERROR', 'CANNOT FIND SYMBOL']
            )

            gate.prepare()
            contract = json.loads(gate.frozen_contract)
            criteria = contract['criteria']
            requirements = contract['requirements']
            ops = {c['check']['op'] for c in criteria}

            # A task-queue item is already one verifiable slice; dividing it again only adds a fragile planning call.
            if os.environ.get('HARNESS_QUEUE_ITEM') == '1':
                return super().run()
            if len(criteria) < 2 or (len(requirements) < 2 and not ('api' in ops and len(ops) > 1)):
                return super().run()

            stages = create(self)
            self.steps = stages + [{'id': 'integration', 'title': '전체 결과 검증', 'kind': 'verify'}]
            return execute(self, base, self._division_harness_class, stages)

    return Divided
