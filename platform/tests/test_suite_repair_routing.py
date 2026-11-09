import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
from divide_execute import repair_target
from divide_gate import StageGate


class SuiteRepairRoutingTests(unittest.TestCase):
    def test_backend_failure_without_api_criterion_gets_backend_scope_and_keeps_ui_proofs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            java = root / 'backend/src/main/java/Controller.java'
            java.parent.mkdir(parents=True)
            java.write_text('class Controller {}')
            test = root / 'backend/src/test/java/ControllerTest.java'
            test.parent.mkdir(parents=True)
            test.write_text('class ControllerTest {}')
            stages = [{'id': 'screen', 'domain': 'frontend', 'criterion_ids': ['C1'],
                       'paths': ['frontend/src/Screen.tsx']}]
            parent = SimpleNamespace(h=SimpleNamespace(workspace=SimpleNamespace(root=root), log_event=Mock()),
                last_check_results={'frontend': {'success': True}, 'backend': {'success': False}})
            target = repair_target(parent, stages, [])
            stage = stages[target]
            self.assertEqual(stage['domain'], 'backend')
            self.assertEqual(stage['paths'], ['backend/src/main/java/Controller.java'])
            self.assertEqual(stage['references'], ['backend/src/test/java/ControllerTest.java'])
            self.assertEqual(stage['depends_on'], ['screen'])
            self.assertEqual(repair_target(parent, stages, []), target)
            self.assertEqual(len(stages), 2)
            contract = {'task': '화면 구성', 'criteria': [{'id': 'C1', 'check': {'op': 'visible', 'selector': '#screen'}}]}
            gate_parent = SimpleNamespace(frozen_contract=json.dumps(contract), contract_hash='hash',
                artifact_dir=root, _probe=Mock(return_value={'success': False,
                    'results': [{'id': 'C1', 'status': 'failed', 'reason': 'screen regressed'}]}))
            child = SimpleNamespace(h=SimpleNamespace(log_event=Mock()))
            gate = StageGate(gate_parent, child, stage, ['C1'], [])
            self.assertFalse(gate.verify()['success'])
            self.assertEqual(gate.selected(), contract['criteria'])

    def test_passing_suites_still_route_to_failed_criterion_owner(self):
        parent = SimpleNamespace(last_check_results={'backend': {'success': True}})
        stages = [{'domain': 'backend', 'criterion_ids': ['C1']},
                  {'domain': 'frontend', 'criterion_ids': ['C2']}]
        self.assertEqual(repair_target(parent, stages, ['C2']), 1)
