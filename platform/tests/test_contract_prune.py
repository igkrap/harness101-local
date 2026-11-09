"""A reviewer-rejected extra criterion is dropped (after re-review) instead of blocking the run."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
import verification_gate

TASK = "품목 등록 화면 결과 그리드의 '비고' 열 제목을 '메모'로 바꿔줘"
CONTRACT = json.loads(r'''{"version": 1, "task": "품목 등록 화면 결과 그리드의 '비고' 열 제목을 '메모'로 바꿔줘", "requirements": [{"id": "R1", "description": "품목 등록 화면 결과 그리드의 '비고' 열 제목을 '메모'로 바꿔줘"}], "criteria": [{"id": "C1", "requirement_id": "R1", "description": "결과 그리드의 '비고' 열 제목이 '메모'로 변경됨", "check": {"op": "text", "selector": "table[aria-label='결과 목록'] th:has-text('메모')", "contains": "메모"}}, {"id": "C2", "requirement_id": "R1", "description": "결과 그리드의 '비고' 열 제목이 더 이상 존재하지 않음", "check": {"op": "absent", "selector": "table[aria-label='결과 목록'] th:has-text('비고')"}}]}''')


class ContractPruneTests(unittest.TestCase):
    def gate(self):
        return SimpleNamespace(runner=SimpleNamespace(h=SimpleNamespace(log_event=Mock())),
                               _require_unique_selectors=lambda parsed: None)

    def prune(self, gate, rejected_ids, second):
        issues = [{'criterion_id': i, 'reason': 'extra'} for i in rejected_ids]
        with patch('requirement_review.review', return_value=second):
            return verification_gate.Gate._prune_rejected(gate, TASK, CONTRACT, {'approved': False, 'issues': issues})

    def test_rejected_extra_criterion_is_removed_when_rereview_approves(self):
        gate = self.gate()
        parsed, review = self.prune(gate, ['C2'], {'approved': True, 'issues': []})
        self.assertEqual([c['id'] for c in parsed['criteria']], ['C1'])
        self.assertTrue(review['approved'])
        self.assertEqual(gate.runner.h.log_event.call_args.args[0], 'requirement.contract_pruned')

    def test_pruning_never_bypasses_the_reviewer_or_empties_the_contract(self):
        self.assertIsNone(self.prune(self.gate(), ['C2'], {'approved': False, 'issues': [{'criterion_id': 'C1', 'reason': 'x'}]}))
        self.assertIsNone(self.prune(self.gate(), ['C1', 'C2'], {'approved': True, 'issues': []}))
        self.assertIsNone(self.prune(self.gate(), ['contract'], {'approved': True, 'issues': []}))


    def test_write_only_criterion_is_dropped_after_review_once_the_rest_passes(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        gate = self.gate()
        gate.runner.args = SimpleNamespace(task=TASK)
        gate.artifact_dir = Path(tmp.name)
        gate._prune_rejected = lambda task, parsed, review: verification_gate.Gate._prune_rejected(gate, task, parsed, review)
        report = {'success': False, 'results': [{'id': 'C1', 'status': 'passed'},
                                                {'id': 'C2', 'status': 'unverified', 'reason': 'blocked_requests'}]}
        with patch('requirement_review.review', return_value={'approved': True, 'issues': []}):
            contract = verification_gate.Gate._drop_write_criteria(gate, CONTRACT, report)
        self.assertEqual([c['id'] for c in contract['criteria']], ['C1'])
        self.assertTrue(report['success'])
        self.assertEqual(report['dropped_write_criteria'], ['C2'])
        self.assertEqual(json.loads(gate.frozen_contract), contract)

    def test_write_criterion_stays_while_other_criteria_fail_or_reviewer_disagrees(self):
        gate = self.gate()
        gate.runner.args = SimpleNamespace(task=TASK)
        failing = {'success': False, 'results': [{'id': 'C1', 'status': 'failed'},
                                                 {'id': 'C2', 'status': 'unverified', 'reason': 'blocked_requests'}]}
        self.assertIs(verification_gate.Gate._drop_write_criteria(gate, CONTRACT, failing), CONTRACT)
        gate = self.gate(); gate.runner.args = SimpleNamespace(task=TASK)
        gate._prune_rejected = lambda *a: None
        passing = {'success': False, 'results': [{'id': 'C1', 'status': 'passed'},
                                                 {'id': 'C2', 'status': 'unverified', 'reason': 'blocked_requests'}]}
        self.assertIs(verification_gate.Gate._drop_write_criteria(gate, CONTRACT, passing), CONTRACT)
        self.assertFalse(passing['success'])


if __name__ == '__main__':
    unittest.main()


class HiddenProofTests(unittest.TestCase):
    def check(self, criteria):
        import requirement_contract
        return requirement_contract.validate('x', {'criteria': criteria})

    def scenario(self, cid, *steps):
        return {'id': cid, 'requirement_id': 'R1', 'description': 'd', 'check': {'op': 'scenario', 'steps': [
            {'action': 'click', 'selector': 'button:has-text("저장")'}, *steps]}}

    def test_hidden_may_be_proven_visible_by_another_criterion(self):
        alert = "div[role='alert']"
        self.check([self.scenario('C1', {'action': 'expect_visible', 'selector': alert}),
                    self.scenario('C2', {'action': 'expect_hidden', 'selector': alert})])
        with self.assertRaises(ValueError):
            self.check([self.scenario('C2', {'action': 'expect_hidden', 'selector': alert})])


class DryRunTests(unittest.TestCase):
    def gate(self, reason):
        gate = SimpleNamespace(runner=SimpleNamespace(h=SimpleNamespace(log_event=Mock())),
                               _baseline_counts={'#f >> internal:label="품번"i': 1, '#f >> internal:label="규격"i': 0})
        gate._probe = lambda criteria: {'results': [{'id': 'C1', 'status': 'failed', 'reason': reason}]}
        return gate

    contract = {'criteria': [{'id': 'C1', 'check': {'op': 'scenario', 'steps': [
        {'action': 'click', 'selector': 'role=tab[name="추가정보"]'},
        {'action': 'fill', 'selector': '#f >> internal:label="규격"i', 'value': 'x'},
        {'action': 'fill', 'selector': '#f >> internal:label="품번"i', 'value': 'x'}]}}]}

    def test_existing_element_lost_by_earlier_steps_rejects_the_draft(self):
        gate = self.gate('step 3 (fill #f >> internal:label="품번"i) failed: x | DIAGNOSTIC: target #f >> internal:label="품번"i does not exist in the DOM at this point')
        with self.assertRaises(ValueError) as error:
            verification_gate.Gate._dry_run_scenarios(gate, self.contract)
        self.assertIn('step 3', str(error.exception))

    def test_new_element_missing_before_the_change_is_expected(self):
        gate = self.gate('step 2 (fill #f >> internal:label="규격"i) failed: x | DIAGNOSTIC: target #f >> internal:label="규격"i does not exist in the DOM at this point')
        verification_gate.Gate._dry_run_scenarios(gate, self.contract)


class NewScreenTests(unittest.TestCase):
    def root(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        screens = Path(tmp.name) / 'frontend/src/screens'
        screens.mkdir(parents=True)
        (screens / 'ItemMaster.tsx').write_text("export const meta = { code: 'MST0001', title: '품목 등록' };")
        return tmp.name

    def test_new_screen_task_uses_the_reference_screen(self):
        from task_sources import new_screen_reference
        root = self.root()
        self.assertEqual(new_screen_reference(root, '회사 등록 화면'), '품목 등록')
        self.assertEqual(new_screen_reference(root, '품목 등록 화면에 버튼 추가'), '')
        self.assertEqual(new_screen_reference(root, '회사 API'), '')

    def test_structural_selector_missing_on_reference_is_rejected(self):
        counts = {'h1': 0, 'form[data-ui="query-panel"]': 1, 'internal:label="회사명"i': 0}
        gate = SimpleNamespace(runner=SimpleNamespace(h=SimpleNamespace(log_event=Mock())), _probe_screen='품목 등록')
        gate._probe = lambda criteria: {'results': [{'evidence': {'counts': counts, 'visible': counts}}]}
        parsed = {'criteria': [{'id': f'C{i}', 'check': {'op': 'visible', 'selector': sel}} for i, sel in enumerate(counts)]}
        with self.assertRaises(ValueError) as error:
            verification_gate.Gate._require_unique_selectors(gate, parsed)
        self.assertIn("'C0'", str(error.exception))
        self.assertNotIn("'C1'", str(error.exception))
        self.assertNotIn("'C2'", str(error.exception))


class StepAliasTests(unittest.TestCase):
    def test_contains_in_expect_text_step_means_value(self):
        import requirement_contract
        parsed = requirement_contract.validate('x', {'criteria': [{'id': 'C1', 'requirement_id': 'R1', 'description': 'd', 'check': {
            'op': 'scenario', 'steps': [{'action': 'click', 'selector': 'button:has-text("저장")'},
                                        {'action': 'expect_text', 'selector': "div[role='alert']", 'contains': '규격'}]}}]})
        self.assertEqual(parsed['criteria'][0]['check']['steps'][1], {'action': 'expect_text', 'selector': "div[role='alert']", 'value': '규격'})
