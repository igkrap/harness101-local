import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
from verification_gate import Gate
from requirement_contract import digest, validate


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.file = self.root / 'frontend/src/App.tsx'
        self.file.parent.mkdir(parents=True)
        self.file.write_text('export default function App(){return <main>Before</main>}')
        self.task = '메인 화면에 로고 표시'
        self.raw = {'criteria': [{'id': 'C1', 'requirement_id': 'R1', 'description': '브랜드 표시',
                                 'check': {'op': 'text', 'selector': 'nav', 'contains': '브랜드'}}]}
        self.runner = SimpleNamespace(
            args=SimpleNamespace(task=self.task), modes=['frontend'], accepted=False,
            h=SimpleNamespace(workspace=SimpleNamespace(root=self.root), log_event=Mock(), checker=Mock()),
            current_context=Mock(return_value=('CURRENT SOURCE', set())),
            ask=Mock(return_value={'content': json.dumps(self.raw, ensure_ascii=False)}))
        self.home = patch('verification_gate.Path.home', return_value=self.root)
        self.home.start()
        self.review_patch=patch('requirement_review.review',return_value={'approved':True,'issues':[]})
        self.review=self.review_patch.start()
        self.gate = Gate(self.runner)

    def tearDown(self):
        self.home.stop()
        self.review_patch.stop()
        self.temp.cleanup()

    def prepared(self):
        self.gate.prepare()
        self.runner.accepted = True
        self.file.write_text('export default function App(){return <main>After</main>}')
        return self.gate

    def passed(self):
        return {'success': True, 'results': [{'id': 'C1', 'status': 'passed', 'reason': '', 'evidence': {'text': '브랜드'}}], 'layout': [], 'screenshot': None}

    def test_contract_generated_once_and_not_per_verification(self):
        self.gate.prepare()
        self.gate.prepare()
        self.runner.ask.assert_called_once()
        self.assertIn(self.task, self.gate.context())
        self.assertTrue(any(c.args[0] == 'requirement.contract' for c in self.runner.h.log_event.call_args_list))

    def test_zero_mutation_cannot_pass_even_when_browser_check_passes(self):
        self.gate.prepare()
        with patch.object(self.gate, '_probe', return_value=self.passed()):
            report = self.gate.verify()
        self.assertFalse(report['success'])
        self.assertTrue(any(r['id'] == 'system:mutation' and r['status'] != 'passed' for r in report['results']))

    def test_accepted_flag_without_net_source_change_cannot_pass(self):
        self.gate.prepare()
        self.runner.accepted = True
        with patch.object(self.gate, '_probe', return_value=self.passed()):
            self.assertFalse(self.gate.verify()['success'])

    def test_actual_change_and_every_criterion_passes(self):
        self.prepared()
        with patch.object(self.gate, '_probe', return_value=self.passed()):
            report = self.gate.verify()
        self.assertTrue(report['success'], report)
        self.assertEqual(report['contract_hash'], self.gate.contract_hash)
        self.assertTrue(any(c.args[0] == 'verification.finished' for c in self.runner.h.log_event.call_args_list))

    def test_failed_or_unverified_criterion_blocks_completion(self):
        self.prepared()
        for status in ['failed', 'unverified']:
            probe = self.passed()
            probe['success'] = False
            probe['results'][0].update(status=status, reason='right panel missing')
            with self.subTest(status=status), patch.object(self.gate, '_probe', return_value=probe):
                report = self.gate.verify()
                self.assertFalse(report['success'])
                self.assertIn('right panel missing', json.dumps(report))

    def test_probe_rejects_missing_duplicate_and_forged_success(self):
        self.prepared()
        for probe in [
            {'success': True, 'results': []},
            {'success': True, 'results': [{'id': 'C1', 'status': 'unverified'}]},
            {'success': True, 'results': [{'id': 'C1', 'status': 'passed'}] * 2},
            {'success': True, 'results': [{'id': 'UNKNOWN', 'status': 'passed'}]},
        ]:
            completed = SimpleNamespace(returncode=0, stdout=json.dumps(probe), stderr='')
            with self.subTest(probe=probe), patch('verification_gate.subprocess.run', return_value=completed):
                self.assertFalse(self.gate.verify()['success'])

    def test_timeout_and_missing_browser_are_unverified(self):
        import subprocess
        self.prepared()
        for error in [FileNotFoundError('node missing'), subprocess.TimeoutExpired('node', 120)]:
            with self.subTest(error=error), patch('verification_gate.subprocess.run', side_effect=error):
                report = self.gate.verify()
                self.assertFalse(report['success'])
                self.assertTrue(any(r['id'] == 'C1' and r['status'] == 'unverified' for r in report['results']))

    def test_isolation_requires_explicit_distinct_service(self):
        self.prepared()
        env = {'HARNESS_PREVIEW_URL': 'http://127.0.0.1:5292', 'HARNESS_API_URL': 'http://127.0.0.1:8083',
               'HARNESS_VERIFICATION_BROWSER_ISOLATED': '1', 'HARNESS_VERIFICATION_API_ISOLATED': '1'}
        with patch.dict(os.environ, env, clear=True):
            inp = self.gate._input([])
            self.assertFalse(inp['allow_browser_writes'])
            self.assertFalse(inp['allow_api_writes'])
        env.update(HARNESS_VERIFICATION_PREVIEW_URL='http://127.0.0.1:5294', HARNESS_VERIFICATION_API_URL='http://127.0.0.1:8084')
        with patch.dict(os.environ, env, clear=True):
            inp = self.gate._input([])
            self.assertTrue(inp['allow_browser_writes'])
            self.assertTrue(inp['allow_api_writes'])

    def test_contract_parse_failure_never_falls_back_to_success(self):
        self.runner.ask.return_value = {'content': '{"criteria":[]}'}
        with self.assertRaisesRegex(RuntimeError, 'contract|Contract'):
            self.gate.prepare()
        self.assertEqual(self.runner.ask.call_count, 3)

    def test_rejected_contract_is_rebuilt_before_it_is_frozen(self):
        self.review.side_effect=[{'approved':False,'issues':[{'criterion_id':'C1','reason':'wrong region ordering'}]},
                                 {'approved':True,'issues':[]}]
        self.gate.prepare()
        self.assertEqual(self.runner.ask.call_count,2)
        self.assertIn('wrong region ordering',str(self.runner.ask.call_args))
        self.assertIsNotNone(self.gate.frozen_contract)
        messages = self.runner.ask.call_args.kwargs['messages']
        self.assertEqual([m['role'] for m in messages], ['system', 'user', 'assistant', 'user'])
        self.assertEqual(json.loads(messages[2]['content']), self.raw)
        self.assertIn('wrong region ordering', messages[3]['content'])

    def test_manual_draft_is_repaired_before_contract_is_frozen(self):
        manual=copy.deepcopy(self.raw)
        manual['criteria'][0]['check']={'op':'manual','reason':'look at the screen'}
        self.runner.ask.side_effect=[{'content':json.dumps(manual)},{'content':json.dumps(self.raw)}]
        self.gate.prepare()
        self.assertEqual(self.runner.ask.call_count,2)
        self.assertIn('Manual',str(self.runner.ask.call_args))
        self.assertNotIn('manual',self.gate.frozen_contract)
        self.assertEqual(self.review.call_count,1)
        rejected=[c.args[1] for c in self.runner.h.log_event.call_args_list if c.args[0]=='requirement.contract_rejected']
        self.assertEqual(len(rejected),1)
        self.assertIn('Manual',rejected[0]['error'])
        self.assertFalse(rejected[0]['success'])

    def test_manual_criterion_beside_executable_ones_is_dropped(self):
        mixed=copy.deepcopy(self.raw)
        extra=copy.deepcopy(mixed['criteria'][0])
        extra.update(id='C9',check={'op':'manual','reason':'framework code should own it'})
        mixed['criteria'].append(extra)
        self.runner.ask.side_effect=[{'content':json.dumps(mixed)}]
        self.gate.prepare()
        self.assertEqual(self.runner.ask.call_count,1)
        self.assertNotIn('manual',self.gate.frozen_contract)
        dropped=[c.args[1] for c in self.runner.h.log_event.call_args_list if c.args[0]=='requirement.manual_dropped']
        self.assertEqual(dropped,[{'removed':['C9']}])

    def test_unexecutable_manual_contract_never_enters_edit_loop(self):
        manual=copy.deepcopy(self.raw)
        manual['criteria'][0]['check']={'op':'manual','reason':'needs human approval'}
        self.runner.ask.return_value={'content':json.dumps(manual)}
        with self.assertRaisesRegex(RuntimeError,'Manual|manual'):
            self.gate.prepare()
        self.assertIsNone(self.gate.frozen_contract)
        self.assertEqual(self.runner.ask.call_count,3)
        self.review.assert_not_called()

    def test_backend_criteria_use_fresh_source_and_disposable_database_gate(self):
        folder=self.root/'backend'
        folder.mkdir()
        (folder/'pom.xml').write_text('<project/>')
        criterion={'id':'API1','check':{'op':'api','method':'GET','path':'/api/items','status':200}}
        backend=SimpleNamespace(verify=Mock(return_value={'success':True,'results':[{'id':'API1','status':'passed'}]}))
        with patch.dict(sys.modules,{'backend_contract_gate':backend}), patch.dict(os.environ,{},clear=True), patch('verification_gate.subprocess.run') as node:
            report=self.gate._probe([criterion])
        backend.verify.assert_called_once()
        self.assertEqual(backend.verify.call_args.args[1],[criterion])
        node.assert_not_called()
        self.assertTrue(report['success'],report)

    def test_explicit_api_service_uses_http_executor(self):
        folder=self.root/'backend'
        folder.mkdir()
        (folder/'pom.xml').write_text('<project/>')
        criterion={'id':'API1','check':{'op':'api','method':'GET','path':'/api/items','status':200}}
        raw={'success':True,'results':[{'id':'API1','status':'passed'}]}
        with patch.dict(os.environ,{'HARNESS_VERIFICATION_API_URL':'http://127.0.0.1:8084'},clear=True), patch('verification_gate.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(raw),stderr='')) as node:
            report=self.gate._probe([criterion])
        node.assert_called_once()
        self.assertTrue(report['success'],report)


class CompletionRegressionTests(unittest.TestCase):
    def test_original_layout_request_does_not_use_missing_grid_shortcut(self):
        from cycle_context import cycle_context
        goal = '전체적인 화면은 다음과 같이 구성\n좌측 넓게, 우측 좁게\n좌측 상단 높이 2줄 정도의 조회 조건, 조회버튼 패널\n좌측 하단 나머지 높이의 조회결과 그리드\n우측 신규 등록 및 수정 패널'
        self.assertFalse(cycle_context.is_grid_task(goal))
        self.assertTrue(cycle_context.is_grid_task('조회 결과 그리드 없는 화면에 추가'))

    def test_existing_table_cannot_promote_unmodified_work_to_complete(self):
        from runner_extensions import extend_runner
        class Base:
            def verify_step(self): return self.steps[self.step]['kind'] == 'verify'
        runner = extend_runner(Base)()
        runner.args = SimpleNamespace(task='조회 결과 그리드 없는 화면에 추가')
        runner.steps = [{'kind': 'change'}]
        runner.step = 0
        runner.accepted = False
        with patch('cycle_context.cycle_context.coverage', return_value=''):
            self.assertFalse(runner.verify_step())
        self.assertEqual(runner.steps[0]['kind'], 'change')


if __name__ == '__main__': unittest.main()


class AbsentBaselineTests(unittest.TestCase):
    def gate_with(self, results):
        import verification_gate
        gate = verification_gate.Gate.__new__(verification_gate.Gate)
        gate.runner = SimpleNamespace(h=SimpleNamespace(log_event=Mock()))
        gate._probe = Mock(return_value={'results': results})
        return gate

    def contract(self):
        return {'criteria': [{'id': 'C2', 'requirement_id': 'R1', 'description': '스플릿 핸들 제거',
                              'check': {'op': 'absent', 'selector': '[data-ui="split-handle"]'}}]}

    def test_absent_selector_missing_before_change_is_rejected(self):
        gate = self.gate_with([])
        gate._probe = Mock(side_effect=[{'results': [{'id': 'C2', 'status': 'failed'}]},
                                        {'results': [{'id': 'inventory', 'status': 'passed', 'evidence': {'elements': [
                                            {'tag': 'div', 'role': 'separator', 'label': '편집 패널 높이'}]}}]}])
        with self.assertRaisesRegex(ValueError, r'trivially[\s\S]*div\[role="separator"\]\[aria-label="편집 패널 높이"\]'):
            gate._require_absent_baseline(self.contract())
        self.assertEqual(gate._probe.call_args_list[0].args[0][0]['check'], {'op': 'visible', 'selector': '[data-ui="split-handle"]'})
        self.assertEqual(gate._probe.call_args_list[1].args[0][0]['check'], {'op': 'inventory'})

    def test_absent_selector_present_before_change_is_accepted(self):
        self.gate_with([{'id': 'C2', 'status': 'passed'}])._require_absent_baseline(self.contract())


class UniqueSelectorTests(unittest.TestCase):
    def gate(self, counts):
        import verification_gate
        gate = verification_gate.Gate.__new__(verification_gate.Gate)
        gate.runner = SimpleNamespace(h=SimpleNamespace(log_event=Mock()))
        gate._probe = Mock(return_value={'results': [{'id': 'count', 'status': 'passed', 'evidence': {'counts': counts}}]})
        return gate

    def test_selector_matching_several_elements_is_rejected(self):
        parsed = {'criteria': [{'id': 'C1', 'requirement_id': 'R1', 'check': {'op': 'text', 'selector': 'section th', 'contains': '메모'}}]}
        with self.assertRaisesRegex(ValueError, 'C1.*already matches 6'):
            self.gate({'section th': 6, 'section': 1})._require_unique_selectors(parsed)
        self.gate({'section th': 1, 'section': 1})._require_unique_selectors(parsed)

    def test_missing_container_and_wrong_tag_are_rejected_but_new_elements_pass(self):
        parsed = {'criteria': [
            {'id': 'C1', 'requirement_id': 'R1', 'check': {'op': 'visible', 'selector': 'form[aria-label="조회 조건"] input[name="spec"]'}},
            {'id': 'C2', 'requirement_id': 'R1', 'check': {'op': 'scenario', 'steps': [
                {'action': 'click', 'selector': "button:has-text('조건 초기화')"},
                {'action': 'expect_visible', 'selector': 'div[data-region="results"]'}]}}]}
        counts = {'form[aria-label="조회 조건"] input[name="spec"]': 0, 'form[aria-label="조회 조건"]': 0,
                  "button:has-text('조건 초기화')": 0, 'div[data-region="results"]': 0, '[data-region="results"]': 1}
        with self.assertRaises(ValueError) as error:
            self.gate(counts)._require_unique_selectors(parsed)
        text = str(error.exception)
        self.assertIn('container form[aria-label="조회 조건"]', text)
        self.assertIn('another tag', text)
        self.assertNotIn('조건 초기화', text)


class ClearRejectionTests(unittest.TestCase):
    """A 400 check must violate something on its face; omitting optional attributes is a valid request."""
    def contract(self, bad_body):
        good = {'companyName': '테스트회사', 'phone': '010', 'email': 'a@b.c'}
        return {'criteria': [
            {'id': 'C1', 'check': {'op': 'api', 'method': 'POST', 'path': '/api/companies', 'status': 201, 'body': good}},
            {'id': 'C2', 'check': {'op': 'api', 'method': 'POST', 'path': '/api/companies', 'status': 400, 'body': bad_body}}]}

    def test_subset_of_an_accepted_body_is_refused_with_guidance(self):
        from verification_gate import Gate
        with self.assertRaisesRegex(ValueError, "only omits \\['email', 'phone'\\]"):
            Gate._require_clear_rejection(self.contract({'companyName': '테스트회사'}))

    def test_empty_blank_or_different_bodies_are_fine(self):
        from verification_gate import Gate
        for body in ({}, {'companyName': ''}, {'companyName': None, 'phone': '010'}, {'companyName': '다른회사'}):
            Gate._require_clear_rejection(self.contract(body))
