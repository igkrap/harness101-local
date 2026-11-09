"""Focused presentation keeps fitting prefixes and enforces the unchanged hard cap."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
from context_budget import extend_context, focused_signature, measure


class FocusedBudgetTests(unittest.TestCase):
    def runner(self, chars=66000, focused=True):
        class Base:
            def tools(self):
                return self.schema
            def fresh(self, reason=''):
                self.rebuilt += 1
                self.messages = [{'role': 'system', 'content': 'rules'},
                                 {'role': 'user', 'content': 'fallback'}]
            def ask(self, messages, tools):
                self.sent.append(copy.deepcopy(messages))
                return {'message_count': len(messages)}
        runner = extend_context(Base)()
        runner.args = SimpleNamespace(task='Edit NamedItem', context_profile='focused' if focused else 'legacy')
        runner.h = SimpleNamespace(log_event=Mock())
        runner.read = set()
        runner.idle = 3
        runner.rebuilt = 0
        runner.schema, runner.sent = [], []
        runner.messages = [{'role': 'system', 'content': 'rules'}, {'role': 'user', 'content': 'task'},
                           {'role': 'assistant', 'content': 'x' * chars}]
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {'LOCAL_LLM_MAX_TOKENS': '8192'}).start()
        return runner

    def test_fitting_history_is_transmitted_unchanged_without_losing_read_state(self):
        runner = self.runner()
        runner.read = {'frontend/src/NamedItem.tsx'}
        original = copy.deepcopy(runner.messages)
        self.assertGreater(measure(original, reserved=8192)['pressure'], .8)
        self.assertLess(measure(original, reserved=8192)['pressure'], .95)
        with patch('context_budget.compact') as compact:
            runner.fresh('context reset after repeated reads or long history')
            runner.ask(runner.messages, runner.tools())
        compact.assert_not_called()
        self.assertEqual(runner.sent, [original])
        self.assertEqual(runner.messages, original)
        self.assertEqual(runner.read, {'frontend/src/NamedItem.tsx'})
        self.assertEqual(runner.idle, 0)
        self.assertEqual(runner.rebuilt, 0)

    def test_unchanged_soft_pressure_is_not_repacked_on_every_ask(self):
        runner = self.runner(chars=70500)
        pressure = measure(runner.messages, reserved=8192)['pressure']
        self.assertGreater(pressure, .95)
        self.assertLessEqual(pressure, 1)
        original = copy.deepcopy(runner.messages)
        with patch('context_budget.compact', return_value=True) as compact:
            runner.ask(runner.messages, runner.tools())
            runner.ask(runner.messages, runner.tools())
            self.assertEqual(compact.call_count, 1)
            runner.messages.append({'role': 'user', 'content': 'new actual tool feedback'})
            runner.ask(runner.messages, runner.tools())
            self.assertEqual(compact.call_count, 2)
        self.assertEqual(runner.sent[:2], [original, original])
        self.assertEqual(runner.rebuilt, 0)

    def test_signature_and_pressure_recheck_change_with_source_schema_and_reservation(self):
        runner = self.runner(chars=70500)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / 'frontend/src/NamedItem.tsx'
            target.parent.mkdir(parents=True)
            target.write_text('original bytes')
            runner.h.workspace = SimpleNamespace(root=root, safe_path=lambda path: root / path)
            with patch('context_budget.compact', return_value=True) as compact:
                runner.ask(runner.messages, runner.tools())
                runner.ask(runner.messages, runner.tools())
                self.assertEqual(compact.call_count, 1)
                target.write_text('changed source bytes')
                runner.ask(runner.messages, runner.tools())
                self.assertEqual(compact.call_count, 2)
                with patch.dict(os.environ, {'LOCAL_LLM_MAX_TOKENS': '8193'}):
                    runner.ask(runner.messages, runner.tools())
                self.assertEqual(compact.call_count, 3)
                runner.schema.append({'type': 'function', 'function': {'name': 'newTool'}})
                runner.ask(runner.messages, runner.tools())
                self.assertEqual(compact.call_count, 4)
            signature = focused_signature(runner, runner.messages, runner.schema, 8192, 32768)
            self.assertNotEqual(signature, focused_signature(runner, runner.messages, runner.schema, 8192, 32767))

    def test_unshrinkable_hard_overflow_never_reaches_model(self):
        runner = self.runner()
        runner.messages = [{'role': 'system', 'content': 'rules'}, {'role': 'user', 'content': 'task'},
            {'role': 'assistant', 'tool_calls': [{'id': 'large', 'function': {'name': 'inspect_code', 'arguments': '{}'}}]},
            {'role': 'tool', 'tool_call_id': 'large', 'content': 'x' * 100000}]
        runner.current_context = lambda: ('', set())
        with self.assertRaisesRegex(RuntimeError, 'cannot fit context budget'):
            runner.ask(runner.messages, runner.tools())
        self.assertEqual(runner.sent, [])
        self.assertEqual(runner.rebuilt, 0)

    def test_legacy_soft_pressure_still_rebuilds_at_point_eight(self):
        runner = self.runner(focused=False)
        runner.ask(runner.messages, runner.tools())
        self.assertEqual(runner.rebuilt, 1)
        self.assertEqual(runner.sent[0][1]['content'], 'fallback')


if __name__ == '__main__':
    unittest.main()
