import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_candidate_repair as fixtures
from ast_editing import editor
from ast_candidate_buffer import CandidateBuffer, CandidateStore
from virtual_candidate_runner import extend_virtual_candidate


def model_reply(changes):
    return {'choices': [{'message': {'tool_calls': [{'type': 'function', 'id': 'model-edit', 'function': {
        'name': 'replace_ast_fragments', 'arguments': json.dumps({'changes': changes})}}]}}]}


class VirtualCandidateTests(unittest.TestCase):
    proposal = fixtures.CandidateRepairTests.proposal

    def setUp(self):
        fixtures.CandidateRepairTests.setUp(self)
        self.store = CandidateStore(self.root / 'private-state', self.root, self.args.task)
        self.runner = extend_virtual_candidate(self.Runner, self.store)(self.args, self.Harness)

    def tearDown(self):
        buffer = self.runner._edit_buffer
        if self.runner.cp.pending:
            self.runner.cp.rollback()
        if buffer:
            buffer.close()
        fixtures.CandidateRepairTests.tearDown(self)

    def retain(self):
        self.runner.apply('inspect_code', {'path': self.rel, 'action': 'edit_ranges'}, {})
        self.runner.apply('apply_ast_edits', self.proposal(), {})
        ok, feedback = self.runner.verify()
        self.assertFalse(ok)
        self.runner.cp.rollback()
        self.runner.feedback = feedback

    def complete_form(self, snapshot):
        aside = next(n for n in snapshot['nodes'] if n['kind'] == 'JsxElement' and n['source'] == '<aside>empty</aside>')
        return {'node_id': aside['id'], 'code': '<aside><form onSubmit={save}><input aria-label="이름"/><button type="submit">추가</button></form></aside>'}

    def batch(self, response):
        paths, error, _ = self.runner.batch(response)
        self.assertFalse(error, error)
        self.assertEqual(paths, [self.rel])
        self.assertTrue(self.runner.cp.pending)

    def test_failed_candidate_is_reindexed_and_uses_normal_native_checks(self):
        self.retain()

        def chat(messages, tools=None):
            self.assertEqual([t['function']['name'] for t in tools], ['replace_ast_fragments'])
            buffer = self.runner._edit_buffer
            snap = buffer.snapshot()
            self.assertTrue(any(n['kind'] == 'VariableStatement' and n['source'].startswith('const search=') for n in snap['nodes']))
            self.assertIn('onSubmit={search}', messages[1]['content'])
            self.assertEqual(self.file.read_text(), self.original)
            return model_reply([self.complete_form(snap)])

        self.runner.h.llm.chat = Mock(side_effect=chat)
        response = self.runner.ask(self.runner.messages, self.runner.tools())
        self.assertEqual(self.file.read_text(), self.original)
        self.batch(response)
        ok, feedback = self.runner.verify()
        self.assertTrue(ok, feedback)
        self.assertIsNone(self.runner._failed_ast_candidate)
        self.assertIn('onSubmit={search}', self.file.read_text())
        self.assertIn('onSubmit={save}', self.file.read_text())
        self.runner.cp.commit()
        self.store.accept([self.rel])
        self.assertIsNone(self.store.load())

    def test_new_declaration_gets_a_real_node_after_failed_check_and_rollback(self):
        self.retain()

        def add_unused(messages, tools=None):
            snap = self.runner._edit_buffer.snapshot()
            slot = next(n for n in snap['nodes'] if n['kind'] == 'insert' and 'before return' in n['label'])
            return model_reply([{'node_id': slot['id'], 'code': 'const draftMarker="draft";'}])

        self.runner.h.llm.chat = Mock(side_effect=add_unused)
        self.batch(self.runner.ask(self.runner.messages, self.runner.tools()))
        ok, feedback = self.runner.verify()
        self.assertFalse(ok)
        self.runner.cp.rollback()
        self.runner.feedback = feedback
        self.assertEqual(self.file.read_text(), self.original)
        self.assertIsNone(self.runner._failed_ast_candidate)

        def repair_current(messages, tools=None):
            snap = self.runner._edit_buffer.snapshot()
            binding = next(n for n in snap['nodes'] if n['kind'] == 'VariableStatement' and n['source'] == 'const draftMarker="draft";')
            self.assertIn('draftMarker', binding['label'])
            return model_reply([{'node_id': binding['id'], 'code': ''}, self.complete_form(snap)])

        self.runner.h.llm.chat = Mock(side_effect=repair_current)
        self.batch(self.runner.ask(self.runner.messages, self.runner.tools()))
        ok, feedback = self.runner.verify()
        self.assertTrue(ok, feedback)
        self.assertNotIn('draftMarker', self.file.read_text())
        self.assertIn('const search=', self.file.read_text())
        self.runner.cp.commit()

    def test_durable_candidate_resumes_with_zero_model_calls_before_rechecking(self):
        self.retain()
        proposal = self.runner._failed_ast_candidate
        source = editor(self.runner.h).apply(self.rel, proposal['snapshot_id'], proposal['edits'])['new_text']
        buffer = CandidateBuffer(self.runner.h.workspace, editor(self.runner.h), self.rel, source)
        try:
            self.store.save(buffer.record('last check failed'))
        finally:
            buffer.close()
        self.runner.h.llm.chat = Mock(side_effect=AssertionError('resume must recheck before a model call'))
        response = self.runner.ask(self.runner.messages, self.runner.tools())
        self.runner.h.llm.chat.assert_not_called()
        self.batch(response)
        self.assertEqual(self.file.read_text(), source)
        ok, _ = self.runner.verify()
        self.assertFalse(ok)
        self.runner.cp.rollback()
        self.assertEqual(self.file.read_text(), self.original)

    def test_identical_candidate_binding_reflex_uses_native_checks_without_a_model_call(self):
        self.retain()
        proposal = self.runner._failed_ast_candidate
        source = editor(self.runner.h).apply(self.rel, proposal['snapshot_id'], proposal['edits'])['new_text']
        source = source.replace("const search=()=>console.log('query');", "const search=()=>console.log('query');const search=()=>console.log('query');")
        self.runner._edit_buffer = CandidateBuffer(self.runner.h.workspace, editor(self.runner.h), self.rel, source)
        self.runner._failed_ast_candidate = None
        self.runner.h.llm.chat = Mock(side_effect=AssertionError('identical binding reflex must not use a model'))
        self.batch(self.runner.ask(self.runner.messages, self.runner.tools()))
        self.runner.h.llm.chat.assert_not_called()
        self.assertEqual(self.file.read_text().count("const search=()=>console.log('query');"), 1)
        ok, _ = self.runner.verify()
        self.assertFalse(ok)
        self.runner.cp.rollback()
        self.assertEqual(self.file.read_text(), self.original)

    def test_concurrent_user_change_cannot_be_overwritten(self):
        self.retain()
        self.runner.h.llm.chat = Mock(side_effect=lambda messages, tools=None: model_reply([self.complete_form(self.runner._edit_buffer.snapshot())]))
        response = self.runner.ask(self.runner.messages, self.runner.tools())
        changed = self.original + '// user change\n'
        self.file.write_text(changed)
        _, error, _ = self.runner.batch(response)
        self.assertIn('Published source changed', error)
        self.assertEqual(self.file.read_text(), changed)
        self.assertFalse(self.runner.cp.pending)

    def test_invalid_fragment_is_feedback_and_preserves_the_private_candidate(self):
        self.retain()
        sources = []

        def invalid(messages, tools=None):
            buffer = self.runner._edit_buffer
            sources.append(buffer.source)
            aside = next(n for n in buffer.snapshot()['nodes'] if n['source'] == '<aside>empty</aside>')
            return model_reply([{'node_id': aside['id'], 'code': '<aside><broken>'}])

        self.runner.h.llm.chat = Mock(side_effect=invalid)
        result = self.runner.ask(self.runner.messages, self.runner.tools())
        self.assertEqual(result['tool_calls'], [])
        self.assertIn('AST_EDIT_FEEDBACK', self.runner._candidate_focus_error)
        self.assertEqual(self.runner._edit_buffer.source, sources[0])
        self.assertEqual(self.file.read_text(), self.original)
        self.assertFalse(self.runner.cp.pending)

    def test_small_variable_or_selfclosing_node_cannot_receive_a_screen_blob(self):
        self.retain()
        proposal = self.runner._failed_ast_candidate
        source = editor(self.runner.h).apply(self.rel, proposal['snapshot_id'], proposal['edits'])['new_text']
        buffer = CandidateBuffer(self.runner.h.workspace, editor(self.runner.h), self.rel, source)
        try:
            snap = buffer.snapshot()
            variable = next(n for n in snap['nodes'] if n['kind'] == 'VariableStatement')
            control = next(n for n in snap['nodes'] if n['kind'] == 'JsxSelfClosingElement')
            for node, code in [(variable, variable['source'] + '\nexport default function Other(){return <main/>}'), (control, '<section><form><input/></form></section>')]:
                with self.subTest(kind=node['kind']), self.assertRaises(ValueError):
                    buffer.prepare(snap['snapshot_id'], [{'node_id': node['id'], 'code': code}])
                self.assertEqual(buffer.source, source)
                self.assertEqual(self.file.read_text(), self.original)
                self.assertIsNone(buffer.pending)
        finally:
            buffer.close()

    def test_model_declaration_group_routes_peers_without_duplicates_through_native_checks(self):
        self.retain()
        def grouped(messages, tools=None):
            snap = self.runner._edit_buffer.snapshot()
            save = next(n for n in snap['nodes'] if n['source'] == "const save=()=>console.log('save');")
            code = "const filter='query';\n" + save['source'] + "\nconst search=()=>console.log(filter);"
            return model_reply([{'node_id': save['id'], 'code': code}, self.complete_form(snap)])
        self.runner.h.llm.chat = Mock(side_effect=grouped)
        self.batch(self.runner.ask(self.runner.messages, self.runner.tools()))
        ok, feedback = self.runner.verify()
        self.assertTrue(ok, feedback)
        source = self.file.read_text()
        self.assertEqual(source.count('const save='), 1)
        self.assertEqual(source.count('const search='), 1)
        self.assertIn("const filter='query';", source)
        self.assertTrue(any(k == 'autonomy.strategy' and d.get('reason') == 'candidate_fragment_edits_normalized' for k, d in self.events))

    def test_opening_tag_rename_reaches_native_checks_with_children_preserved(self):
        self.retain()

        def repair(messages, tools=None):
            self.assertIn('matching closing tag automatically', tools[0]['function']['description'])
            snap = self.runner._edit_buffer.snapshot()
            main = next(n for n in snap['nodes'] if n['kind'] == 'JsxOpeningElement' and n['source'] == '<main>')
            return model_reply([{'node_id': main['id'], 'code': '<section>'}])

        self.runner.h.llm.chat = Mock(side_effect=repair)
        self.batch(self.runner.ask(self.runner.messages, self.runner.tools()))
        source = self.file.read_text()
        self.assertIn('<section><form onSubmit={search}>', source)
        self.assertIn('<aside>empty</aside></section>', source)
        ok, _ = self.runner.verify()
        self.assertFalse(ok)  # Existing unused save/unfinished editor remains a failure.
        self.runner.cp.rollback()
        self.assertEqual(self.file.read_text(), self.original)
        self.runner.cp.rollback()
        self.assertEqual(self.file.read_text(), self.original)

    def test_after_truncation_fragment_schema_enforces_small_edits_and_keeps_candidate(self):
        self.retain()
        self.runner._compact_fragment_output = True
        def oversized(messages, tools=None):
            changes = tools[0]['function']['parameters']['properties']['changes']
            self.assertEqual(changes['maxItems'], 2)
            self.assertEqual(changes['items']['properties']['code']['maxLength'], 2400)
            snap = self.runner._edit_buffer.snapshot()
            edit = self.complete_form(snap)
            edit['code'] += ' ' * 2400
            return model_reply([edit])
        self.runner.h.llm.chat = Mock(side_effect=oversized)
        response = self.runner.ask(self.runner.messages, self.runner.tools())
        self.assertFalse(response.get('tool_calls'))
        self.assertEqual(self.file.read_text(), self.original)
        self.assertFalse(self.runner.cp.pending)
        self.assertIn('2400', self.runner._candidate_focus_error)

    def test_opening_tag_remains_available_for_a_precise_attribute_edit(self):
        self.retain()
        def edit_attributes(messages, tools=None):
            snap = self.runner._edit_buffer.snapshot()
            node = next(n for n in snap['nodes'] if n['kind'] == 'JsxOpeningElement' and n['source'] == '<main>')
            self.assertIn('NODE ' + node['id'] + ' KIND JsxOpeningElement', messages[1]['content'])
            return model_reply([{'node_id': node['id'], 'code': '<main aria-label="편집 화면">'}])
        self.runner.h.llm.chat = Mock(side_effect=edit_attributes)
        self.batch(self.runner.ask(self.runner.messages, self.runner.tools()))
        self.assertIn('<main aria-label="편집 화면">', self.file.read_text())
        self.assertIn('onSubmit={search}', self.file.read_text())
        self.runner.cp.rollback()
        self.assertEqual(self.file.read_text(), self.original)

    def test_component_owner_api_survives_plugin_errors_and_is_cached(self):
        source = (Path(__file__).parent / 'fixtures/ast_dense_inventory.tsx').read_text()
        self.runner._edit_buffer = CandidateBuffer(self.runner.h.workspace, editor(self.runner.h), self.rel, source)
        self.runner.feedback = 'frontend/src/App.tsx(1,1): error TS2560: Function has no properties in common with TablePlugin.'
        self.runner.h.llm.chat = Mock(return_value={'choices': [{'message': {'content': ''}}]})
        fact = 'interface TableProps { plugins?: Record<string, TablePlugin>; }'
        with patch('installed_type_records.declarations', return_value=[fact]) as retrieve:
            for _ in range(2):
                self.runner.ask(self.runner.messages, self.runner.tools())
                self.assertIn(fact, self.runner.h.llm.chat.call_args.args[0][1]['content'])
            retrieve.assert_called_once_with(self.runner.h.workspace.root, ['TableProps', 'TableColumn', 'TablePlugin'])

    def test_browser_failure_becomes_the_subtask_without_replacing_the_original_goal(self):
        self.retain()
        proposal = self.runner._failed_ast_candidate
        source = editor(self.runner.h).apply(self.rel, proposal['snapshot_id'], proposal['edits'])['new_text']
        self.runner._edit_buffer = CandidateBuffer(self.runner.h.workspace, editor(self.runner.h), self.rel, source)
        self.runner._failed_ast_candidate = None
        self.runner.feedback = '[frontend] Success\n[framework] Error: Command failed: node browser\nError: Search click leaves Copper visible'
        self.runner.h.llm.chat = Mock(return_value={'choices': [{'message': {'content': ''}}]})
        self.runner.ask(self.runner.messages, self.runner.tools())
        messages = self.runner.h.llm.chat.call_args.args[0]
        self.assertIn('ORIGINAL REQUEST: ' + self.args.task, messages[0]['content'])
        self.assertIn('CURRENT STAGE: Repair ONLY this observed behavior', messages[0]['content'])
        self.assertIn('Search click leaves Copper visible', messages[0]['content'])

    def test_token_cannot_publish_an_unrelated_or_unprepared_buffer(self):
        self.retain()
        self.runner.h.llm.chat = Mock(side_effect=lambda messages, tools=None: model_reply([self.complete_form(self.runner._edit_buffer.snapshot())]))
        response = self.runner.ask(self.runner.messages, self.runner.tools())
        forged = copy.deepcopy(response)
        data = json.loads(forged['tool_calls'][0]['function']['arguments'])
        data['token'] = 'forged'
        forged['tool_calls'][0]['function']['arguments'] = json.dumps(data)
        _, error, _ = self.runner.batch(forged)
        self.assertIn('No matching validated candidate', error)
        self.assertEqual(self.file.read_text(), self.original)
        self.assertFalse(self.runner.cp.pending)

    def test_unreachable_column_branch_and_prior_rejection_reach_model(self):
        source = self.original.replace('return (', "const columns=[{key:'name'}];return (").replace(
            '<aside>empty</aside>', '<aside><Table columns={columns} plugins={{actions:{transformBodyCell:(props,column)=>column.key === \'actions\' ? props : props}}}/></aside>')
        self.runner._edit_buffer = CandidateBuffer(self.runner.h.workspace, editor(self.runner.h), self.rel, source)
        self.runner._candidate_focus_error = 'No actual repair changes'
        self.runner.feedback = 'Error: selecting row does not populate editor'
        self.runner.h.llm.chat = Mock(return_value={'choices': [{'message': {'content': ''}}]})
        self.runner.ask(self.runner.messages, self.runner.tools())
        packet = self.runner.h.llm.chat.call_args.args[0][-1]['content']
        self.assertIn('LAST REJECTED PROPOSAL: No actual repair changes', packet)
        self.assertIn('"unreachable_cell_branch_keys": ["actions"]', packet)
        self.assertEqual(self.file.read_text(), self.original)

    def test_other_task_and_changed_base_do_not_resume_saved_code(self):
        self.retain()
        proposal = self.runner._failed_ast_candidate
        source = editor(self.runner.h).apply(self.rel, proposal['snapshot_id'], proposal['edits'])['new_text']
        buffer = CandidateBuffer(self.runner.h.workspace, editor(self.runner.h), self.rel, source)
        try:
            self.store.save(buffer.record('failed'))
        finally:
            buffer.close()
        other = CandidateStore(self.store.file.parent, self.root, 'different task')
        self.assertIsNone(other.load())
        self.file.write_text(self.original + '// changed\n')
        self.assertFalse(self.runner._saved_buffer())
        self.assertIsNone(self.runner._edit_buffer)
