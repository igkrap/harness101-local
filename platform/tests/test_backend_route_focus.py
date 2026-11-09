"""Runner integration of verified literal route ownership without changing explicit targets."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
from task_sources import resolve_runner_sources, resolve_task_sources
from call_budget import snapshot
from context_budget import focused_signature, measure
from recent_context import compact
from test_autonomy import native, reply_tool


class BackendRouteFocusTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.path = 'backend/src/main/java/example/AnyEndpoint.java'
        self.source = b'package example; class AnyEndpoint { void query() {} }'
        self.put(self.path, self.source)
        self.runner = SimpleNamespace(args=SimpleNamespace(task='POST /api/catalog\ub294 \ucd94\uac00\ud574\uc918', context_profile='focused'),
            modes=['backend'], read=set(), messages=[], steps=[], step=0,
            h=SimpleNamespace(workspace=native.WorkspaceManager(self.root), log_event=Mock()))
        self.owner = {'source': self.path, 'sha256': hashlib.sha256(self.source).hexdigest(),
                      'class_name': 'example.AnyEndpoint', 'matched_routes': ['/api/catalog'], 'match_kind': 'class-base'}
        self.route_owners = Mock(return_value=[self.owner])
        patcher = patch.dict(sys.modules, {'spring_route_sources': SimpleNamespace(route_owners=self.route_owners)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def put(self, path, source):
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(source)
        return file

    def test_unique_existing_collection_route_can_be_targeted_for_a_new_http_method(self):
        self.assertEqual(resolve_task_sources(self.root, self.runner.args.task), [])
        self.assertEqual(resolve_runner_sources(self.runner), [self.path])
        self.route_owners.assert_called_once_with(self.root, '/api/catalog')
        self.assertEqual(self.runner.read, set(), 'Route facts alone must not authorize source edits')

    def test_explicit_filename_keeps_priority_and_skips_route_inference(self):
        self.runner.args.task = 'AnyEndpoint \uc218\uc815\ud574\uc918 POST /api/catalog'
        self.assertEqual(resolve_runner_sources(self.runner), [self.path])
        self.route_owners.assert_not_called()

    def test_unresolved_or_ambiguous_explicit_file_mentions_do_not_fall_back_to_a_route(self):
        self.put('backend/src/main/java/other/AnyEndpoint.java', b'class AnyEndpoint {}')
        for task in ('MissingEndpoint.java \ucd94\uac00 POST /api/catalog',
                     'backend/src/main/java/example/MissingEndpoint.java \uc218\uc815 POST /api/catalog',
                     'AnyEndpoint.java \uc218\uc815 POST /api/catalog',
                     'AnyEndpoint \uc218\uc815 POST /api/catalog'):
            with self.subTest(task=task):
                self.runner.args.task = task
                self.assertEqual(resolve_task_sources(self.root, task), [])
                self.assertEqual(resolve_runner_sources(self.runner), [])
        self.route_owners.assert_not_called()

    def test_frontend_mixed_legacy_and_other_modes_remain_unchanged(self):
        for profile, modes in [('legacy', ['backend']), ('focused', ['frontend']),
                               ('focused', ['frontend', 'backend']), ('focused', ['backend', 'python'])]:
            with self.subTest(profile=profile, modes=modes):
                self.runner.args.context_profile = profile
                self.runner.modes = modes
                self.assertEqual(resolve_runner_sources(self.runner), [])
        self.route_owners.assert_not_called()

    def test_absolute_external_urls_multiple_paths_and_path_traversal_do_not_promote(self):
        for task in ('POST https://example.com/api/catalog', 'POST //example.com/api/catalog',
                     'POST /api/catalog GET /api/other', 'POST /api/../catalog'):
            with self.subTest(task=task):
                self.runner.args.task = task
                self.assertEqual(resolve_runner_sources(self.runner), [])
        self.route_owners.assert_not_called()

    def test_duplicate_relative_path_queries_are_one_literal_route(self):
        self.runner.args.task = 'POST /api/catalog GET /api/catalog?code=x&name=y'
        self.assertEqual(resolve_runner_sources(self.runner), [self.path])
        self.route_owners.assert_called_once_with(self.root, '/api/catalog')

    def test_unresolved_ambiguous_stale_and_unsafe_owner_facts_do_not_promote(self):
        other = {**self.owner, 'class_name': 'example.OtherEndpoint'}
        cases = [[], [self.owner, other], [{**self.owner, 'sha256': '0' * 64}],
                 [{**self.owner, 'source': '../outside.java'}],
                 [{**self.owner, 'source': 'backend/src/main/java/../AnyEndpoint.java'}],
                 [{**self.owner, 'matched_routes': '/api/catalog'}],
                 [{**self.owner, 'matched_routes': ['/api/catalog/child']}]]
        for owners in cases:
            with self.subTest(owners=owners):
                self.route_owners.return_value = owners
                self.assertEqual(resolve_runner_sources(self.runner), [])
        alias = self.root / 'backend/src/main/java/example/Alias.java'
        alias.symlink_to(self.root / self.path)
        self.route_owners.return_value = [{**self.owner, 'source': str(alias.relative_to(self.root))}]
        self.assertEqual(resolve_runner_sources(self.runner), [])

    def test_snapshot_prefers_target_and_only_whole_bytes_supply_read_authority(self):
        references = ['backend/src/main/java/example/ReferenceA.java', 'backend/src/main/java/example/ReferenceB.java']
        for path in references:
            self.put(path, b'x' * 6500)
        self.runner.messages = [reply_tool('read_file', path=path)['choices'][0]['message'] for path in references]
        text, paths = snapshot(self.runner)
        self.assertIn('CURRENT FILE ' + self.path, text)
        self.assertIn(self.source.decode(), text)
        self.assertIn(self.path, paths)
        large = b'package example; class AnyEndpoint {} /*' + b'x' * 9001 + b'*/'
        self.put(self.path, large)
        self.owner['sha256'] = hashlib.sha256(large).hexdigest()
        text, paths = snapshot(self.runner)
        self.assertNotIn(self.path, paths)
        self.assertNotIn(large.decode(), text)

    def test_signature_and_pressure_compaction_share_the_current_route_target(self):
        before = focused_signature(self.runner, [], [], 8192, 32768)
        self.put(self.path, self.source + b'\n// changed')
        self.owner['sha256'] = hashlib.sha256((self.root / self.path).read_bytes()).hexdigest()
        after = focused_signature(self.runner, [], [], 8192, 32768)
        self.assertNotEqual(before, after)
        self.runner.current_context = lambda: snapshot(self.runner)
        self.runner.baseline_feedback = self.runner.feedback = ''
        self.runner.messages = [{'role': 'system', 'content': 'rules'}, {'role': 'user', 'content': 'old context ' * 6000},
            reply_tool('read_file', path=self.path)['choices'][0]['message'],
            {'role': 'tool', 'tool_call_id': 'tool-read_file', 'content': json.dumps({'summary': 'not a whole source'})}]
        before = measure(self.runner.messages, [], reserved=8192)
        self.assertTrue(compact(self.runner, [], 8192, 32768, 'context budget threshold'))
        self.assertIn(self.path, self.runner.read)
        self.assertIn((self.root / self.path).read_text(), json.loads(self.runner.messages[1]['content'])['current_source'])
        self.assertLess(measure(self.runner.messages, [], reserved=8192)['estimated_input_tokens'], before['estimated_input_tokens'])

    def test_native_backend_runner_fresh_grants_only_fully_supplied_source_without_frontend_service(self):
        from autonomy_runtime import Runner
        gate = SimpleNamespace(enabled=False, prepare=lambda: None, context=lambda: 'Frozen API checks remain required')
        args = SimpleNamespace(task=self.runner.args.task, context_profile='focused', workspace=str(self.root),
                               check='backend', max_rounds=1, ponytail='off',
                               llm_url='http://127.0.0.1:1/v1', model='fixture')
        with patch('completion_runner.Gate', return_value=gate):
            runner = Runner(args, native.Harness)
        runner.h.log_event = Mock()
        runner.h.llm.chat = Mock(side_effect=AssertionError('No real model calls in fixture proof'))
        runner.steps = [{'title': args.task, 'kind': 'change'}]
        runner.fresh()
        self.assertIn(self.path, runner.read)
        self.assertIn('CURRENT FILE ' + self.path, runner.messages[1]['content'])
        self.assertIn(self.source.decode(), runner.messages[1]['content'])
        self.assertFalse(hasattr(runner.h, '_code_intelligence'))
        self.assertFalse(runner.cp.pending)
        runner.h.llm.chat.assert_not_called()
        large = self.source + b'/*' + b'x' * 9001 + b'*/'
        self.put(self.path, large)
        self.owner['sha256'] = hashlib.sha256(large).hexdigest()
        runner.fresh()
        self.assertNotIn(self.path, runner.read)
        self.assertNotIn(large.decode(), runner.messages[1]['content'])


if __name__ == '__main__':
    unittest.main()
