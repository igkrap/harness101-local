import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
from autonomy_runtime import Runner
from candidate_focus import ask_candidate


BaseRunner = next(cls for cls in Runner.__mro__ if cls.__module__ == 'autonomy_runtime')


class LoopFixture(BaseRunner):
    """Exercise the real run/batch loop without services, compilation or inference."""

    def __init__(self, root):
        self.events = []
        workspace = SimpleNamespace(root=root, safe_path=lambda path: root / path,
                                    is_protected=lambda path: False)
        harness = SimpleNamespace(workspace=workspace,
                                  log_event=lambda kind, data: self.events.append((kind, data)),
                                  llm=SimpleNamespace(chat=Mock(return_value={
                                      'choices': [{'message': {'content': 'model reply', 'tool_calls': []}}]})))
        args = SimpleNamespace(task='repair fixture', check='fixture', max_rounds=8)
        super().__init__(args, lambda args: harness)
        self.reply_count = 0
        self.reply = lambda: {'content': 'No executable reply', 'tool_calls': []}
        self.verify_step = lambda: False
        self._failed_ast_candidate = {
            'path': 'frontend/src/Fixture.tsx', 'snapshot_id': 'snapshot',
            'source_hash': 'source-hash', 'edits': [],
        }

    def verify(self):
        return True, 'Fixture baseline'

    def plan(self):
        self.steps = [{'title': 'Fixture', 'kind': 'change'}]

    def fresh(self, reason=''):
        self.messages = [{'role': 'system', 'content': 'fixture'}, {'role': 'user', 'content': 'fixture'}]
        self.idle = 0

    def tools(self):
        return []

    def ask(self, messages, tools):
        self.reply_count += 1
        if self.reply_count > 20:
            raise AssertionError('Guard failed to bound deterministic replies')
        return self.reply()

    def apply(self, name, inputs, before):
        if name in ('fixture_noop', 'finish'):
            return {'status': 'ok'}
        return {'error': 'Unknown fixture tool'}

    def reject_repeat(self, name, inputs, error):
        pass


class RuntimeNoCallGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runner = LoopFixture(self.root)
        self.proposal = copy.deepcopy(self.runner._failed_ast_candidate)
        self.model = Mock(side_effect=AssertionError('Preflight must not call a model'))

    def assert_stopped(self, detail):
        self.assertFalse(self.runner.run())
        self.assertEqual(self.runner.reply_count, 3)
        self.assertEqual(self.runner.used, 0)
        self.assertEqual(self.runner._failed_ast_candidate, self.proposal)
        self.assertIn(detail, self.runner.feedback)
        events = [data for kind, data in self.runner.events if kind == 'autonomy.stalled']
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['reason'], 'no_model_no_executable_reply')
        self.assertEqual(events[0]['consecutive_replies'], 3)
        self.model.assert_not_called()

    def test_real_oversize_candidate_packet_stops_without_model_or_candidate_loss(self):
        catalog = [dict(id=f'n{i}', kind='JsxElement', label='fixture', source='x' * 10000)
                   for i in range(8)]
        snapshot = dict(snapshot_id='snapshot', nodes=catalog)
        self.runner.h._ast_editor = SimpleNamespace(
            allow_nested_handlers=False,
            snapshot=Mock(return_value=snapshot),
            _snapshots={'snapshot': SimpleNamespace(ranges={}, nodes={})})
        self.runner.reply = lambda: ask_candidate(self.runner, self.model)
        self.assert_stopped('Packet too large')
        self.assertFalse(self.runner.cp.pending)

    def test_real_candidate_preask_failure_stops_without_model_or_candidate_loss(self):
        self.runner.h._ast_editor = SimpleNamespace(allow_nested_handlers=False,
            snapshot=Mock(side_effect=ValueError('Snapshot unavailable')))
        self.runner.reply = lambda: ask_candidate(self.runner, self.model)
        self.assert_stopped('Snapshot unavailable')
        self.assertEqual(self.runner.h._ast_editor.snapshot.call_count, 3)
        self.assertFalse(self.runner.cp.pending)

    def test_stop_preserves_pending_checkpoint_and_exact_source(self):
        path = self.root / 'candidate.txt'
        path.write_bytes(b'original')

        def reply():
            if self.runner.reply_count == 3:
                self.runner.cp.stage('candidate.txt')
                path.write_bytes(b'candidate')
                self.runner.cp.record('candidate.txt')
            return {'content': 'Preflight failed', 'tool_calls': []}

        self.runner.reply = reply
        self.assert_stopped('Preflight failed')
        self.assertTrue(self.runner.cp.pending)
        self.assertEqual(path.read_bytes(), b'candidate')
        record = self.runner.cp._records['candidate.txt']
        self.assertEqual(record['before'], b'original')
        self.assertEqual(record['expected'], b'candidate')

    def test_actual_model_call_resets_consecutive_reply_bound(self):
        self.runner.accepted = True

        def reply():
            if self.runner.reply_count == 3:
                return BaseRunner.ask(self.runner, self.runner.messages, [])
            if self.runner.reply_count == 6:
                return {'content': 'finish', 'tool_calls': []}
            return {'content': 'Preflight failed', 'tool_calls': []}

        self.runner.reply = reply
        self.assertTrue(self.runner.run())
        self.assertEqual(self.runner.reply_count, 6)
        self.assertEqual(self.runner.used, 1)
        self.runner.h.llm.chat.assert_called_once()
        self.assertFalse(any(kind == 'autonomy.stalled' for kind, _ in self.runner.events))

    def test_successful_deterministic_tool_resets_bound_without_read_or_file_progress(self):
        self.runner.accepted = True

        def reply():
            if self.runner.reply_count in (3, 6):
                name = 'fixture_noop' if self.runner.reply_count == 3 else 'finish'
                return {'content': '', 'tool_calls': [dict(id='fixture', type='function',
                        function=dict(name=name, arguments=json.dumps({}))) ]}
            return {'content': 'Preflight failed', 'tool_calls': []}

        self.runner.reply = reply
        self.assertTrue(self.runner.run())
        self.assertEqual(self.runner.reply_count, 6)
        self.assertEqual(self.runner.used, 0)
        self.assertFalse(any(kind == 'autonomy.stalled' for kind, _ in self.runner.events))

    def test_invalid_tool_reply_does_not_reset_bound(self):
        self.runner.reply = lambda: {'content': '', 'tool_calls': [dict(id='bad', type='function',
                                    function=dict(name='fixture_noop', arguments='{'))]}
        self.assert_stopped('Tool fixture_noop failed')

    def test_deterministic_verification_steps_are_not_counted_as_stalled_replies(self):
        self.runner.plan = lambda: setattr(self.runner, 'steps', [dict(title='Verify', kind='verify') for _ in range(6)])

        def verify_step():
            self.runner.step += 1
            return True

        self.runner.verify_step = verify_step
        self.assertTrue(self.runner.run())
        self.assertEqual(self.runner.step, 6)
        self.assertEqual(self.runner.reply_count, 0)
        self.assertEqual(self.runner.used, 0)


if __name__ == '__main__':
    unittest.main()
