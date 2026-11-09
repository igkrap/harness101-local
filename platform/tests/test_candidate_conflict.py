import copy
import json
import unittest
from unittest.mock import Mock

import test_candidate_repair as fixtures
from ast_editing import editor
from candidate_conflict import resolve_conflict


class CandidateConflictTests(unittest.TestCase):
    setUp=fixtures.CandidateRepairTests.setUp
    tearDown=fixtures.CandidateRepairTests.tearDown

    def overlapping(self):
        snap=editor(self.runner.h).snapshot(self.rel)
        self.parent=next(n for n in snap['nodes']if n['kind']=='JsxElement'and n['source'].startswith('<main>'))
        self.child=next(n for n in snap['nodes']if n['kind']=='JsxElement'and n['source'].startswith('<aside>'))
        edits=[dict(node_id=self.child['id'],code='<aside>updated</aside>'),dict(node_id=self.parent['id'],code=self.parent['source'].replace('<aside>empty</aside>','<aside>updated</aside>'))]
        self.runner.feedback='Overlapping edits'
        return dict(path=self.rel,snapshot_id=snap['snapshot_id'],source_hash=snap['source_hash'],edits=edits)

    def test_model_chooses_parent_or_child_without_rewriting_or_silent_drop(self):
        proposal=self.overlapping();original=copy.deepcopy(proposal)
        for choice,removed in [('A',self.child['id']),('B',self.parent['id'])]:
            ask=Mock(return_value={'content':choice})
            response=resolve_conflict(self.runner,proposal,ask)
            self.assertIsNotNone(response)
            args=json.loads(response['tool_calls'][0]['function']['arguments'])
            self.assertEqual(args,dict(changes=[],remove=[removed]))
            self.assertEqual(ask.call_args.args[1],[])
            self.assertEqual(proposal,original)
            self.assertEqual(self.file.read_text(),self.original)

    def test_resolution_uses_existing_atomic_checkpoint_and_native_checks(self):
        proposal=self.overlapping();self.runner._failed_ast_candidate=proposal
        self.runner.read.add(self.rel)
        response=resolve_conflict(self.runner,proposal,Mock(return_value={'content':'A'}))
        _,error,_=self.runner.batch(response)
        self.assertFalse(error,error)
        self.assertTrue(self.runner.cp.pending)
        ok,feedback=self.runner.verify()
        self.assertTrue(ok,feedback)
        self.assertIn('<aside>updated</aside>',self.file.read_text())
        self.assertIn('onSubmit={save}',self.file.read_text())
        self.runner.cp.commit()

    def test_adjacent_edits_and_stale_source_make_no_decision_call(self):
        proposal=self.overlapping()
        snap=editor(self.runner.h).snapshot(self.rel)
        form=next(n for n in snap['nodes']if n['kind']=='JsxElement'and n['source'].startswith('<form'))
        proposal['edits']=[dict(node_id=form['id'],code=form['source'].replace('추가','등록')),proposal['edits'][0]]
        ask=Mock()
        self.assertIsNone(resolve_conflict(self.runner,proposal,ask));ask.assert_not_called()
        proposal=self.overlapping();changed=self.original+'// user change';self.file.write_text(changed)
        self.assertIsNone(resolve_conflict(self.runner,proposal,ask));ask.assert_not_called()
        self.assertEqual(self.file.read_text(),changed)

    def test_invalid_reply_cannot_apply_and_generation_errors_propagate(self):
        proposal=self.overlapping()
        response=resolve_conflict(self.runner,proposal,Mock(return_value={'content':'EDIT n33'}))
        self.assertFalse(response.get('tool_calls'))
        self.assertEqual(self.file.read_text(),self.original)
        for error in (KeyboardInterrupt(),TimeoutError('headers timed out')):
            with self.assertRaises(type(error)):
                resolve_conflict(self.runner,proposal,Mock(side_effect=error))

    def test_zero_length_insertion_at_existing_node_start_is_a_conflict(self):
        snap=editor(self.runner.h).snapshot(self.rel)
        slot=next(n for n in snap['nodes']if n['kind']=='insert'and'function prologue'in n['label'])
        statement=next(n for n in snap['nodes']if n['source'].startswith('const save='))
        proposal=dict(path=self.rel,snapshot_id=snap['snapshot_id'],source_hash=snap['source_hash'],edits=[dict(node_id=slot['id'],code='const extra=1;'),dict(node_id=statement['id'],code=statement['source'].replace("'save'","'changed'"))])
        ask=Mock(return_value={'content':'A'})
        self.assertIsNotNone(resolve_conflict(self.runner,proposal,ask))
        self.assertEqual(ask.call_count,1)

    def test_runner_routes_overlap_to_single_choice_call_before_code_generation(self):
        self.runner._failed_ast_candidate=self.overlapping()
        self.runner.messages=[{'role':'user','content':'old generic context'}]
        self.runner.h.llm.chat=Mock(return_value={'choices':[{'message':{'content':'A'}}]})
        response=self.runner.ask(self.runner.messages,self.runner.tools())
        self.assertEqual(self.runner.used,1)
        self.assertEqual(self.runner.h.llm.chat.call_count,1)
        args=json.loads(response['tool_calls'][0]['function']['arguments'])
        self.assertEqual(args['remove'],[self.child['id']])
        prompt=self.runner.h.llm.chat.call_args.args[0][0]['content']
        self.assertIn(self.parent['id'],prompt)
        self.assertIn(self.child['id'],prompt)
        self.assertEqual(self.file.read_text(),self.original)
