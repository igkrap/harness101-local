import copy
import json
import unittest
from unittest.mock import Mock

import test_candidate_repair as candidate_tests
from candidate_focus import ask_candidate


class CandidateFocusTests(unittest.TestCase):
    setUp = candidate_tests.CandidateRepairTests.setUp
    tearDown = candidate_tests.CandidateRepairTests.tearDown
    proposal = candidate_tests.CandidateRepairTests.proposal
    repair = candidate_tests.CandidateRepairTests.repair

    def test_native_named_panel_scope_reaches_model_with_parent_hidden(self):
        from ast_editing import editor
        self.file.write_text(self.original.replace('<main>', '<main data-testid="root">').replace('<aside>', '<aside data-testid="right">'))
        snap = editor(self.runner.h).snapshot(self.rel)
        aside = next(n for n in snap['nodes'] if n['kind'] == 'JsxElement' and n['source'].startswith('<aside'))
        root = next(n for n in snap['nodes'] if n['kind'] == 'JsxElement' and n['source'].startswith('<main'))
        self.runner.requirement_gate.contract = {'task': 'Move editor to right', 'criteria': [{'id': 'C5', 'check': {'selector': '[data-testid="right"]'}}]}
        self.runner.requirement_gate.last_report = {'results': [{'id': 'C5', 'status': 'failed'}]}
        self.runner._failed_ast_candidate = dict(path=self.rel, snapshot_id=snap['snapshot_id'], source_hash=snap['source_hash'], edits=[])
        callback = Mock(return_value={'content': ''})
        ask_candidate(self.runner, callback)
        callback.assert_called_once()
        packet = callback.call_args.args[0][1]['content']
        self.assertIn('NODE ' + aside['id'] + ' KIND', packet)
        self.assertNotIn('NODE ' + root['id'] + ' KIND', packet)

    def retain(self):
        self.runner.apply('inspect_code', {'path': self.rel, 'action': 'edit_ranges'}, {})
        self.runner.apply('apply_ast_edits', self.proposal(), {})
        ok, feedback = self.runner.verify()
        self.assertFalse(ok)
        self.runner.cp.rollback()
        self.runner.feedback = feedback
        self.runner.steps = [{'title': 'repair', 'kind': 'change'}]
        self.runner.fresh('failed patch')
        return copy.deepcopy(self.runner._failed_ast_candidate)

    def test_focused_json_repair_preserves_companions_and_uses_native_checks(self):
        proposal = self.retain()
        callback = Mock(return_value={'content': json.dumps(self.repair())})
        message = ask_candidate(self.runner, callback)
        messages, tools = callback.call_args.args
        self.assertEqual([t['function']['name'] for t in tools], ['replace_ast_fragments'])
        self.assertIn('search', json.dumps(messages))
        self.assertIn('save', json.dumps(messages))
        self.assertIn('이름', messages[1]['content'])
        self.assertEqual(self.file.read_text(), self.original)
        self.assertEqual(self.runner._failed_ast_candidate, proposal)
        paths, error, finished = self.runner.batch(message)
        self.assertFalse(error, error)
        self.assertTrue(self.runner.cp.pending)
        ok, feedback = self.runner.verify()
        self.assertTrue(ok, feedback)
        source = self.file.read_text()
        self.assertIn('const search=', source)
        self.assertIn('onSubmit={search}', source)
        self.assertIn('onSubmit={save}', source)
        self.runner.cp.commit()

    def test_invalid_response_never_applies_or_loses_proposal_and_error_is_replayed(self):
        proposal = self.retain()
        cases = ['bad JSON', '{"changes":[],"changes":[],"remove":[]}', '{"changes":[],"remove":[]}', json.dumps({'changes':[{'node_id':'fake','code':'<aside>bad</aside>'}],'remove':[]}), json.dumps({'changes':[],'remove':['fake']}), json.dumps({'changes':[proposal['edits'][0]],'remove':[]})]
        for response in cases:
            callback = Mock(return_value={'content': response})
            message = ask_candidate(self.runner, callback)
            self.assertFalse(message.get('tool_calls'))
            self.assertEqual(self.file.read_text(), self.original)
            self.assertEqual(self.runner._failed_ast_candidate, proposal)
        error = self.runner._candidate_focus_error
        callback = Mock(return_value={'content': json.dumps(self.repair())})
        ask_candidate(self.runner, callback)
        self.assertIn(error, json.dumps(callback.call_args.args[0]))

    def test_stale_source_is_preserved_without_model_call(self):
        self.retain()
        changed = self.original + '// user change\n'
        self.file.write_text(changed)
        callback = Mock()
        message = ask_candidate(self.runner, callback)
        callback.assert_not_called()
        self.assertEqual(message['tool_calls'][0]['function']['name'], 'discard_ast_candidate')
        self.runner.batch(message)
        self.assertEqual(self.file.read_text(), changed)
        self.assertFalse(self.runner._failed_ast_candidate)

    def test_stop_and_generation_failure_propagate_without_mutation(self):
        self.retain()
        for error in (KeyboardInterrupt(), RuntimeError('model unavailable')):
            with self.assertRaises(type(error)):
                ask_candidate(self.runner, Mock(side_effect=error))
            self.assertEqual(self.file.read_text(), self.original)

    def test_native_ui_failure_starts_focused_repair_without_cosmetic_tool_rounds(self):
        self.proposal()
        self.runner.requirement_gate.last_report = {'results':[{'id':'C5','status':'failed','reason':'Native UI requirement: missing form'}]}
        self.runner.requirement_gate.stage = {'paths':[self.rel]}
        self.runner.feedback = 'Native UI requirement: missing form'
        self.runner.messages = [{'role':'user','content':'previous normal context'}]
        self.runner.h.llm.chat = Mock(return_value={'choices':[{'message':{'content':json.dumps(self.repair())}}]})
        response = self.runner.ask(self.runner.messages, self.runner.tools())
        self.assertEqual(response['tool_calls'][0]['function']['name'], 'repair_ast_candidate')
        self.assertEqual(self.runner._failed_ast_candidate['edits'], [])
        self.assertEqual(self.file.read_text(), self.original)
        self.assertEqual([t['function']['name'] for t in self.runner.h.llm.chat.call_args.kwargs['tools']], ['replace_ast_fragments'])
        _, error, _ = self.runner.batch(response)
        self.assertFalse(error, error)
        self.assertTrue(self.runner.cp.pending)
        ok, feedback = self.runner.verify()
        self.assertTrue(ok, feedback)
        self.assertIn('<aside><form onSubmit={save}>', self.file.read_text())
        self.runner.cp.commit()

    def test_non_ui_failure_does_not_seed_frontend_candidate(self):
        self.runner.requirement_gate.last_report = {'results':[{'status':'failed','reason':'API response invalid'}]}
        self.runner.requirement_gate.stage = {'paths':[self.rel]}
        self.runner.messages = [{'role':'user','content':'ordinary context'}]
        self.runner.h.llm.chat = Mock(return_value={'choices':[{'message':{'content':'normal response'}}]})
        self.runner.ask(self.runner.messages, self.runner.tools())
        self.assertIsNone(self.runner._failed_ast_candidate)
        self.assertTrue(self.runner.h.llm.chat.call_args.kwargs['tools'])

    def test_raw_fenced_edit_flows_through_same_atomic_repair_pipeline(self):
        self.retain()
        edit = self.repair()['changes'][0]
        callback = Mock(return_value={'content':'EDIT '+edit['node_id']+'\n```tsx\n'+edit['code']+'\n```\n'})
        response = ask_candidate(self.runner,callback)
        self.assertTrue(response['tool_calls'],response)
        _,error,_ = self.runner.batch(response)
        self.assertFalse(error,error)
        ok,feedback = self.runner.verify()
        self.assertTrue(ok,feedback)
        self.assertIn('onSubmit={save}',self.file.read_text())
        self.assertIn('onSubmit={search}',self.file.read_text())
        self.runner.cp.commit()

    def test_repeated_unchanged_companion_does_not_block_a_real_new_repair(self):
        proposal = self.retain()
        data = self.repair()
        data['changes'] = [proposal['edits'][0]] + data['changes']
        response = ask_candidate(self.runner,Mock(return_value={'content':json.dumps(data)}))
        self.assertTrue(response['tool_calls'],response)
        emitted=json.loads(response['tool_calls'][0]['function']['arguments'])
        self.assertEqual([e['node_id']for e in emitted['changes']],[self.aside['id']])
        _,error,_=self.runner.batch(response)
        self.assertFalse(error,error)
        ok,feedback=self.runner.verify()
        self.assertTrue(ok,feedback)
        self.assertIn('const search=',self.file.read_text())
        self.runner.cp.commit()

    def test_redundancy_filter_cannot_hide_duplicate_or_unknown_operations(self):
        proposal=self.retain()
        good=self.repair()['changes'][0]
        for changes in ([good,good],[proposal['edits'][0],dict(node_id='fake',code='bad')]):
            response=ask_candidate(self.runner,Mock(return_value={'content':json.dumps(dict(changes=changes,remove=[]))}))
            self.assertFalse(response['tool_calls'])
            self.assertEqual(self.file.read_text(),self.original)
            self.assertEqual(self.runner._failed_ast_candidate,proposal)

    def test_focused_repair_preserves_original_user_goal_above_stage_interpretation(self):
        self.retain()
        self.runner.requirement_gate.contract={'task':'화면 배치만 바꾸기'}
        self.runner.args.task='subordinate stage that mentions new CRUD'
        callback=Mock(return_value={'content':json.dumps(self.repair())})
        response=ask_candidate(self.runner,callback)
        self.assertTrue(response['tool_calls'])
        system=callback.call_args.args[0][0]['content']
        self.assertLess(system.index('화면 배치만 바꾸기'),system.index('subordinate stage'))
        self.assertIn('cannot be used to expand',system)
