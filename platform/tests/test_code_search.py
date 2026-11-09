import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
import code_search


class CodeSearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.root = self.home / 'project'
        for scope in ('frontend', 'backend'):
            (self.root / scope / 'src').mkdir(parents=True)
        binary = self.home / '.local/share/mlx-server/search/node_modules/.bin/zg'
        binary.parent.mkdir(parents=True)
        binary.touch()
        self.home_patch = patch.object(Path, 'home', return_value=self.home)
        self.home_patch.start()
        self.addCleanup(self.home_patch.stop)

    def result(self, code=0, out='hits', error=''):
        return subprocess.CompletedProcess([], code, out, error)

    def test_exact_uses_literal_query_and_fixed_scope(self):
        query = '$(touch /tmp/search-injection); --help'
        with patch.object(code_search.subprocess, 'run', return_value=self.result()) as run:
            result = code_search.search_code(self.root, {'query': query, 'scope': 'frontend'})
        self.assertTrue(result['success'])
        argv = run.call_args.args[0]
        self.assertEqual(argv[1:], ['query', '--rg', '-n', '-F', '-m', '5', '-e', query, 'frontend/src'])
        self.assertFalse(run.call_args.kwargs.get('shell', False))

    def test_invalid_input_never_executes(self):
        with patch.object(code_search.subprocess, 'run') as run:
            for args in ({'query': ''}, {'query': 'x' * 301}, {'query': []}, {'query': 'x', 'mode': 'shell'}, {'query': 'x', 'scope': '../'}):
                self.assertFalse(code_search.search_code(self.root, args)['success'])
            self.assertEqual(run.call_count, 0)

    def test_no_matches_and_result_bound(self):
        with patch.object(code_search.subprocess, 'run', return_value=self.result(1, '')):
            self.assertTrue(code_search.search_code(self.root, {'query': 'absent'})['success'])
        with patch.object(code_search.subprocess, 'run', return_value=self.result(out='x' * 10000)):
            result = code_search.search_code(self.root, {'query': 'x'})
        self.assertTrue(result['truncated'])
        self.assertLessEqual(len(result['content']), 6000)

    def test_index_refresh_precedes_hybrid_with_local_cpu_cache(self):
        with patch.object(code_search.subprocess, 'run', side_effect=[self.result(), self.result(out='controller:32')]) as run:
            result = code_search.search_code(self.root, {'query': '품목 등록', 'mode': 'hybrid', 'scope': 'backend'})
        self.assertTrue(result['success'])
        index, query = [call.args[0] for call in run.call_args_list]
        self.assertEqual(index[1], 'index')
        self.assertIn('local/potion-multilingual-128m', index)
        self.assertEqual(index[index.index('--model-cache') + 1], str(self.home / '.local/share/mlx-server/search/models'))
        self.assertEqual(index[index.index('--device') + 1], 'cpu')
        self.assertIn('backend/src/**', query)
        self.assertNotIn('--allow-remote', index + query)

    def test_failed_refresh_does_not_query_stale_index(self):
        with patch.object(code_search.subprocess, 'run', return_value=self.result(2, error='refresh failed')) as run:
            result = code_search.search_code(self.root, {'query': 'save', 'mode': 'hybrid'})
        self.assertFalse(result['success'])
        self.assertEqual(run.call_count, 1)

    def test_component_scope_searches_descriptors_with_real_local_vectors(self):
        with patch.object(code_search.subprocess, 'run', side_effect=[self.result(), self.result(out='component-hit')]) as run:
            result = code_search.search_code(self.root, {'query': '좌우 목록 상세', 'mode': 'hybrid', 'scope': 'components'})
        self.assertTrue(result['success'])
        index, query = [call.args[0] for call in run.call_args_list]
        self.assertIn('local/potion-multilingual-128m', index)
        self.assertIn('frontend/src/**/*.component.json', query)

    def test_remote_or_invalid_manifest_rejected(self):
        index = self.root / '.zvec-grep'
        index.mkdir()
        with patch.object(code_search.subprocess, 'run') as run:
            for content in ('bad json', json.dumps({'embedding': {'provider': 'remote', 'model': 'other'}})):
                (index / 'manifest.json').write_text(content)
                self.assertFalse(code_search.search_code(self.root, {'query': 'save', 'mode': 'hybrid'})['success'])
            self.assertEqual(run.call_count, 0)

    def test_scope_never_falls_back_to_entire_project(self):
        for scope in ('frontend', 'backend'):
            (self.root / scope / 'src').rmdir()
        with patch.object(code_search.subprocess, 'run') as run:
            self.assertFalse(code_search.search_code(self.root, {'query': 'x'})['success'])
            self.assertEqual(run.call_count, 0)

    def test_source_symlink_is_rejected(self):
        (self.root / 'frontend/src/outside').symlink_to(self.home)
        with patch.object(code_search.subprocess, 'run') as run:
            self.assertFalse(code_search.search_code(self.root, {'query': 'x'})['success'])
            self.assertEqual(run.call_count, 0)

    def test_parent_symlink_cannot_escape(self):
        import shutil
        shutil.rmtree(self.root / 'frontend')
        (self.home / 'outside/src').mkdir(parents=True)
        (self.root / 'frontend').symlink_to(self.home / 'outside')
        with patch.object(code_search.subprocess, 'run') as run:
            self.assertFalse(code_search.search_code(self.root, {'query': 'x', 'scope': 'frontend'})['success'])
            self.assertEqual(run.call_count, 0)

    def test_hybrid_validates_both_indexed_trees(self):
        (self.root / 'backend/src/escape').symlink_to(self.home)
        with patch.object(code_search.subprocess, 'run') as run:
            self.assertFalse(code_search.search_code(self.root, {'query': 'x', 'mode': 'hybrid', 'scope': 'frontend'})['success'])
            self.assertEqual(run.call_count, 0)

    def test_project_with_only_frontend_still_has_source_scope(self):
        (self.root / 'backend/src').rmdir()
        with patch.object(code_search.subprocess, 'run', return_value=self.result()) as run:
            self.assertTrue(code_search.search_code(self.root, {'query': 'x'})['success'])
        self.assertEqual(run.call_args.args[0][-1], 'frontend/src')

    def test_timeout_is_returned_as_tool_error(self):
        with patch.object(code_search.subprocess, 'run', side_effect=subprocess.TimeoutExpired('zg', 30)):
            self.assertFalse(code_search.search_code(self.root, {'query': 'x'})['success'])

    def test_native_dispatch_and_schema_are_available(self):
        import harness
        from types import SimpleNamespace
        native = object.__new__(harness.Harness)
        native.workspace = SimpleNamespace(root=self.root)
        self.assertIn('search_code', [t['function']['name'] for t in native._get_tool_schemas()])
        with patch.object(code_search.subprocess, 'run', return_value=self.result(out='frontend/src/App.tsx:1')):
            result = native._execute_tool('search_code', {'query': 'App'})
        self.assertTrue(result['success'])
