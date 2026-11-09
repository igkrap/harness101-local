import json
from pathlib import Path
from unittest.mock import Mock, patch
import unittest

import test_autonomy as fixtures
from autonomy_runtime import Runner
from context_budget import measure
from recent_context import compact
from source_progress import remember_accepted, sync_read_context


def batch_read(paths, tag):
    calls = []
    for index, path in enumerate(paths):
        call = fixtures.reply_tool('read_file', path=path)['choices'][0]['message']['tool_calls'][0]
        calls.append({**call, 'id': f'{tag}-{index}'})
    return {'choices': [{'message': {'role': 'assistant', 'content': None, 'tool_calls': calls}}]}


def text_content(messages):
    def leaves(value):
        if isinstance(value, dict):
            return '\n'.join(leaves(v) for v in value.values())
        if isinstance(value, list):
            return '\n'.join(leaves(v) for v in value)
        return value if isinstance(value, str) else ''
    parts = []
    for message in messages:
        value = message.get('content') or ''
        try:
            parts.append(leaves(json.loads(value)))
        except ValueError:
            parts.append(value)
    return '\n'.join(parts)


class FocusedSourceOnceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SupervisorTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.addCleanup(self.fixture.tearDown)
        self.fixture.args.context_profile = 'focused'
        self.fixture.args.check = 'frontend'
        self.fixture.args.task = 'Create a new screen NewScreen.tsx using existing common components UNIQUE_TASK'
        self.fixture.args.max_rounds = 4

    def put(self, path, source):
        target = self.fixture.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source)

    def runner(self):
        runner = Runner(self.fixture.args, self.fixture.Harness)
        runner.h.checker.run_check = lambda mode: {'success': True, 'stdout': '', 'stderr': ''}
        return runner

    def test_runner_eight_source_reads_keep_each_body_once_and_stable_tools(self):
        names = ['screens/Home.tsx', 'framework/index.ts', 'framework/BusinessWorkspace.tsx',
                 'framework/QueryPanel.tsx', 'framework/RecordGrid.tsx', 'framework/RecordEditor.tsx',
                 'framework/fields.tsx', 'framework/TabbedPanel.tsx']
        sizes = [361, 2528, 2302, 2556, 1261, 3068, 2866, 3500]
        paths = ['frontend/src/' + name for name in names]
        sources = {}
        for index, (path, size) in enumerate(zip(paths, sizes)):
            prefix = f'export const source{index} = {index};\n/* SOURCE_{index} '
            source = prefix + 'x' * (size - len(prefix) - 3) + ' */'
            self.put(path, source)
            sources[path] = source
        self.fixture.script = [batch_read(paths[:2], 'first'), batch_read(paths[2:6], 'second'),
                               batch_read(paths[6:], 'third'), fixtures.reply_text('continue')]
        runner = self.runner()
        with patch('component_catalog.context_for_task', return_value='RAG PUBLIC CONTRACTS ' + 'r' * 9000), \
                patch('ast_editing.editor', side_effect=AssertionError('Read-only common source is not an AST target')):
            self.assertFalse(runner.run())
        fourth = self.fixture.messages[3]
        contents = text_content(fourth)
        self.assertEqual(contents.count(self.fixture.args.task), 1)
        self.assertNotIn('CURRENT AST EDIT SCOPES', contents)
        for path, source in sources.items():
            self.assertEqual(contents.count(source), int(path in runner.read), path)
        self.assertTrue(set(paths[2:]) <= runner.read)
        compacted = [data for kind, data in self.fixture.events if kind == 'autonomy.compact']
        self.assertEqual(compacted, [], 'History length alone must not rewrite a focused prompt that fits')
        for previous, current in zip(self.fixture.messages, self.fixture.messages[1:]):
            self.assertEqual(current[:len(previous)], previous)
        schemas = [json.dumps(tools, sort_keys=True) for tools in self.fixture.schemas]
        self.assertEqual(len(set(schemas)), 1)
        self.assertEqual(runner.h._code_intelligence.read_hashes.keys(), runner.read)

    def test_evicted_source_reread_returns_full_body_even_after_repeat_read_limit(self):
        path = 'frontend/src/framework/Reference.ts'
        source = 'export const preserved = 17;'
        self.put(path, source)
        runner = self.runner()
        result = runner.apply('read_file', {'path': path}, {})
        self.assertEqual(result['content'], source)
        service = runner.h._code_intelligence
        service.duplicate_reads = 3
        sync_read_context(runner, set())
        self.assertNotIn(path, service.read_hashes)
        self.assertEqual(service.duplicate_reads, 0)
        self.assertNotIn(path, runner.read)
        with patch.object(service, '_ast', side_effect=AssertionError('Evicted source requires a complete read')):
            result = runner.apply('read_file', {'path': path}, {})
        self.assertEqual(result['content'], source)
        self.assertNotIn('unchanged', result)
        self.assertIn(path, runner.read)

    def test_legacy_evicted_source_reread_returns_full_body(self):
        path = 'frontend/src/framework/BusinessWorkspace.tsx'
        source = 'export function BusinessWorkspace() { return null; }'
        self.put(path, source)
        runner = self.runner()
        runner.args.context_profile = 'legacy'
        self.assertEqual(runner.apply('read_file', {'path': path}, {})['content'], source)
        service = runner.h._code_intelligence
        sync_read_context(runner, set())
        self.assertNotIn(path, service.read_hashes)
        with patch.object(service, '_ast', side_effect=AssertionError('A lost source must be returned in full')):
            result = runner.apply('read_file', {'path': path}, {})
        self.assertEqual(result['content'], source)
        self.assertNotIn('unchanged', result)

    def test_crlf_full_source_and_read_hash_match_actual_bytes(self):
        import hashlib
        path = 'frontend/src/Windows.ts'
        raw = b'export const first = 1;\r\nexport const second = 2;\r\n'
        self.put(path, '')
        (self.fixture.root / path).write_bytes(raw)
        runner = self.runner()
        result = runner.apply('read_file', {'path': path}, {})
        self.assertEqual(result['content'].encode('utf-8'), raw)
        self.assertEqual(result['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertIn(path, runner.read)
        sync_read_context(runner, runner.read)
        self.assertEqual(runner.h._code_intelligence.read_hashes[path], result['sha256'])

    def test_unchanged_or_truncated_result_cannot_grant_missing_read_permission(self):
        path = 'frontend/src/Large.ts'
        self.put(path, 'export const value = 1; /*' + 'x' * 14000 + '*/')
        runner = self.runner()
        with patch.object(runner.h, '_execute_tool', return_value={'unchanged': True, 'content': 'outline only'}):
            runner.apply('read_file', {'path': path}, {})
        self.assertNotIn(path, runner.read)
        read = batch_read([path], 'large')['choices'][0]['message']
        runner.messages.append(read)
        self.assertEqual(runner.batch(read)[1], '')
        self.assertIn('summary', json.loads(runner.messages[-1]['content']))
        self.assertNotIn(path, runner.read)
        self.assertNotIn(path, runner.h._code_intelligence.read_hashes)

    def test_explicit_edit_target_keeps_ast_and_legacy_default_is_unchanged(self):
        path = 'frontend/src/App.tsx'
        self.put(path, 'export default function App() { return null; }')
        runner = self.runner()
        runner.args.task = 'Update frontend/src/App.tsx'
        editor = Mock()
        editor.snapshot.return_value = {'snapshot_id': 'real-scope', 'nodes': [{'id': 'n1', 'source': 'return null;'}]}
        with patch('ast_editing.editor', return_value=editor):
            text, paths = runner.current_context()
            editor.snapshot.assert_called_once_with(path)
        self.assertIn('real-scope', text)
        self.assertIn(path, paths)
        runner.args.context_profile = 'legacy'
        runner.args.task = 'Unspecified existing frontend task'
        editor.reset_mock()
        with patch('ast_editing.editor', return_value=editor):
            runner.current_context()
        editor.snapshot.assert_called_once_with(path)

    def test_bare_existing_target_precedes_recent_references_in_snapshot_and_ast(self):
        path = 'frontend/src/screens/NamedItem.tsx'
        source = 'export default function NamedItem() { return <main>target source</main>; }'
        self.put(path, source)
        references = ['frontend/src/framework/ReferenceA.tsx', 'frontend/src/framework/ReferenceB.tsx']
        for reference in references:
            self.put(reference, 'export const reference = 1; /*' + 'x' * 6500 + '*/')
        runner = self.runner()
        runner.args.task = 'NamedItem 화면의 조회만 연결해줘'
        runner.steps = [{'title': runner.args.task, 'kind': 'change'}]
        runner.read = set(references)
        runner.messages = [batch_read(references, 'recent')['choices'][0]['message']]
        editor = Mock()
        editor.snapshot.return_value = {'snapshot_id': 'target-scope', 'nodes': [{'id': 'n1', 'source': '<main/>'}]}
        with patch('ast_editing.editor', return_value=editor):
            text, paths = runner.current_context()
        editor.snapshot.assert_called_once_with(path)
        self.assertIn(source, text)
        self.assertIn(path, paths)
        self.assertIn('target-scope', text)

    def test_compaction_preserves_committed_progress_and_latest_rejected_draft(self):
        paths = ['frontend/src/First.ts', 'frontend/src/Second.ts']
        runner = self.runner()
        for index, path in enumerate(paths):
            source = f'export const value{index} = {index};'
            self.put(path, source)
            remember_accepted(runner, {path: {'expected': source.encode()}})
        runner.steps = [{'title': runner.args.task, 'kind': 'change'}]
        runner.feedback = 'unrelated tool error'
        runner.rejected_new_files.replace({'frontend/src/Failed.ts': {'before': None, 'expected': b'BAD_DRAFT'}}, 'actual TS2322')
        runner.messages = [{'role': 'system', 'content': runner.args.task}, {'role': 'user', 'content': 'old context ' * 2000}]
        read = batch_read(paths, 'retained')['choices'][0]['message']
        runner.messages.append(read)
        runner.batch(read)
        before = measure(runner.messages, runner.tools())['estimated_input_tokens']
        self.assertTrue(compact(runner, runner.tools(), 8192, 32768, 'history limit'))
        self.assertLess(measure(runner.messages, runner.tools())['estimated_input_tokens'], before)
        context = text_content(runner.messages)
        self.assertIn('SELECTED-CHECK PATCH PROGRESS', context)
        self.assertIn('not task completion', context)
        self.assertEqual(context.count('BAD_DRAFT'), 1)
        self.assertIn('actual TS2322', context)
        self.assertNotIn('frontend/src/Failed.ts', runner.read)
        self.assertTrue(set(paths) <= runner.read)

    def test_small_valid_prompt_is_never_expanded_by_compaction(self):
        runner = self.runner()
        runner.messages = [{'role': 'system', 'content': 'task'}, {'role': 'user', 'content': 'short'}]
        read = fixtures.reply_tool('read_file', path='app.py')['choices'][0]['message']
        runner.messages.append(read)
        runner.batch(read)
        original = json.loads(json.dumps(runner.messages))
        runner.current_context = lambda: ('large source anchor ' * 1000, set())
        self.assertTrue(compact(runner, [], 8192, 32768, 'history limit'))
        self.assertEqual(runner.messages, original)

    def test_stable_schema_retains_tools_while_runtime_blocks_repeated_reads(self):
        path = 'frontend/src/Source.ts'
        self.put(path, 'export const value = 1;')
        runner = self.runner()
        original = json.dumps(runner.tools(), sort_keys=True)
        runner.apply('read_file', {'path': path}, {})
        runner.focused = True
        runner.listed = {'frontend/src': ['Source.ts']}
        runner.blocked_tools = {'list_files'}
        runner.h._code_intelligence.duplicate_reads = 3
        self.assertEqual(json.dumps(runner.tools(), sort_keys=True), original)
        with self.assertRaisesRegex(ValueError, 'Repeated unchanged source reads'):
            runner.apply('read_file', {'path': path}, {})
        listing = fixtures.reply_tool('list_files', path='frontend/src')['choices'][0]['message']
        self.assertIn('Tool disabled', runner.batch(listing)[1])


if __name__ == '__main__':
    unittest.main()
