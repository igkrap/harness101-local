"""Re-sending the identical model request escalates and then stops instead of looping."""
from pathlib import Path
import json
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
import harness


class IdenticalRequestGuardTests(unittest.TestCase):
    def client(self):
        c = harness.LLMClient.__new__(harness.LLMClient) if hasattr(harness, 'LLMClient') else None
        return c

    def test_escalates_then_stops(self):
        cls = next(v for v in vars(harness).values() if isinstance(v, type) and 'chat' in vars(v))
        c = cls.__new__(cls)
        c.url, c.model = 'http://127.0.0.1:8099/v1', 'm'
        sent = []
        def complete(req, timeout):
            sent.append(json.loads(req.data))
            return {'choices': [{'message': {'content': 'same'}, 'finish_reason': 'stop'}]}
        messages = [{'role': 'user', 'content': 'fix it'}]
        with patch('model_transport.complete', side_effect=complete):
            for _ in range(4):
                c.chat(messages)
            with self.assertRaisesRegex(harness.HarnessError, 'No progress'):
                c.chat(messages)
            c.chat([{'role': 'user', 'content': 'different'}])  # a changed request resets the guard
        self.assertNotIn('IDENTICAL REQUEST', sent[0]['messages'][-1]['content'])
        self.assertIn('IDENTICAL REQUEST', sent[1]['messages'][-1]['content'])
        self.assertGreaterEqual(sent[3]['temperature'], sent[1]['temperature'])
        self.assertGreaterEqual(sent[1]['temperature'], max(0.6, sent[0]['temperature']))


if __name__ == '__main__':
    unittest.main()
