import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
from test_autonomy import native
from code_intelligence import Service


class AstEditTests(unittest.TestCase):
    def setUp(self):
        from ast_editing import Editor
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.rel = 'frontend/src/screens/Demo.tsx'
        self.file = self.root / self.rel
        self.file.parent.mkdir(parents=True)
        self.original = (
            '// 😀 한글: preserve this comment\r\n'
            "import {useState} from 'react';\r\n"
            "export const meta = {title:'등록'};\r\n"
            "export default function Demo(){\r\n"
            "  const label = 'same';\r\n"
            "  const [count,setCount] = useState(0);\r\n"
            "  return (<form><h1>등록</h1><button onClick={()=>setCount(count+1)}>{label}</button></form>);\r\n"
            "}\r\n"
            "export function Other(){const label = 'same';return <aside>{label}</aside>;}\r\n"
        )
        self.file.write_bytes(self.original.encode())
        self.service = Service(native.WorkspaceManager(self.root))
        self.editor = Editor(self.service)

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def snapshot(self):
        return self.editor.snapshot(self.rel)

    def find(self, snap, source):
        return next(n for n in snap['nodes'] if n['source'] == source)

    def apply(self, snap, edits):
        return self.editor.apply(self.rel, snap['snapshot_id'], edits)

    def test_catalog_uses_real_ast_without_file_or_function_replacements(self):
        snap = self.snapshot()
        self.assertEqual(snap['path'], self.rel)
        self.assertTrue(snap['source_hash'])
        self.assertTrue(snap['nodes'])
        for node in snap['nodes']:
            self.assertNotIn('start', node)
            self.assertNotIn('end', node)
            self.assertNotIn(node['kind'], ('SourceFile', 'FunctionDeclaration', 'ClassDeclaration', 'Block'))
            self.assertNotEqual(node['source'], self.original)
        self.assertTrue(any(n['kind'] == 'insert' and 'Demo' in n['label'] and 'JSX' in n['label'] for n in snap['nodes']))

    def test_duplicate_text_targets_one_ast_node_and_preserves_unicode_crlf(self):
        snap = self.snapshot()
        node = self.find(snap, "const label = 'same';")
        result = self.apply(snap, [{'node_id': node['id'], 'code': "const label = 'changed';"}])
        expected = self.original.replace("const label = 'same';", "const label = 'changed';", 1)
        self.assertEqual(result['new_text'].encode(), expected.encode())
        self.assertIn("export function Other(){const label = 'same';", result['new_text'])
        self.assertEqual(self.file.read_bytes(), self.original.encode())

    def test_import_node_may_expand_to_multiple_imports_of_same_kind(self):
        snap = self.snapshot()
        node = self.find(snap, "import {useState} from 'react';")
        replacement = "import {useState} from 'react';\nimport {Icon} from 'ui/Icon';\nimport {Heading} from 'ui/Heading';"
        result = self.apply(snap, [{'node_id': node['id'], 'code': replacement}])
        self.assertEqual(result['new_text'], self.original.replace(node['source'], replacement, 1))
        self.assertEqual(self.file.read_bytes(), self.original.encode())

    def test_failed_fragment_feedback_identifies_node_code_location_and_fix(self):
        snap = self.snapshot()
        node = self.find(snap, "const label = 'same';")
        bad = 'const label = ;'
        with self.assertRaises(ValueError) as caught:
            self.apply(snap, [{'node_id': node['id'], 'code': bad}])
        message = str(caught.exception)
        self.assertTrue(message.startswith('AST_EDIT_FEEDBACK '), message)
        detail = json.loads(message[len('AST_EDIT_FEEDBACK '):])
        self.assertEqual(detail['node_id'], node['id'])
        self.assertEqual(detail['path'], self.rel)
        self.assertEqual(detail['expected_kind'], node['kind'])
        self.assertEqual(detail['original_code'], node['source'])
        self.assertEqual(detail['proposed_code'], bad)
        self.assertEqual(detail['diagnostics'][0]['line'], 1)
        self.assertGreater(detail['diagnostics'][0]['column'], 0)
        self.assertFalse(detail['source_changed'])
        self.assertTrue(detail['fix_hint'])
        self.assertIn('const label', detail['error_context'])
        self.assertEqual(self.file.read_bytes(), self.original.encode())

    def test_feedback_reports_code_relative_multiline_location(self):
        snap = self.snapshot()
        node = self.find(snap, "const label = 'same';")
        with self.assertRaises(ValueError) as caught:
            self.apply(snap, [{'node_id': node['id'], 'code': 'const label =\n  ;'}])
        detail = json.loads(str(caught.exception).split('AST_EDIT_FEEDBACK ', 1)[1])
        self.assertEqual(detail['diagnostics'][0]['line'], 2)
        self.assertEqual(detail['diagnostics'][0]['column'], 3)
        self.assertIn('const label =\n  ;', detail['error_context'])

    def test_invalid_validator_response_is_reported_with_the_failed_node(self):
        from unittest.mock import patch
        snap = self.snapshot()
        node = self.find(snap, "const label = 'same';")
        response = SimpleNamespace(returncode=0, stdout='not-json', stderr='')
        with patch('ast_feedback.subprocess.run', return_value=response):
            with self.assertRaises(ValueError) as caught:
                self.apply(snap, [{'node_id': node['id'], 'code': "const label = 'valid';"}])
        detail = json.loads(str(caught.exception).split('AST_EDIT_FEEDBACK ', 1)[1])
        self.assertIn('malformed JSON', detail['error'])
        self.assertEqual(detail['node_id'], node['id'])
        self.assertEqual(self.file.read_bytes(), self.original.encode())

    def test_exact_failed_edit_feedback_survives_context_rebuild(self):
        from autonomy_runtime import Runner
        args = SimpleNamespace(task='제목 수정', workspace=str(self.root), check='frontend', max_rounds=0, ponytail='off', llm_url='http://127.0.0.1:8099/v1', model='fixture')
        runner = Runner(args, native.Harness)
        runner.h.evidence_path = self.root / 'test-events.jsonl'
        runner.steps = [{'title': args.task, 'kind': 'change'}]
        try:
            snap = runner.apply('inspect_code', {'path': self.rel, 'action': 'edit_ranges'}, {})
            node = self.find(snap, "const label = 'same';")
            operation = {'path': self.rel, 'snapshot_id': snap['snapshot_id'], 'edits': [{'node_id': node['id'], 'code': 'const label = ;'}]}
            paths, error, finished = runner.batch({'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'bad-scoped-edit', 'type': 'function', 'function': {'name': 'apply_ast_edits', 'arguments': json.dumps(operation)}}]})
            self.assertFalse(paths)
            self.assertFalse(finished)
            runner.feedback = error
            runner.fresh('tool error')
            prompt = json.dumps(runner.messages, ensure_ascii=False)
            for expected in (node['id'], 'const label = ;', 'original_code', 'fix_hint', 'diagnostics'):
                self.assertIn(expected, prompt)
            self.assertFalse(runner.cp.pending)
        finally:
            self.service.close()
            if getattr(runner.h, '_code_intelligence', None):
                runner.h._code_intelligence.close()

    def test_focused_read_delivers_complete_screen_above_old_six_thousand_char_cap(self):
        from autonomy_runtime import Runner
        content = self.original + '\n//' + ('x' * 6100) + '\n'
        self.file.write_text(content)
        args = SimpleNamespace(task='Demo 화면 수정', workspace=str(self.root), check='frontend',
                               max_rounds=16, context_profile='focused', ponytail='off',
                               llm_url='http://127.0.0.1:8099/v1', model='fixture')
        runner = Runner(args, native.Harness)
        runner.h.evidence_path = self.root / 'read-events.jsonl'
        try:
            call = {'id': 'read-screen', 'type': 'function', 'function': {
                'name': 'read_file', 'arguments': json.dumps({'path': self.rel})}}
            runner.batch({'role': 'assistant', 'content': None, 'tool_calls': [call]})
            observed = json.loads(runner.messages[-1]['content'])
            self.assertEqual(observed['content'], content)
            self.assertIn(self.rel, runner.read)
        finally:
            if getattr(runner.h, '_code_intelligence', None):
                runner.h._code_intelligence.close()

    def test_jsx_child_slot_is_inside_existing_root(self):
        snap = self.snapshot()
        slot = next(n for n in snap['nodes'] if n['kind'] == 'insert' and 'Demo' in n['label'] and 'JSX' in n['label'])
        result = self.apply(snap, [{'node_id': slot['id'], 'code': '<Table data={[]}/>'}])
        self.assertIn('<Table data={[]}/>\n</form>', result['new_text'])
        self.assertIn('<button onClick={()=>setCount(count+1)}>{label}</button>', result['new_text'])

    def test_stale_snapshot_does_not_overwrite_external_change(self):
        snap = self.snapshot()
        changed = self.original + '// concurrent edit\n'
        self.file.write_bytes(changed.encode())
        with self.assertRaises(ValueError):
            self.apply(snap, [{'node_id': snap['nodes'][0]['id'], 'code': 'const value=1;'}])
        self.assertEqual(self.file.read_bytes(), changed.encode())

    def test_optional_snapshot_id_uses_latest_provided_scope(self):
        from ast_editing import TOOL
        snap = self.snapshot()
        node = self.find(snap, "const label = 'same';")
        result = self.editor.apply(self.rel, None, [{'node_id': node['id'], 'code': "const label = 'bound';"}])
        self.assertIn("const label = 'bound';", result['new_text'])
        self.assertNotIn('snapshot_id', TOOL['function']['parameters']['required'])
        self.assertEqual(self.file.read_bytes(), self.original.encode())

    def test_unknown_snapshot_feedback_names_file_and_next_inspection(self):
        snap = self.snapshot()
        node = self.find(snap, "const label = 'same';")
        with self.assertRaises(ValueError) as caught:
            self.editor.apply(self.rel, 'invented-id', [{'node_id': node['id'], 'code': "const label = 'wrong';"}])
        message = str(caught.exception)
        for expected in (self.rel, 'inspect_code', 'edit_ranges', snap['snapshot_id']):
            self.assertIn(expected, message)
        self.assertEqual(self.file.read_bytes(), self.original.encode())

    def test_first_frontend_context_provides_real_edit_scopes_without_model_call(self):
        from autonomy_runtime import Runner
        from unittest.mock import Mock
        app = self.root / 'frontend/src/App.tsx'
        app.write_bytes(self.original.encode())
        args = SimpleNamespace(task='사이드 패널 로고 추가', workspace=str(self.root), check='frontend', max_rounds=0, ponytail='off', llm_url='http://127.0.0.1:8099/v1', model='fixture')
        runner = Runner(args, native.Harness)
        runner.h.evidence_path = self.root / 'test-events.jsonl'
        runner.h.llm.chat = Mock(side_effect=AssertionError('context setup must not call the model'))
        runner.steps = [{'title': args.task, 'kind': 'change'}]
        try:
            runner.fresh()
            prompt = json.dumps(runner.messages, ensure_ascii=False)
            self.assertIn('CURRENT AST EDIT SCOPES', prompt)
            self.assertIn('snapshot_id', prompt)
            self.assertIn('source_hash', prompt)
            self.assertIn('frontend/src/App.tsx', runner.read)
            runner.h.llm.chat.assert_not_called()
        finally:
            if getattr(runner.h, '_code_intelligence', None):
                runner.h._code_intelligence.close()

    def test_overlapping_parent_and_child_are_rejected(self):
        snap = self.snapshot()
        parent = next(n for n in snap['nodes'] if n['kind']=='JsxElement' and n['source'].startswith('<form>'))
        child = self.find(snap, '<h1>등록</h1>')
        with self.assertRaisesRegex(ValueError, f"{parent['id']} contains {child['id']}; remove the {child['id']} edit"):
            self.apply(snap, [{'node_id': parent['id'], 'code': '<form/>'}, {'node_id': child['id'], 'code': '<h2>수정</h2>'}])

    def test_exact_child_change_embedded_in_parent_is_one_atomic_edit(self):
        snap = self.snapshot()
        parent = next(n for n in snap['nodes'] if n['kind'] == 'JsxElement' and n['source'].startswith('<form>'))
        child = self.find(snap, '<h1>등록</h1>')
        replacement = parent['source'].replace(child['source'], '<h2>수정</h2>')
        expected = self.original.replace(parent['source'], replacement)
        for edits in ([{'node_id': child['id'], 'code': '<h2>수정</h2>'},
                       {'node_id': parent['id'], 'code': replacement}],
                      [{'node_id': parent['id'], 'code': replacement},
                       {'node_id': child['id'], 'code': '<h2>수정</h2>'}]):
            with self.subTest(order=[item['node_id'] for item in edits]):
                result = self.apply(snap, edits)
                self.assertEqual(result['new_text'], expected)
                self.assertEqual(result['edited_nodes'], [parent['id']])

    def test_insertion_inside_replaced_node_is_rejected(self):
        snap = self.snapshot()
        parent = next(n for n in snap['nodes'] if n['kind']=='JsxElement' and n['source'].startswith('<form>'))
        slot = next(n for n in snap['nodes'] if n['kind'] == 'insert' and 'Demo' in n['label'] and 'JSX' in n['label'])
        with self.assertRaisesRegex(ValueError, 'Overlapping'):
            self.apply(snap, [{'node_id': parent['id'], 'code': '<form/>'}, {'node_id': slot['id'], 'code': '<Table/>'}])

    def test_untrusted_offsets_paths_and_node_ids_are_rejected(self):
        snap = self.snapshot()
        node = self.find(snap, "const label = 'same';")
        for edits in ([], [{'node_id': 'invented', 'code': 'x'}], [{'node_id': node['id'], 'code': 'x', 'start': 0}], [{'node_id': node['id'], 'code': 'x'}] * 2):
            with self.assertRaises(ValueError):
                self.apply(snap, edits)
        other = self.file.parent / 'Other.tsx'
        other.write_text('export const x=1;')
        with self.assertRaises(ValueError):
            self.editor.apply(str(other.relative_to(self.root)), snap['snapshot_id'], [{'node_id': node['id'], 'code': 'const x=1;'}])

    def test_syntax_errors_are_rejected_before_writing(self):
        snap = self.snapshot()
        node = self.find(snap, "const label = 'same';")
        with self.assertRaises(ValueError):
            self.apply(snap, [{'node_id': node['id'], 'code': 'const broken = ;'}])
        self.assertEqual(self.file.read_bytes(), self.original.encode())

    def test_existing_syntax_error_can_be_repaired_inside_recovered_node(self):
        broken = self.original.replace("const label = 'same';", 'const label = ;', 1)
        self.file.write_bytes(broken.encode())
        snap = self.snapshot()
        self.assertTrue(snap['diagnostics'])
        node = self.find(snap, 'const label = ;')
        result = self.apply(snap, [{'node_id': node['id'], 'code': "const label = 'same';"}])
        self.assertEqual(result['new_text'], self.original)
        self.assertEqual(self.file.read_bytes(), broken.encode())

    def test_fragment_cannot_escape_parent_even_when_whole_file_parses(self):
        snap = self.snapshot()
        heading = self.find(snap, '<h1>등록</h1>')
        escape = '</form>);}\nexport function Hijacked(){return (<form><h1>등록</h1>'
        candidate = self.original.replace('<h1>등록</h1>', escape, 1)
        self.assertFalse(self.service._ast(self.rel, candidate).get('diagnostics'))
        with self.assertRaises(ValueError):
            self.apply(snap, [{'node_id': heading['id'], 'code': escape}])
        self.assertEqual(self.file.read_bytes(), self.original.encode())

    def test_large_file_can_change_small_node_without_regenerating_file(self):
        source = '// ' + 'x' * 40000 + '\n' + self.original
        self.file.write_bytes(source.encode())
        snap = self.snapshot()
        self.assertLess(sum(len(n['source']) for n in snap['nodes']), 12001)
        node = self.find(snap, "const label = 'same';")
        result = self.apply(snap, [{'node_id': node['id'], 'code': "const label = 'large';"}])
        self.assertEqual(result['new_text'], source.replace("const label = 'same';", "const label = 'large';", 1))

    def test_workspace_and_symlink_boundaries(self):
        link = self.file.parent / 'Link.tsx'
        link.symlink_to(self.file)
        for rel in ('../outside.tsx', '/etc/passwd', str(link.relative_to(self.root))):
            with self.assertRaises(ValueError):
                self.editor.snapshot(rel)

    def test_generic_tool_uses_same_transaction_and_rollback(self):
        from autonomy_runtime import Runner
        from ast_editing import editor
        args = SimpleNamespace(task='제목 수정', workspace=str(self.root), check='frontend', max_rounds=0, ponytail='off', llm_url='http://127.0.0.1:8099/v1', model='fixture')
        runner = Runner(args, native.Harness)
        runner.h.evidence_path = self.root / 'test-events.jsonl'
        try:
            snap = runner.apply('inspect_code', {'path': self.rel, 'action': 'edit_ranges'}, {})
            self.assertIn(self.rel, runner.read)
            heading = self.find(snap, '<h1>등록</h1>')
            result = runner.apply('apply_ast_edits', {'path': self.rel, 'snapshot_id': snap['snapshot_id'], 'edits': [{'node_id': heading['id'], 'code': '<h1>수정</h1>'}]}, {})
            self.assertFalse(result.get('error'))
            self.assertIn('<h1>수정</h1>', self.file.read_text())
            self.assertTrue(runner.cp.pending)
            runner.cp.rollback()
            self.assertEqual(self.file.read_bytes(), self.original.encode())
        finally:
            editor(runner.h).service.close()

    def test_default_cannot_bypass_scopes_with_raw_frontend_writes(self):
        from autonomy_runtime import Runner
        args = SimpleNamespace(task='제목 수정', workspace=str(self.root), check='frontend', max_rounds=0, ponytail='off', llm_url='http://127.0.0.1:8099/v1', model='fixture')
        runner = Runner(args, native.Harness)
        runner.h.evidence_path = self.root / 'test-events.jsonl'
        runner.read.add(self.rel)
        for name, payload in [('write_file', {'content': 'export const overwritten=1;'}), ('edit_file', {'old_text': '등록', 'new_text': '삭제'}), ('apply_edits', {'edits': [{'old_text': '<h1>등록</h1>', 'new_text': '<h1>변경</h1>'}]})]:
            for alias in (self.rel, './' + self.rel, 'frontend/src/screens/../screens/Demo.tsx'):
                with self.assertRaisesRegex(ValueError, 'requires inspect_code'):
                    runner.apply(name, {'path': alias, **payload}, {})
        self.assertEqual(self.file.read_bytes(), self.original.encode())
        new_path = 'frontend/src/screens/New.tsx'
        result = runner.apply('write_file', {'path': new_path, 'content': 'export const created=1;'}, {})
        self.assertFalse(result.get('error'))
        self.assertTrue((self.root / new_path).is_file())
        runner.cp.rollback()


if __name__ == '__main__':
    unittest.main()
