import copy
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
import candidate_snippet_repair as repair
from snippet_patch_parser import parse_patches


def block(node, old, new):
    return f'PATCH {node}\n```old\n{old}\n```\n```new\n{new}\n```\n'


class SnippetRepairTests(unittest.TestCase):
    def setUp(self):
        self.proposal = dict(path='frontend/src/Test.tsx', snapshot_id='snapshot', source_hash='hash', edits=[
            dict(node_id='s1', code='const count = 1;\nconst extra = 2;'),
            dict(node_id='n1', code='<Text>before</Text>'),
        ])
        self.catalog = [dict(id='s1', kind='insert', label='function statements', source=''),
                        dict(id='n1', kind='JsxElement', label='render', source='<Text>original</Text>'),
                        dict(id='n0', kind='VariableStatement', label='original binding', source='const count = 1;')]
        self.runner = SimpleNamespace(used=7, args=SimpleNamespace(task='test'), feedback='duplicate count', h=SimpleNamespace(log_event=Mock()))
        self.ed = Mock()
        self.ed.apply.return_value = {'new_text': 'validated candidate'}

    def call(self, response):
        ask = Mock(return_value={'content': response, 'tool_calls': []})
        before = copy.deepcopy(self.proposal)
        with patch.object(repair, 'editor', return_value=self.ed), patch.object(repair, 'format_candidate_context', return_value='test context'):
            result = repair.ask_snippets(self.runner, self.proposal, self.catalog, ask)
        self.assertEqual(self.proposal, before)
        self.assertEqual(self.runner.used, 7)
        ask.assert_called_once()
        return result

    def args(self, result):
        return json.loads(result['tool_calls'][0]['function']['arguments'])

    def test_removes_only_duplicate_snippet_and_keeps_companions(self):
        args = self.args(self.call(block('s1', 'const count = 1;\n', '')))
        self.assertEqual(args['changes'], [dict(node_id='s1', code='const extra = 2;')])
        self.assertEqual(args['remove'], [])
        validated = self.ed.apply.call_args.args[2]
        self.assertIn(self.proposal['edits'][1], validated)

    def test_sequential_patches_use_retained_content(self):
        args = self.args(self.call(block('n1', 'before', 'middle') + block('n1', 'middle', 'after')))
        self.assertEqual(args['changes'], [dict(node_id='n1', code='<Text>after</Text>')])

    def test_native_call_without_content_preserves_checkpoint_boundary(self):
        patches = [dict(node_id='n1', old_text='before', new_text='after')]
        ask = Mock(return_value={'tool_calls': [{'function': {'name': 'apply_snippet_patch', 'arguments': json.dumps({'patches': patches})}}]})
        with patch.object(repair, 'editor', return_value=self.ed), patch.object(repair, 'format_candidate_context', return_value='test context'):
            result = repair.ask_snippets(self.runner, self.proposal, self.catalog, ask)
        self.assertEqual(self.args(result)['changes'], [dict(node_id='n1', code='<Text>after</Text>')])
        self.assertEqual(self.proposal['edits'][1]['code'], '<Text>before</Text>')
        messages, tools = ask.call_args.args
        self.assertEqual([t['function']['name'] for t in tools], ['replace_ast_fragments'])
        self.assertTrue(messages[0]['content'].startswith('ORIGINAL REQUEST:'))
        self.assertNotIn('```old', messages[0]['content'])

    def test_native_ast_fragment_needs_no_original_anchor_and_keeps_companions(self):
        delta = {'changes': [{'node_id': 'n1', 'code': '<Text>after</Text>'}], 'remove': []}
        ask = Mock(return_value={'tool_calls': [{'function': {'name': 'repair_ast_candidate', 'arguments': json.dumps(delta)}}]})
        with patch.object(repair, 'editor', return_value=self.ed), patch.object(repair, 'format_candidate_context', return_value='test context'):
            result = repair.ask_snippets(self.runner, self.proposal, self.catalog, ask)
        self.assertEqual(self.args(result), delta)
        self.assertEqual(self.proposal['edits'][0]['code'], 'const count = 1;\nconst extra = 2;')

    def test_native_ast_replay_of_unchanged_companion_is_compacted(self):
        delta = {'changes': self.proposal['edits'][:1] + [{'node_id': 'n1', 'code': '<Text>after</Text>'}], 'remove': []}
        ask = Mock(return_value={'tool_calls': [{'function': {'name': 'repair_ast_candidate', 'arguments': json.dumps(delta)}}]})
        with patch.object(repair, 'editor', return_value=self.ed), patch.object(repair, 'format_candidate_context', return_value='test context'):
            result = repair.ask_snippets(self.runner, self.proposal, self.catalog, ask)
        self.assertEqual(self.args(result)['changes'], [{'node_id': 'n1', 'code': '<Text>after</Text>'}])

    def test_primary_fragment_tool_has_no_cancellation_field(self):
        changes = [{'node_id': 'n1', 'code': '<Text>after</Text>'}]
        ask = Mock(return_value={'tool_calls': [{'function': {'name': 'replace_ast_fragments', 'arguments': json.dumps({'changes': changes})}}]})
        with patch.object(repair, 'editor', return_value=self.ed), patch.object(repair, 'format_candidate_context', return_value='test context'):
            result = repair.ask_snippets(self.runner, self.proposal, self.catalog, ask)
        self.assertEqual(self.args(result), {'changes': changes, 'remove': []})
        spec = ask.call_args.args[1][0]['function']
        self.assertEqual(spec['name'], 'replace_ast_fragments')
        self.assertEqual(spec['parameters']['required'], ['changes'])
        self.assertNotIn('remove', spec['parameters']['properties'])

    def test_primary_fragment_tool_rejects_cancellation_and_duplicate_keys(self):
        for args in ['{"changes":[],"remove":["n1"]}', '{"changes":[],"changes":[]}']:
            ask = Mock(return_value={'tool_calls': [{'function': {'name': 'replace_ast_fragments', 'arguments': args}}]})
            with patch.object(repair, 'editor', return_value=self.ed), patch.object(repair, 'format_candidate_context', return_value='test context'):
                result = repair.ask_snippets(self.runner, self.proposal, self.catalog, ask)
            self.assertEqual(result['tool_calls'], [])

    def test_unchanged_companion_does_not_block_real_text_patch(self):
        patches = parse_patches(block('n1', 'before', 'after') + block('n0', 'same', 'same'))
        self.assertEqual(patches, [dict(node_id='n1', old_text='before', new_text='after')])

    def test_can_patch_current_node_without_discarding_retained_operations(self):
        args = self.args(self.call(block('n0', '1', '3')))
        self.assertEqual(args['changes'], [dict(node_id='n0', code='const count = 3;')])
        self.assertEqual(len(self.ed.apply.call_args.args[2]), 3)

    def test_whole_retained_operation_deletion_uses_remove(self):
        args = self.args(self.call(block('s1', self.proposal['edits'][0]['code'], '')))
        self.assertEqual(args, {'changes': [], 'remove': ['s1']})

    def test_invalid_anchor_or_ambiguous_anchor_never_reaches_editor(self):
        for response in [block('s1', 'missing', 'x'), block('n1', 'e', 'x'), block('invented', 'a', 'b')]:
            with self.subTest(response=response):
                self.assertEqual(self.call(response)['tool_calls'], [])
        self.ed.apply.assert_not_called()

    def test_current_declaration_deletion_goes_through_native_ast_validator(self):
        args = self.args(self.call(block('n0', self.catalog[-1]['source'], '')))
        self.assertEqual(args, {'changes': [{'node_id': 'n0', 'code': ''}], 'remove': []})
        self.ed.apply.assert_called_once()

    def test_deleting_retained_replacement_does_not_restore_original_source(self):
        args = self.args(self.call(block('n1', '<Text>before</Text>', '')))
        self.assertEqual(args, {'changes': [{'node_id': 'n1', 'code': ''}], 'remove': []})

    def test_empty_anchor_can_create_only_a_known_empty_ast_slot(self):
        self.catalog.append(dict(id='s2', kind='insert', label='before return', source=''))
        args = self.args(self.call(block('s2', '', 'const query = "";')))
        self.assertEqual(args['changes'], [dict(node_id='s2', code='const query = "";')])
        self.assertEqual(len(self.ed.apply.call_args.args[2]), 3)

    def test_empty_anchor_cannot_overwrite_existing_or_original_nodes(self):
        self.catalog.append(dict(id='emptyOriginal', kind='VariableStatement', label='original', source=''))
        for node in ['n1', 's1', 'emptyOriginal', 'invented']:
            with self.subTest(node=node):
                self.assertEqual(self.call(block(node, '', 'const unexpected = 1;'))['tool_calls'], [])
        self.ed.apply.assert_not_called()

    def test_scope_or_stale_snapshot_failure_does_not_write(self):
        self.ed.apply.side_effect = ValueError('stale snapshot')
        self.assertEqual(self.call(block('n1', 'before', 'after'))['tool_calls'], [])

    def test_transport_exception_propagates(self):
        with patch.object(repair, 'editor', return_value=self.ed), patch.object(repair, 'format_candidate_context', return_value='test context'), self.assertRaises(TimeoutError):
            repair.ask_snippets(self.runner, self.proposal, self.catalog, Mock(side_effect=TimeoutError('timeout')))

    def test_existing_strict_json_response_keeps_native_compatibility(self):
        delta = {'changes': [{'node_id': 'n1', 'code': '<Text>after</Text>'}], 'remove': []}
        self.assertEqual(self.args(self.call(json.dumps(delta))), delta)

    def test_legacy_response_does_not_bypass_duplicate_key_validation(self):
        result = self.call('{"changes": [], "changes": [{"node_id":"n1","code":"<Text>after</Text>"}], "remove": []}')
        self.assertEqual(result['tool_calls'], [])

    def test_parser_preserves_crlf_and_optional_line_annotation(self):
        text = 'PATCH s1 line 42\r\n```old\r\na\r\nb\r\n```\r\n```new\r\nc\r\n```\r\n'
        self.assertEqual(parse_patches(text), [dict(node_id='s1', old_text='a\r\nb', new_text='c')])

    def test_parser_rejects_prose_noop_and_broken_fences(self):
        for text in ['prose\n' + block('n1', 'a', 'b'), block('n1', 'a', 'a'), 'PATCH n1\n```old\na', '']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_patches(text)


class NativeSnippetRepairTests(unittest.TestCase):
    def setUp(self):
        import test_candidate_repair as fixtures
        fixtures.CandidateRepairTests.setUp(self)

    def tearDown(self):
        import test_candidate_repair as fixtures
        fixtures.CandidateRepairTests.tearDown(self)

    def test_snippets_reach_native_checkpoint_and_preserve_other_edits(self):
        import test_candidate_repair as fixtures
        from ast_editing import editor
        proposal = fixtures.CandidateRepairTests.proposal(self)
        snap = editor(self.runner.h).snapshot(self.rel)
        proposal['source_hash'] = snap['source_hash']
        self.runner._failed_ast_candidate = proposal
        self.runner.read.add(self.rel)
        reply = block(self.aside['id'], 'empty', '<form onSubmit={save}><input aria-label="이름"/><button type="submit">추가</button></form>')
        response = repair.ask_snippets(self.runner, proposal, snap['nodes'], Mock(return_value={'content': reply}))
        self.assertEqual(self.file.read_text(), self.original)
        self.assertTrue(response['tool_calls'], response)
        _, error, _ = self.runner.batch(response)
        self.assertFalse(error, error)
        self.assertTrue(self.runner.cp.pending)
        ok, feedback = self.runner.verify()
        self.assertTrue(ok, feedback)
        self.assertIn('const search=', self.file.read_text())
        self.assertIn('onSubmit={search}', self.file.read_text())
        self.assertIn('onSubmit={save}', self.file.read_text())
        self.runner.cp.commit()

    def test_empty_slot_and_its_jsx_use_are_one_native_atomic_edit(self):
        import test_candidate_repair as fixtures
        from ast_editing import editor
        proposal = fixtures.CandidateRepairTests.proposal(self)
        snap = editor(self.runner.h).snapshot(self.rel)
        proposal['source_hash'] = snap['source_hash']
        slot = next(n for n in snap['nodes'] if n['kind'] == 'insert' and 'before return' in n['label'])
        self.runner._failed_ast_candidate = proposal
        self.runner.read.add(self.rel)
        reply = block(slot['id'], '', 'const note="draft";') + block(self.aside['id'], 'empty', '<form onSubmit={save}><input aria-label="이름"/><span>{note}</span><button type="submit">추가</button></form>')
        response = repair.ask_snippets(self.runner, proposal, snap['nodes'], Mock(return_value={'content': reply}))
        self.assertEqual(self.file.read_text(), self.original)
        self.assertTrue(response['tool_calls'], response)
        _, error, _ = self.runner.batch(response)
        self.assertFalse(error, error)
        ok, feedback = self.runner.verify()
        self.assertTrue(ok, feedback)
        self.assertIn('const note="draft";', self.file.read_text())
        self.assertIn('{note}', self.file.read_text())
        self.runner.cp.commit()

    def test_deleting_unused_original_declaration_uses_native_source_span(self):
        from ast_editing import editor
        clean = self.original
        self.original = self.original.replace('const save=', 'const unused_original=1;const save=', 1)
        self.file.write_text(self.original)
        snap = editor(self.runner.h).snapshot(self.rel)
        node = next(n for n in snap['nodes'] if n['source'] == 'const unused_original=1;')
        proposal = dict(path=self.rel, snapshot_id=snap['snapshot_id'], source_hash=snap['source_hash'], edits=[])
        self.runner._failed_ast_candidate = proposal
        self.runner.read.add(self.rel)
        response = repair.ask_snippets(self.runner, proposal, snap['nodes'], Mock(return_value={'content': block(node['id'], node['source'], '')}))
        self.assertEqual(self.file.read_text(), self.original)
        self.assertTrue(response['tool_calls'], response)
        _, error, _ = self.runner.batch(response)
        self.assertFalse(error, error)
        ok, feedback = self.runner.verify()
        self.assertTrue(ok, feedback)
        self.assertEqual(self.file.read_text(), clean)
        self.runner.cp.commit()
