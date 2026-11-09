import unittest
from harness.harness import Harness
import argparse
import tempfile
import shutil
from pathlib import Path

class TestHarnessProgressNudge(unittest.TestCase):
    def setUp(self):
        self.demo_dir = Path(tempfile.mkdtemp())
        (self.demo_dir / "tests").mkdir()
        (self.demo_dir / "app.py").write_text("class BrokenApp:\n    def add(self, a, b):\n        return a - b\n")
        (self.demo_dir / "tests" / "test_app.py").write_text(
            "import unittest\nfrom app import BrokenApp\n"
            "class TestApp(unittest.TestCase):\n    def test_add(self):\n"
            "        self.assertEqual(BrokenApp().add(1, 2), 3)\n"
        )
        
        class MockArgs:
            task = "Fix app.py"
            workspace = str(self.demo_dir)
            check = "python"
            max_rounds = 10
            llm_url = "http://127.0.0.1:8099/v1"
            model = "test-model"
            ponytail = "off"

        self.args = MockArgs()

    def tearDown(self):
        shutil.rmtree(self.demo_dir)

    def test_nudge_after_repeated_reads(self):
        from unittest.mock import MagicMock, patch
        harness = Harness(self.args)
        harness.llm = MagicMock()
        harness.checker = MagicMock()
        harness.checker.run_check.return_value = {"success": False, "stdout": "", "stderr": "error"}

        read_call = {
            'role': 'assistant',
            'content': '',
            'tool_calls': [{
                'id': 'call_1',
                'function': {'name': 'read_file', 'arguments': '{"path": "app.py"}'}
            }]
        }
        # OpenAI format: choices[0].message
        read_response = {'choices': [{'message': read_call}]}

        # Round 1, 2, 3: read_file
        # Round 4: LLM receives nudge and we stop
        harness.llm.chat.side_effect = [
            read_response,
            read_response,
            read_response,
            {'choices': [{'message': {'role': 'assistant', 'content': 'finish'}}]},
        ]

        harness._execute_tool = MagicMock(return_value={"content": "some content"})

        # We need to capture the messages sent to the LLM in the 4th call
        with patch.object(harness, 'args', self.args):
            try:
                harness.run()
            except Exception:
                pass

        # The 4th call to chat should have the nudge in the messages
        args, kwargs = harness.llm.chat.call_args_list[3]
        sent_messages = args[0]

        nudge_msg = "STOP REPEATING ALREADY READ DOCS OR FILES."
        found = any(nudge_msg in m.get('content', '') for m in sent_messages if m.get('role') == 'user')
        self.assertTrue(found, "Nudge message not found in messages sent to LLM after 3 reads")

if __name__ == "__main__":
    unittest.main()
