import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
from call_budget import snapshot
from context_budget import measure
from source_progress import MAX_RECORDS, remember_accepted
from test_autonomy import native, reply_tool


class SourceProgressTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.runner = SimpleNamespace(
            args=SimpleNamespace(task='Build several related files'), step=0,
            steps=[{'title': 'Build several related files'}], read=set(), messages=[],
            h=SimpleNamespace(workspace=native.WorkspaceManager(self.root), log_event=Mock()))

    def put(self, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def accepted(self, path, content):
        self.put(path, content)
        remember_accepted(self.runner, {path: {'expected': content.encode()}})

    def test_four_committed_sources_survive_repeated_resets_and_static_task_paths(self):
        static = ['backend/src/main/resources/base.sql', 'frontend/src/workspace.json']
        self.runner.args.task = ' '.join(static)
        self.runner.steps[0]['title'] = self.runner.args.task
        for path in static:
            self.put(path, 'static')
        created = [f'backend/src/main/java/sample/Part{i}.java' for i in range(4)]
        for i, path in enumerate(created):
            self.accepted(path, f'class Part{i} {{}}\n')
        for _ in range(3):
            text, paths = snapshot(self.runner)
            self.assertTrue(set(created).issubset(paths))
            self.assertIn('not task completion', text)
            self.runner.read = paths
            self.runner.messages = [{'role': 'user', 'content': text}]

    def test_changed_source_is_current_and_old_check_evidence_is_stale(self):
        path = 'backend/src/Part.java'
        self.accepted(path, 'old bytes')
        self.put(path, 'current bytes')
        text, paths = snapshot(self.runner)
        self.assertIn(path, paths)
        self.assertIn('current bytes', text)
        self.assertNotIn('old bytes', text)
        self.assertIn('CHANGED since checks', text)

    def test_omitted_large_source_does_not_gain_read_authority(self):
        path = 'backend/src/Large.java'
        self.accepted(path, 'x' * 9001)
        text, paths = snapshot(self.runner)
        self.assertIn(path, text)
        self.assertNotIn(path, paths)
        self.assertNotIn('x' * 100, text)
        self.assertIn('omitted files require read_file', text)

    def test_deleted_and_symlinked_sources_are_not_read(self):
        path = 'backend/src/Part.java'
        self.accepted(path, 'source')
        (self.root / path).unlink()
        text, paths = snapshot(self.runner)
        self.assertNotIn(path, paths)
        self.assertIn('old evidence is stale', text)
        other = self.root / 'other'
        other.mkdir()
        (other / 'Part.java').write_text('redirected')
        (self.root / 'backend/src').rmdir()
        (self.root / 'backend/src').symlink_to(other, target_is_directory=True)
        text, paths = snapshot(self.runner)
        self.assertNotIn(path, paths)
        self.assertNotIn('redirected', text)

    def test_context_and_progress_are_bounded_without_partial_sources(self):
        for i in range(MAX_RECORDS + 8):
            self.accepted(f'backend/src/Part{i}.java', f'BEGIN-{i}\n' + 'x' * 1300 + f'\nEND-{i}')
        text, paths = snapshot(self.runner)
        self.assertEqual(len(self.runner._selected_check_progress), MAX_RECORDS)
        self.assertLessEqual(len(text), 10000)
        self.assertIn('older records', text)
        for path in paths:
            self.assertIn((self.root / path).read_text(), text)
        # Conservative fixed prompt/schema overhead plus an 8300-character RAG
        # payload and feedback/contract; source metadata shares the old 10k cap.
        messages = [{'role': 'system', 'content': 's' * (35500 + 8300)},
                    {'role': 'user', 'content': 'f' * 6000 + text}]
        budget = measure(messages, [{'schema': 't' * 7700}], reserved=8192)
        self.assertLessEqual(budget['pressure'], 1)

    def test_compaction_discards_read_authority_for_stale_retained_tool_result(self):
        from recent_context import compact
        path = 'backend/src/Old.java'
        self.put(path, 'new content')
        self.runner.read = {path}
        self.runner.current_context = lambda: ('current anchor', set())
        self.runner.messages = [
            {'role': 'system', 'content': 'rules'},
            {'role': 'user', 'content': 'old anchor'},
            reply_tool('read_file', path=path)['choices'][0]['message'],
            {'role': 'tool', 'tool_call_id': 'tool-read_file', 'content': json.dumps({'content': 'old content'})}]
        self.assertTrue(compact(self.runner, [], 8192, 32768, 'long history'))
        self.assertNotIn(path, self.runner.read)

    def test_legacy_compaction_clears_source_service_cache_for_evicted_file(self):
        from recent_context import compact
        path = 'frontend/src/framework/BusinessWorkspace.tsx'
        self.put(path, 'current source')
        service = SimpleNamespace(read_hashes={path: 'old'}, retain_reads=Mock())
        self.runner.h._code_intelligence = service
        self.runner.read = {path}
        self.runner.current_context = lambda: ('current anchor', set())
        self.runner.messages = [
            {'role': 'system', 'content': 'rules'}, {'role': 'user', 'content': 'old anchor'},
            reply_tool('read_file', path=path)['choices'][0]['message'],
            {'role': 'tool', 'tool_call_id': 'tool-read_file', 'content': json.dumps({'content': 'stale source'})}]
        self.assertTrue(compact(self.runner, [], 8192, 32768, 'long history'))
        self.assertNotIn(path, self.runner.read)
        service.retain_reads.assert_called_once_with(set())

    def test_compaction_retains_complete_current_read_result(self):
        from recent_context import compact
        path = 'backend/src/Current.java'
        self.put(path, 'current content')
        self.runner.read = {path}
        self.runner.current_context = lambda: ('current anchor', set())
        self.runner.messages = [
            {'role': 'system', 'content': 'rules'},
            {'role': 'user', 'content': 'old anchor'},
            reply_tool('read_file', path=path)['choices'][0]['message'],
            {'role': 'tool', 'tool_call_id': 'tool-read_file', 'content': json.dumps({'content': 'current content'})}]
        self.assertTrue(compact(self.runner, [], 8192, 32768, 'long history'))
        self.assertIn(path, self.runner.read)

    def test_runner_commits_survive_completion_reset_and_failed_patch(self):
        from autonomy_runtime import Runner
        root = self.root
        paths = [f'backend/src/main/java/sample/Part{i}.java' for i in range(4)]

        class Gate:
            enabled = True
            def __init__(self, runner): pass
            def prepare(self): pass
            def context(self): return 'Independent completion criteria remain required.'
            def verify(self):
                done = all((root / p).is_file() for p in paths) and (root / paths[0]).read_text() == 'revised'
                return {'success': done, 'results': []}

        args = SimpleNamespace(task='Build related files', workspace=str(root), check='python',
                               max_rounds=7, ponytail='off', llm_url='http://127.0.0.1:8099/v1', model='fixture')
        with patch('completion_runner.Gate', Gate):
            runner = Runner(args, native.Harness)
        runner.h.log_event = Mock()
        sent = []
        script = [reply_tool('write_file', path=paths[0], content='part0'),
                  reply_tool('write_file', path='backend/src/Rejected.java', content='bad')]
        script += [reply_tool('write_file', path=p, content=f'part{i}') for i, p in enumerate(paths[1:], 1)]
        script += [reply_tool('edit_file', path=paths[0], old_text='part0', new_text='revised')]

        def chat(messages, tools=None):
            sent.append(json.loads(json.dumps(messages)))
            return script.pop(0)

        def verify():
            if (root / 'backend/src/Rejected.java').exists():
                runner.last_check_results = {'python': {'success': False}}
                return False, 'deliberate fixture failure'
            return True, 'selected checks passed'

        runner.h.llm.chat = chat
        runner.verify = verify
        self.assertTrue(runner.run())
        self.assertEqual((root / paths[0]).read_text(), 'revised')
        self.assertFalse((root / 'backend/src/Rejected.java').exists())
        self.assertNotIn('backend/src/Rejected.java', runner._selected_check_progress)
        final_context = str(sent[-1])
        self.assertIn('SELECTED-CHECK PATCH PROGRESS', final_context)
        self.assertNotIn('rejected changes were restored', final_context)
        for path in paths:
            self.assertIn('CURRENT FILE ' + path, final_context)


if __name__ == '__main__':
    unittest.main()
