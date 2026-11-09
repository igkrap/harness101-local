import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
import fixed_acceptance
from verification_gate import Gate


class FixedAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / 'local-only'
        (self.root / 'frontend/src').mkdir(parents=True)
        self.script = self.base / 'platform/tests/oracle.cjs'
        self.script.parent.mkdir(parents=True)
        self.script.write_text('// immutable oracle')
        self.patch_root = patch.object(fixed_acceptance, 'CHECKS_ROOT', self.script.parent)
        self.patch_root.start()
        self.addCleanup(self.patch_root.stop)
        self.spec = {'id': 'example-v1', 'task': '조회 동작\n저장 동작', 'project_root': str(self.root),
                     'script': str(self.script), 'script_sha256': hashlib.sha256(self.script.read_bytes()).hexdigest(),
                     'cases': ['query', 'save']}

    def gate(self, spec=None):
        runner = SimpleNamespace(args=SimpleNamespace(task=self.spec['task'], fixed_acceptance=spec or self.spec),
                                 modes=['frontend', 'framework'], accepted=True,
                                 h=SimpleNamespace(workspace=SimpleNamespace(root=self.root), log_event=Mock()),
                                 ask=Mock(side_effect=AssertionError('Model must not author fixed acceptance')),
                                 current_context=Mock(side_effect=AssertionError('No context needed for fixed acceptance')))
        gate = Gate(runner)
        gate.artifact_dir = self.base / 'evidence'
        return gate, runner

    def executor(self, payload=None, code=0, mutate=False, missing=False):
        def execute(command, **kwargs):
            out = Path(command[2])
            self.assertFalse((out / 'result.json').exists())
            if not missing:
                (out / 'result.json').write_text(json.dumps(payload if payload is not None else {'passed': True, 'cases': ['query', 'save']}))
            if mutate:
                self.script.write_text('// tampered during run')
            return subprocess.CompletedProcess(command, code, 'browser output', '')
        return execute

    def test_prepare_uses_zero_model_calls_and_covers_all_requirements(self):
        gate, runner = self.gate()
        gate.prepare()
        contract = json.loads(gate.frozen_contract)
        self.assertEqual(len(contract['criteria']), 1)
        self.assertEqual(contract['criteria'][0]['requirement_ids'], ['R1', 'R2'])
        self.assertEqual(contract['verifier'], self.spec)
        self.assertIn('Implement the task directly', gate.context())
        runner.ask.assert_not_called()
        self.assertEqual([call.args[0] for call in runner.h.log_event.call_args_list], ['requirement.contract', 'requirement.contract_predefined'])

    def test_wrong_task_project_hash_or_duplicate_cases_rejected(self):
        for key, value in [('task', 'different'), ('project_root', str(self.base)), ('script_sha256', '0' * 64), ('cases', ['query', 'query'])]:
            spec = copy.deepcopy(self.spec)
            spec[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.gate(spec)[0].prepare()
        link = self.script.parent / 'link.cjs'
        link.symlink_to(self.script)
        with self.assertRaises(ValueError):
            self.gate({**self.spec, 'script': str(link)})[0].prepare()

    def test_fixed_contract_skips_division_and_model_planning(self):
        from divide_runner import extend_divide
        from deterministic_plan import plan
        gate, runner = self.gate()

        class Base:
            def __init__(self, args, harness_class):
                self.__dict__.update(vars(runner))
                self.requirement_gate = gate
                gate.runner = self

            def verify(self):
                return True, 'baseline passed'

            def run(self):
                self.requirement_gate.prepare()
                plan(self)
                return self.steps

        with patch('divide_runner.create', side_effect=AssertionError('No model division plan')) as divide:
            direct = extend_divide(Base)(runner.args, None)
            self.assertEqual(direct.run(), [{'title': self.spec['task'], 'kind': 'change'}])
            divide.assert_not_called()
            direct.ask.assert_not_called()

    def test_pass_still_requires_actual_accepted_source_change(self):
        gate, runner = self.gate()
        gate.prepare()
        with patch.object(fixed_acceptance.subprocess, 'run', side_effect=self.executor()):
            self.assertFalse(gate.verify()['success'])
            (self.root / 'frontend/src/New.tsx').write_text('export default function New() { return null; }')
            self.assertTrue(gate.verify()['success'])
            runner.accepted = False
            self.assertFalse(gate.verify()['success'])

    def test_false_pass_nonzero_missing_malformed_or_incomplete_cases_fail(self):
        variants = [({'passed': False, 'cases': ['query', 'save']}, 0, False),
                    ({'passed': True, 'cases': ['query', 'save']}, 1, False),
                    ({'passed': True, 'cases': ['query']}, 0, False),
                    ({'passed': True, 'cases': ['query', 'save', 'save']}, 0, False),
                    ({'passed': True, 'cases': ['query', 'save', 'extra']}, 0, False),
                    ([], 0, False), (None, 0, True)]
        gate, _ = self.gate()
        gate.prepare()
        criteria = json.loads(gate.frozen_contract)['criteria']
        for payload, code, missing in variants:
            with self.subTest(payload=payload, code=code, missing=missing), patch.object(fixed_acceptance.subprocess, 'run', side_effect=self.executor(payload, code, missing=missing)):
                report = gate._probe(criteria)
                self.assertFalse(report['success'])
                self.assertTrue(Path(report['results'][0]['evidence']).is_file())

    def test_script_change_before_or_during_execution_fails(self):
        gate, _ = self.gate()
        gate.prepare()
        criteria = json.loads(gate.frozen_contract)['criteria']
        with patch.object(fixed_acceptance.subprocess, 'run', side_effect=self.executor(mutate=True)):
            self.assertFalse(gate._probe(criteria)['success'])
        with patch.object(fixed_acceptance.subprocess, 'run') as execute:
            self.assertFalse(gate._probe(criteria)['success'])
            execute.assert_not_called()

    def test_nested_checker_failure_reaches_model_feedback_without_changing_verdict(self):
        gate, _ = self.gate()
        gate.prepare()
        criteria = json.loads(gate.frozen_contract)['criteria']

        def execute(command, **kwargs):
            out = Path(command[2])
            (out / 'result.json').write_text(json.dumps({'passed': False, 'failure': 'Wrapper assertion'}))
            nested = out / 'delete-regression/update-regression/create-regression'
            nested.mkdir(parents=True)
            (nested / 'result.json').write_text(json.dumps({
                'passed': False, 'failure': 'TimeoutError: locator.click waiting for button 추가', 'cases': []}))
            return subprocess.CompletedProcess(command, 1, '', '')

        with patch.object(fixed_acceptance.subprocess, 'run', side_effect=execute):
            report = gate._probe(criteria)
        self.assertFalse(report['success'])
        reason = report['results'][0]['reason']
        self.assertIn('Wrapper assertion', reason)
        self.assertIn('TimeoutError: locator.click waiting for button 추가', reason)
        self.assertIn('delete-regression/update-regression/create-regression/result.json', reason)

    def test_nested_diagnostics_reject_links_and_bound_output(self):
        out = self.base / 'diagnostic-output'
        out.mkdir()
        outside = self.base / 'outside.json'
        outside.write_text(json.dumps({'passed': False, 'failure': 'EXTERNAL SECRET'}))
        (out / 'linked').symlink_to(self.base)
        nested = out / 'nested'
        nested.mkdir()
        (nested / 'result.json').symlink_to(outside)
        self.assertEqual(fixed_acceptance._nested_failure(out), '')
        (nested / 'result.json').unlink()
        (nested / 'result.json').write_text(json.dumps({'passed': False, 'failure': 'x' * 2000}))
        feedback = fixed_acceptance._nested_failure(out)
        self.assertLessEqual(len(feedback), 800)
        self.assertNotIn('EXTERNAL SECRET', feedback)


if __name__ == '__main__':
    unittest.main()
