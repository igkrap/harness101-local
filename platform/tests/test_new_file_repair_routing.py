import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import test_autonomy as fixtures
from autonomy_runtime import Runner, rejected_new_file_context


class NewFileRepairRoutingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SupervisorTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.addCleanup(self.fixture.tearDown)
        self.fixture.args.task = 'Implement the requested files and their dependencies'
        self.fixture.args.max_rounds = 2
        self.fixture.args.check = 'frontend|backend'

    def run_rejection(self, sources, failed_mode):
        calls = []
        for path, source in sources.items():
            calls.extend(fixtures.reply_tool('write_file', path=path, content=source)
                         ['choices'][0]['message']['tool_calls'])
        self.fixture.script = [
            {'choices': [{'message': {'role': 'assistant', 'content': None, 'tool_calls': calls}}]},
            fixtures.reply_tool('read_file', path='app.py'),
        ]
        runner = Runner(self.fixture.args, self.fixture.Harness)

        def check(mode):
            failed = mode == failed_mode and any((self.fixture.root / path).exists() for path in sources)
            return {'success': not failed, 'stdout': 'error: missing dependency' if failed else '', 'stderr': ''}

        runner.h.checker.run_check = check
        with patch('autonomy_runtime.repair_new', side_effect=AssertionError('Single-file repair traps dependency creation')) as focused:
            self.assertFalse(runner.run())
            focused.assert_not_called()
        self.assertIsNone(runner.rejected_candidate)
        self.assertFalse(runner.cp.pending)
        for path, source in sources.items():
            self.assertFalse((self.fixture.root / path).exists())
            self.assertIn(source, runner.feedback)
        names = [tool['function']['name'] for tool in self.fixture.schemas[1]]
        self.assertIn('write_file', names)
        self.assertNotIn('repair_new_file', names)
        return runner

    def test_java_schema_failure_can_return_to_normal_migration_tools(self):
        self.run_rejection({'backend/src/main/java/Fixture.java': 'class Fixture {}'}, 'backend')

    def test_multifile_frontend_failure_keeps_sql_and_java_context(self):
        sources = {
            'frontend/src/screens/Fixture.tsx': 'export default function Fixture() { return unresolved; }',
            'backend/src/main/java/Fixture.java': 'class Fixture {}',
            'backend/src/main/resources/db/migration/V6__fixture.sql': 'CREATE TABLE fixture (id bigint);',
        }
        runner = self.run_rejection(sources, 'frontend')
        self.assertIn('V6__fixture.sql', runner.feedback)

    def test_single_frontend_file_with_only_backend_failure_uses_normal_tools(self):
        self.run_rejection({'frontend/src/screens/Fixture.tsx': 'export default function Fixture() { return null; }'}, 'backend')

    def test_whole_files_over_the_old_six_thousand_limit_survive(self):
        sources = {'one.java': 'FIRST\n' + 'x' * 7000 + '\nFIRST_END',
                   'two.sql': 'SECOND\n' + 'y' * 7000 + '\nSECOND_END'}
        records = {path: {'before': None, 'expected': source.encode()} for path, source in sources.items()}
        text = rejected_new_file_context(records)
        for source in sources.values():
            self.assertIn(source, text)
        self.assertLessEqual(len(text), 18000)
        self.assertNotIn('OMITTED', text)

    def test_oversized_file_is_explicitly_omitted_without_truncated_source(self):
        oversized = 'OVERSIZED_BEGIN\n' + 'x' * 20000 + '\nOVERSIZED_END'
        text = rejected_new_file_context({
            'large.java': {'before': None, 'expected': oversized.encode()},
            'small.sql': {'before': None, 'expected': b'SELECT 1;'},
            'existing.ts': {'before': b'old', 'expected': b'EXISTING_CHANGED'},
        })
        self.assertIn('OMITTED REJECTED NEW FILE: large.java', text)
        self.assertNotIn('OVERSIZED_BEGIN', text)
        self.assertNotIn('OVERSIZED_END', text)
        self.assertIn('SELECT 1;', text)
        self.assertNotIn('EXISTING_CHANGED', text)
        self.assertLessEqual(len(text), 18000)

    def test_many_omitted_paths_are_bounded_and_counted(self):
        records = {f'long/{index}/' + 'p' * 200 + '.java': {'before': None, 'expected': b'x' * 20000}
                   for index in range(100)}
        text = rejected_new_file_context(records)
        self.assertIn('additional paths (context budget)', text)
        self.assertLessEqual(len(text), 18000)


class FocusedNewFileRepairTests(unittest.TestCase):
    """Scripted model replies, real Runner/checkpoint writes and real tsc."""

    def setUp(self):
        self.fixture = fixtures.SupervisorTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.addCleanup(self.fixture.tearDown)
        self.fixture.args.task = 'Implement frontend/src/Fixture.ts with a numeric exported count'
        self.fixture.args.check = 'frontend'
        self.fixture.args.context_profile = 'focused'
        self.fixture.args.max_rounds = 2
        self.path = 'frontend/src/Fixture.ts'
        # Longer than the old truncated feedback, but still a small new file.
        self.tail = '\n/* ' + 'model-owned source ' * 350 + ' COMPLETE_SOURCE_END */\n'
        self.bad = 'export const count: number = "wrong";' + self.tail
        self.good = 'export const count: number = 1;' + self.tail
        self.compiler_results = []

    def runner(self):
        runner = Runner(self.fixture.args, self.fixture.Harness)
        target = self.fixture.root / self.path
        compiler = Path(__file__).resolve().parents[2] / 'local-only/frontend/node_modules/.bin/tsc'

        def check(mode):
            if not target.exists():
                return {'success': True, 'stdout': '', 'stderr': '', 'exit_code': 0}
            completed = subprocess.run([str(compiler), '--noEmit', '--skipLibCheck',
                '--target', 'ES2022', str(target)], capture_output=True, text=True, timeout=10)
            result = {'success': completed.returncode == 0, 'stdout': completed.stdout,
                      'stderr': completed.stderr, 'exit_code': completed.returncode}
            self.compiler_results.append(result)
            return result

        runner.h.checker.run_check = check
        return runner

    def test_focused_normal_write_repairs_actual_type_error_and_commits(self):
        self.fixture.script = [fixtures.reply_tool('write_file', path=self.path, content=self.bad),
                               fixtures.reply_tool('write_file', path=self.path, content=self.good)]
        runner = self.runner()
        with patch('autonomy_runtime.repair_new', side_effect=AssertionError('No specialized snippet repair')) as special:
            self.assertTrue(runner.run())
            special.assert_not_called()
        self.assertEqual((self.fixture.root / self.path).read_text(), self.good)
        self.assertFalse(runner.cp.pending)
        self.assertIsNone(runner.rejected_candidate)
        self.assertEqual(runner.used, 2)
        self.assertFalse(self.compiler_results[0]['success'])
        self.assertTrue(self.compiler_results[-1]['success'])
        retry = '\n'.join(message.get('content') or '' for message in self.fixture.messages[1])
        self.assertIn('TS2322', retry)
        self.assertIn(self.bad, retry)
        names = {tool['function']['name'] for tool in self.fixture.schemas[1]}
        self.assertTrue({'read_file', 'write_file', 'search_code'} <= names)
        self.assertNotIn('repair_new_file', names)
        self.assertTrue(any(kind == 'autonomy.rollback' for kind, _ in self.fixture.events))
        self.assertTrue(any(kind == 'autonomy.accepted' for kind, _ in self.fixture.events))

    def test_focused_failed_rewrite_rolls_back_and_retains_latest_whole_source(self):
        second = 'export const count: number = false;' + self.tail
        self.fixture.script = [fixtures.reply_tool('write_file', path=self.path, content=self.bad),
                               fixtures.reply_tool('write_file', path=self.path, content=second)]
        runner = self.runner()
        with patch('autonomy_runtime.repair_new', side_effect=AssertionError('No specialized snippet repair')):
            self.assertFalse(runner.run())
        self.assertFalse((self.fixture.root / self.path).exists())
        self.assertEqual((self.fixture.root / 'app.py').read_text(), 'broken')
        self.assertIsNone(runner.rejected_candidate)
        self.assertFalse(runner.cp.pending)
        self.assertIn(second, runner.rejected_new_context())
        self.assertNotIn(second, runner.feedback, 'Persistent source is not duplicated in feedback')
        self.assertEqual(len(self.compiler_results), 2)
        self.assertTrue(all(not result['success'] for result in self.compiler_results))

    def test_legacy_single_new_file_still_uses_specialized_repair(self):
        from autonomy_runtime import repair_new
        self.fixture.args.context_profile = 'legacy'
        self.fixture.script = [fixtures.reply_tool('write_file', path=self.path, content=self.bad),
            fixtures.reply_text(json.dumps({'edits': [{
                'old_text': 'export const count: number = "wrong";',
                'new_text': 'export const count: number = 1;',
            }]}))]
        runner = self.runner()
        with patch('autonomy_runtime.repair_new', wraps=repair_new) as special:
            self.assertTrue(runner.run())
            special.assert_called_once()
        self.assertEqual((self.fixture.root / self.path).read_text(), self.good)
        self.assertEqual([tool['function']['name'] for tool in self.fixture.schemas[1]], ['repair_new_file'])

    def test_focused_profile_does_not_allow_whole_rewrite_of_existing_frontend(self):
        target = self.fixture.root / self.path
        target.parent.mkdir(parents=True)
        target.write_text(self.good)
        self.fixture.script = [fixtures.reply_tool('read_file', path=self.path),
                               fixtures.reply_tool('write_file', path=self.path, content=self.bad)]
        runner = self.runner()
        self.assertFalse(runner.run())
        self.assertEqual(target.read_text(), self.good)
        self.assertFalse(runner.cp.pending)
        self.assertEqual(len(self.compiler_results), 1, 'Reject before applying or checking the write')
        self.assertTrue(any(kind == 'autonomy.blocked' and data['name'] == 'write_file'
                            and ('TOOL_INPUT_INVALID write_file' in data['error']
                                 or 'Existing frontend source requires' in data['error'])
                            for kind, data in self.fixture.events))

    def test_failed_new_read_then_tool_error_keeps_draft_and_normal_write_commits(self):
        self.fixture.args.max_rounds = 4
        self.fixture.script = [fixtures.reply_tool('write_file', path=self.path, content=self.bad),
            fixtures.reply_tool('read_file', path=self.path),
            fixtures.reply_tool('read_file', path='frontend/src/NoSuchFile.ts'),
            fixtures.reply_tool('write_file', path=self.path, content=self.good)]
        runner = self.runner()
        self.assertTrue(runner.run())
        result = next(data['result'] for kind, data in self.fixture.events
                      if kind == 'tool_call' and data['name'] == 'read_file' and data['args']['path'] == self.path)
        self.assertEqual(result['status'], 'rejected_candidate')
        self.assertIs(result['exists'], False)
        self.assertEqual(result['content'], self.bad)
        self.assertIn('TS2322', result['diagnostic'])
        self.assertNotIn('error', result)
        # Tool serialization must preserve the entire >6000-character draft.
        draft_tool = next(json.loads(message['content']) for message in self.fixture.messages[2]
                          if message.get('role') == 'tool' and 'rejected_candidate' in message.get('content', ''))
        self.assertEqual(draft_tool['content'], self.bad)
        retry = '\n'.join(message.get('content') or '' for message in self.fixture.messages[3])
        self.assertEqual(retry.count(self.bad), 1)
        self.assertIn('TS2322', retry)
        self.assertNotIn(self.path, runner.read, 'Draft reads grant no existing-file edit permission')
        self.assertEqual((self.fixture.root / self.path).read_text(), self.good)
        self.assertEqual(runner.rejected_new_context(), '')
        self.assertFalse(runner.cp.pending)
        self.assertEqual([r['success'] for r in self.compiler_results], [False, True, True])

    def test_compaction_keeps_one_draft_after_feedback_replacement(self):
        from recent_context import compact
        self.fixture.args.max_rounds = 1
        self.fixture.script = [fixtures.reply_tool('write_file', path=self.path, content=self.bad)]
        runner = self.runner()
        self.assertFalse(runner.run())
        runner.feedback = 'An unrelated tool argument was invalid'
        runner.fresh('tool error')
        read = fixtures.reply_tool('read_file', path=self.path)['choices'][0]['message']
        runner.messages.append(read)
        self.assertEqual(runner.batch(read)[1], '')
        for _ in range(2):
            self.assertTrue(compact(runner, runner.tools(), reserved=4096, capacity=32768, reason='test'))
            contents = [message.get('content') or '' for message in runner.messages]
            anchor = json.loads(runner.messages[1]['content'])
            self.assertEqual(anchor['rejected_new_files'].count(self.bad), 1)
            self.assertIn('TS2322', anchor['rejected_new_files'])
            self.assertNotIn('content', json.loads(runner.messages[-1]['content']))
            self.assertNotIn(self.path, runner.read)

    def test_draft_read_never_authorizes_newly_appeared_real_file(self):
        from source_progress import retained_read_paths
        runner = self.runner()
        runner.rejected_new_files.replace({self.path: {'before': None, 'expected': self.bad.encode()}}, 'error TS2322')
        call = fixtures.reply_tool('read_file', path=self.path)['choices'][0]['message']
        runner.messages.append(call)
        self.assertEqual(runner.batch(call)[1], '')
        self.assertNotIn(self.path, runner.read)
        target = self.fixture.root / self.path
        target.parent.mkdir(parents=True)
        target.write_text(self.bad)
        self.assertNotIn(self.path, retained_read_paths(runner, runner.messages))
        with self.assertRaisesRegex(ValueError, 'Read existing file first'):
            runner.apply('write_file', {'path': self.path, 'content': self.good}, {})
        self.assertEqual(target.read_text(), self.bad)
        target.write_text(self.good)
        result = runner.apply('read_file', {'path': self.path}, {})
        self.assertEqual(result['content'], self.good)
        self.assertNotEqual(result.get('status'), 'rejected_candidate')
        self.assertIn(self.path, runner.read)
        target.unlink()
        self.assertEqual(runner.rejected_new_context(), '')
        with self.assertRaises(ValueError):
            runner.apply('read_file', {'path': self.path}, {})


class RejectedNewRetentionTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from rejected_new_files import RejectedNewFiles
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.drafts = RejectedNewFiles(fixtures.native.WorkspaceManager(self.root))

    def test_latest_failed_snapshot_replaces_old_paths_and_ignores_existing_files(self):
        self.drafts.replace({'old.ts': {'before': None, 'expected': b'OLD_DRAFT'}}, 'old failure')
        self.drafts.replace({'new.ts': {'before': None, 'expected': b'NEW_DRAFT'},
                             'existing.ts': {'before': b'old', 'expected': b'EXISTING_EDIT'}}, 'new failure')
        self.assertIsNone(self.drafts.read('old.ts'))
        self.assertIsNone(self.drafts.read('existing.ts'))
        text = self.drafts.context()
        self.assertIn('NEW_DRAFT', text)
        self.assertNotIn('OLD_DRAFT', text)
        self.assertNotIn('EXISTING_EDIT', text)
        self.assertNotIn('old failure', text)
        self.drafts.replace({'existing.ts': {'before': b'old', 'expected': b'changed'}}, 'existing failure')
        self.assertEqual(self.drafts.context(), '')

    def test_whole_source_budget_and_many_omissions_are_bounded(self):
        from rejected_new_files import MAX_SOURCE_CHARS, MAX_METADATA_CHARS, MAX_DIAGNOSTIC_CHARS
        sources = {'a.ts': 'FIRST_BEGIN' + 'a' * 8980 + 'FIRST_END',
                   'b.ts': 'SECOND_BEGIN' + 'b' * 8978 + 'SECOND_END',
                   'c.ts': 'THIRD_BEGIN' + 'c' * 18000 + 'THIRD_END'}
        records = {path: {'before': None, 'expected': source.encode()} for path, source in sources.items()}
        records.update({f'long/{index}/' + 'p' * 200 + '.ts': {'before': None, 'expected': b'x' * 20000}
                        for index in range(100)})
        self.drafts.replace(records, 'actual failure ' * 1000)
        text = self.drafts.context()
        self.assertIn(sources['a.ts'], text)
        self.assertIn(sources['b.ts'], text)
        self.assertNotIn('THIRD_BEGIN', text)
        self.assertIn('OMITTED REJECTED NEW FILE: c.ts', text)
        self.assertIn('additional paths (metadata budget)', text)
        self.assertLessEqual(sum(len(record['source'] or '') for record in self.drafts.files.values()), MAX_SOURCE_CHARS)
        self.assertLessEqual(len(text), MAX_SOURCE_CHARS + MAX_METADATA_CHARS + MAX_DIAGNOSTIC_CHARS + 600)
        omitted = self.drafts.read('c.ts')
        self.assertIs(omitted['exists'], False)
        self.assertTrue(omitted['source_omitted'])
        self.assertIsNone(omitted['content'])

    def test_real_file_seen_by_context_expires_draft_permanently(self):
        self.drafts.replace({'new.ts': {'before': None, 'expected': b'FAILED'}}, 'failure')
        target = self.root / 'new.ts'
        target.write_text('REAL')
        self.assertEqual(self.drafts.context(), '')
        target.unlink()
        self.assertIsNone(self.drafts.read('new.ts'))

    def test_legacy_does_not_supply_virtual_missing_file_reads(self):
        fixture = fixtures.SupervisorTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.addCleanup(fixture.tearDown)
        runner = Runner(fixture.args, fixture.Harness)
        runner.rejected_new_files.replace({'missing.py': {'before': None, 'expected': b'failed'}}, 'failure')
        self.assertEqual(runner.rejected_new_context(), '')
        with self.assertRaises(ValueError):
            runner.apply('read_file', {'path': 'missing.py'}, {})


if __name__ == '__main__':
    unittest.main()
