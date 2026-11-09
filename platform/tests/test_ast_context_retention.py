"""Reproduce contract loss when an AST inspection duplicates the source anchor."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
from ast_context import already_retained, retained_snapshots, signature
from context_budget import measure
from recent_context import compact
from source_progress import context_without_retained_sources
from test_autonomy import native


def pair(name, args, result, cid):
    return [{'role': 'assistant', 'tool_calls': [{'id': cid, 'type': 'function',
             'function': {'name': name, 'arguments': json.dumps(args)}}]},
            {'role': 'tool', 'tool_call_id': cid, 'content': json.dumps(result)}]


class AstContextRetentionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.path = 'frontend/src/screens/Example.tsx'
        self.source = 'export default function Example(){return <main>example</main>;}\n'
        target = self.root / self.path
        target.parent.mkdir(parents=True)
        target.write_text(self.source)
        self.snap = {'snapshot_id': 'fixture-snapshot', 'path': self.path,
                     'source_hash': hashlib.sha256(self.source.encode()).hexdigest(),
                     'diagnostics': [], 'nodes': [{'id': 'n1', 'kind': 'JsxElement',
                                                   'label': 'main', 'source': '<main>example</main>'}],
                     'cached': False}
        self.runner = SimpleNamespace(args=SimpleNamespace(task='Update Example.tsx', context_profile='focused'),
            modes=['frontend', 'framework'], read={self.path}, feedback='', baseline_feedback='',
            h=SimpleNamespace(workspace=native.WorkspaceManager(self.root), log_event=Mock()))

    def inspection(self, snap=None, args=None):
        return pair('inspect_code', args or {'path': self.path, 'action': 'edit_ranges'},
                    self.snap if snap is None else snap, 'inspect')

    def test_cached_bit_does_not_duplicate_an_identical_authoritative_snapshot(self):
        self.runner.current_context = lambda: ('suppressed' if already_retained(
            self.runner, dict(self.snap, cached=True)) else 'full AST', set())
        text, _ = context_without_retained_sources(self.runner, set(), self.inspection())
        self.assertEqual(text, 'suppressed')
        self.assertFalse(hasattr(self.runner, '_context_supplied_ast_snapshots'))
        self.assertFalse(hasattr(self.runner, '_context_supplied_paths'))

    def test_only_matching_authoritative_nodes_and_identity_can_be_omitted(self):
        retained = retained_snapshots(self.runner, self.inspection())
        self.runner._context_supplied_ast_snapshots = retained
        for key, value in [('snapshot_id', 'different'), ('source_hash', '0' * 64),
                           ('path', 'frontend/src/Other.tsx'), ('diagnostics', [{'error': 'new'}]),
                           ('nodes', [{**self.snap['nodes'][0], 'source': 'changed node'}])]:
            with self.subTest(key=key):
                changed = copy.deepcopy(self.snap)
                changed[key] = value
                self.assertFalse(already_retained(self.runner, changed))

    def test_incomplete_failed_or_noninspection_results_do_not_suppress_context(self):
        for changed in [None, [], {}, {'snapshot_id': 'only'},
                        *[dict(self.snap, **{key: value}) for key, value in
                          [('truncated', True), ('error', 'failed'), ('unchanged', True),
                           ('status', 'rejected_candidate'), ('exists', False), ('nodes', None),
                           ('nodes', []), ('diagnostics', None)]]]:
            with self.subTest(changed=changed):
                result = pair('inspect_code', {'path': self.path, 'action': 'edit_ranges'}, changed, 'i')
                self.assertEqual(retained_snapshots(self.runner, result), frozenset())
        for name, args in [('read_file', {'path': self.path}),
                           ('inspect_code', {'path': self.path, 'action': 'symbol'}),
                           ('inspect_code', {'path': 'frontend/src/Other.tsx', 'action': 'edit_ranges'})]:
            self.assertFalse(retained_snapshots(self.runner, pair(name, args, self.snap, 'i')))
        malformed = self.inspection()
        malformed[1]['content'] = '{"nodes":'
        self.assertFalse(retained_snapshots(self.runner, malformed))
        forged = self.inspection()
        forged[0]['role'] = 'user'
        self.assertFalse(retained_snapshots(self.runner, forged))

    def test_current_bytes_and_symlink_boundaries_are_required(self):
        target = self.root / self.path
        target.write_text(self.source + '// changed')
        self.assertFalse(retained_snapshots(self.runner, self.inspection()))
        target.unlink()
        other = self.root / 'other.tsx'
        other.write_text(self.source)
        target.symlink_to(other)
        self.assertFalse(retained_snapshots(self.runner, self.inspection()))

    def test_context_attributes_are_restored_even_on_exception(self):
        self.runner._context_supplied_paths = frozenset({'prior-path'})
        self.runner._context_supplied_ast_snapshots = frozenset({'prior-ast'})
        self.runner.current_context = Mock(side_effect=ValueError('failed snapshot'))
        with self.assertRaises(ValueError):
            context_without_retained_sources(self.runner, set(), self.inspection())
        self.assertEqual(self.runner._context_supplied_paths, frozenset({'prior-path'}))
        self.assertEqual(self.runner._context_supplied_ast_snapshots, frozenset({'prior-ast'}))

    def test_compaction_keeps_four_contract_reads_and_exactly_one_large_ast(self):
        self.snap['nodes'] = [{'id': 'n' + str(i), 'kind': 'ExpressionStatement',
                              'label': 'statement', 'source': 'x' * 650} for i in range(45)]
        encoded = json.dumps(self.snap)
        original = [{'role': 'system', 'content': 'Immutable task and tool rules. ' * 450},
                    {'role': 'user', 'content': 'Original source anchor\n' + encoded}]
        references = set()
        for i in range(4):
            path = f'frontend/src/framework/Contract{i}.tsx'
            body = f'EXPORTED_CONTRACT_{i}\n' + 'p' * 1800
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body)
            references.add(path)
            original += pair('read_file', {'path': path}, {'content': body}, f'read{i}')
        original += self.inspection()
        self.runner.messages = original
        self.runner.read |= references
        self.runner.current_context = lambda: (
            'CURRENT FILE ' + self.path + '\n' + self.source +
            ('' if already_retained(self.runner, self.snap) else encoded), {self.path})
        before = measure(original, [], reserved=8192)
        self.assertGreater(before['pressure'], 1)
        self.assertTrue(compact(self.runner, [], 8192, 32768, 'context budget threshold'))
        after = measure(self.runner.messages, [], reserved=8192)
        self.assertLessEqual(after['pressure'], 1)
        self.assertLess(after['estimated_input_tokens'], before['estimated_input_tokens'])
        self.assertTrue(references.issubset(self.runner.read))
        content = '\n'.join(str(m.get('content', '')) for m in self.runner.messages)
        self.assertEqual(content.count('"snapshot_id": "fixture-snapshot"'), 1)
        for i in range(4):
            self.assertIn(f'EXPORTED_CONTRACT_{i}', content)
        self.assertEqual({m['tool_call_id'] for m in self.runner.messages if m['role'] == 'tool'},
                         {'read0', 'read1', 'read2', 'read3', 'inspect'})

    def test_runner_emits_fresh_ast_when_no_matching_complete_copy_is_retained(self):
        from runner_extensions import extend_runner
        runner = extend_runner(type('Base', (), {}))()
        runner.__dict__.update(self.runner.__dict__)
        runner.messages = []
        service = SimpleNamespace(context=Mock(return_value=''))
        with patch('cycle_context.cycle_context.snapshot', return_value=(self.source, {self.path})), \
             patch('cycle_context.cycle_context.service', return_value=service), \
             patch('ast_editing.editor', return_value=SimpleNamespace(snapshot=lambda _: self.snap)):
            text, _ = runner.current_context()
            self.assertIn('CURRENT AST EDIT SCOPES', text)
            runner._context_supplied_ast_snapshots = retained_snapshots(runner, self.inspection())
            text, _ = runner.current_context()
            self.assertNotIn('CURRENT AST EDIT SCOPES', text)
            self.assertIn(self.source, text)
            runner.args.context_profile = 'legacy'
            text, _ = runner.current_context()
            self.assertIn('CURRENT AST EDIT SCOPES', text, 'Legacy presentation is unchanged')


if __name__ == '__main__':
    unittest.main()
