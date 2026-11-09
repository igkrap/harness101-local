import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
from harness.harness import Harness, WorkspaceManager, Checker, LocalLLMClient

class MockArgs:
    def __init__(self, task, workspace, check, max_rounds=5, llm_url="http://127.0.0.1:8099/v1", model="test-model", ponytail="full"):
        self.task = task
        self.workspace = workspace
        self.check = check
        self.max_rounds = max_rounds
        self.llm_url = llm_url
        self.model = model
        self.ponytail = ponytail

class TestFinishTool(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path("test_workspace_finish")
        self.test_dir.mkdir(exist_ok=True)
        (self.test_dir / "tests").mkdir(exist_ok=True)
        (self.test_dir / "app.py").write_text("def ok(): pass")
        (self.test_dir / "tests" / "test_app.py").write_text(
            "import unittest\nfrom app import ok\n"
            "class TestApp(unittest.TestCase):\n    def test_ok(self):\n"
            "        self.assertTrue(ok() is None)\n"
        )
        
        self.args = MockArgs(
            task="Finish task",
            workspace=str(self.test_dir),
            check="python"
        )
        # Mock LLM to avoid network
        self.args.llm_url = "http://127.0.0.1:8099/v1"
        self.args.model = "test-model"

    def tearDown(self):
        import shutil
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    @patch("harness.harness.LocalLLMClient.chat")
    def test_finish_rejected_then_accepted(self, mock_chat):
        harness = Harness(self.args)
        harness.llm = MagicMock()

        harness.checker = MagicMock()
        harness.checker.run_check.side_effect = [
            {"success": False, "stdout": "", "stderr": ""}, # Round 1 start
            {"success": False, "stdout": "", "stderr": ""}, # Round 1 finish tool (rejected)
            {"success": True, "stdout": "", "stderr": ""},  # Round 2 start (normal check)
            {"success": True, "stdout": "", "stderr": ""}   # Round 2 finish tool (accepted)
        ]

        resp1 = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{"function": {"name": "finish", "arguments": '{"reason": "first"}'}, "id": "call_1"}]
                }
            }]
        }
        resp2 = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{"function": {"name": "finish", "arguments": '{"reason": "second"}'}, "id": "call_2"}]
                }
            }]
        }

        self.call_count = 0
        def chat_side_effect(messages, tools=None):
            self.call_count += 1
            if self.call_count == 1: return resp1
            if self.call_count == 2: return resp2
            raise Exception("Too many LLM calls")

        harness.llm.chat.side_effect = chat_side_effect

        success = harness.run()

        self.assertTrue(success)
        self.assertEqual(self.call_count, 2)

if __name__ == "__main__":
    unittest.main()
