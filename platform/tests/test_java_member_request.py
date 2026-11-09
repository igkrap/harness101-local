import json
import sys
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-only/harness'))
import test_autonomy


class JavaMemberRequestTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.rel='backend/src/test/java/demo/InventoryTest.java';self.file=self.root/self.rel
        self.file.parent.mkdir(parents=True);self.file.write_text('package demo; class InventoryTest { void original() {} }')
        self.criteria=[dict(id='C1',check=dict(op='junit_added',suite='demo.InventoryTest',count=3))]
        self.contract=dict(task='Add new tests; preserve original methods',criteria=self.criteria)
        self.gate=SimpleNamespace(frozen_contract=json.dumps(self.contract),_junit_baseline={'suites':{'demo.InventoryTest':{'executed':5}}})
        self.messages=[dict(role='user',content='native main loop')]
        self.runner=SimpleNamespace(messages=self.messages,modes=['backend'],cp=SimpleNamespace(pending=False),requirement_gate=self.gate,h=SimpleNamespace(workspace=test_autonomy.native.WorkspaceManager(self.root)),read=set(),feedback='prior compilation failure',used=7)

    def test_plain_java_response_becomes_native_safe_tool_without_model_tool_json(self):
        from java_member_request import focused
        ask=Mock(return_value={'content':'```java\nvoid added() {}\n```','tool_calls':[]})
        response=focused(self.runner,self.messages,ask)
        args=json.loads(response['tool_calls'][0]['function']['arguments'])
        self.assertEqual(args,dict(path=self.rel,class_name='InventoryTest',code='void added() {}'))
        self.assertEqual(self.runner.used,7)
        self.assertIn(self.rel,self.runner.read)
        packet=ask.call_args.args[0];self.assertEqual(ask.call_args.args[1],[])
        self.assertIn('prior compilation failure',packet[1]['content'])
        self.assertIn('8',packet[1]['content'])

    def test_bootstrap_requests_and_pending_transactions_are_not_intercepted(self):
        from java_member_request import focused
        ask=Mock()
        self.assertIsNone(focused(self.runner,list(self.messages),ask))
        self.runner.cp.pending=True
        self.assertIsNone(focused(self.runner,self.messages,ask))
        ask.assert_not_called()

    def test_repeated_suite_criteria_and_stage_owned_criteria_use_correct_shape(self):
        from java_member_request import focused
        self.contract['criteria'].append(dict(id='C2',check=dict(op='junit_added',suite='demo.InventoryTest',count=2)))
        self.gate.frozen_contract=json.dumps(self.contract)
        ask=Mock(return_value={'content':'void added() {}'})
        self.assertIsNotNone(focused(self.runner,self.messages,ask))
        stage=SimpleNamespace(contract=self.contract,stage={'criterion_ids':['C1']},parent_gate=self.gate,selected=lambda:self.contract['criteria'])
        self.runner.requirement_gate=stage
        self.assertIsNotNone(focused(self.runner,self.messages,ask))

    def test_transport_errors_propagate_and_invalid_response_has_explicit_feedback(self):
        from java_member_request import focused
        with self.assertRaises(TimeoutError):focused(self.runner,self.messages,Mock(side_effect=TimeoutError('timeout')))
        response=focused(self.runner,self.messages,Mock(return_value={'content':''}))
        self.assertFalse(response.get('tool_calls'))
        self.assertTrue(getattr(self.runner,'_java_member_error',None))

    def test_rollback_candidate_is_retained_but_committed_source_does_not_reinsert_it(self):
        from java_member_request import focused
        ask=Mock(return_value={'content':'```java\nvoid added() {}\n```'})
        focused(self.runner,self.messages,ask)
        focused(self.runner,self.messages,ask)
        self.assertIn('void added()',ask.call_args.args[0][1]['content'])
        self.file.write_text(self.file.read_text()+'\n// committed changes')
        focused(self.runner,self.messages,ask)
        self.assertNotIn('void added()',ask.call_args.args[0][1]['content'])

    def test_native_runner_uses_raw_code_and_preserves_atomic_rollback(self):
        import test_candidate_repair as fixtures
        from java_member_focus import extend_java_members
        fixture=fixtures.CandidateRepairTests()
        fixture.setUp()
        try:
            old_service=getattr(fixture.runner.h,'_code_intelligence',None)
            if old_service:old_service.close()
            fixture.args.check='backend'
            fixture.args.task='Add Java test methods'
            rel='backend/src/test/java/demo/InventoryTest.java';file=fixture.root/rel
            file.parent.mkdir(parents=True);original='package demo; class InventoryTest { void original() {} }';file.write_text(original)
            runner=extend_java_members(fixture.Runner)(fixture.args,fixture.Harness);fixture.runner=runner
            runner.requirement_gate=SimpleNamespace(enabled=False,frozen_contract=json.dumps(self.contract),_junit_baseline=self.gate._junit_baseline)
            runner.h.llm.chat=Mock(return_value={'choices':[{'message':{'content':'```java\nvoid added() {}\n```'}}]})
            response=runner.ask(runner.messages,runner.tools())
            self.assertEqual(runner.used,1)
            self.assertEqual(runner.h.llm.chat.call_args.kwargs['tools'],[])
            paths,error,_=runner.batch(response)
            self.assertFalse(error,error)
            self.assertTrue(runner.cp.pending)
            self.assertIn('void original() {}',file.read_text())
            self.assertIn('void added() {}',file.read_text())
            runner.cp.rollback();self.assertEqual(file.read_text(),original)
        finally:
            fixture.tearDown()
