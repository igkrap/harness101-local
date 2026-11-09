import unittest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace
import tempfile
import os
from harness.harness import run_task, WorkspaceManager

class TestRecovery(unittest.TestCase):
    def test_retry_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = WorkspaceManager(tmp)
            file_path = os.path.join(tmp, "demo.py")
            with open(file_path, "w") as f:
                f.write("fresh_bytes")

            # Fake 1: Fail, with history of stale write and failed check
            f1 = SimpleNamespace(run=MagicMock(return_value=False), history=[], workspace=ws)
            f1.history.append({'type': 'tool_call', 'data': {'name': 'write_file', 'args': {'path': 'demo.py', 'content': 'stale'}, 'result': {'status': 'ok'}}})
            f1.history.append({'type': 'check', 'data': {'mode': 'python', 'result': {'success': False, 'stdout': 'LATEST', 'stderr': 'FAILURE'}}})
            
            # Fake 2: Success
            f2 = SimpleNamespace(run=MagicMock(return_value=True), history=[], workspace=ws)

            with patch('harness.harness.Harness', side_effect=[f1, f2]) as mock_harness:
                args = SimpleNamespace(
                    task="original-goal", workspace=tmp, check="python", 
                    max_rounds=10, llm_url="127.0.0.1:8099/v1", model="local", ponytail="full"
                )
                res = run_task(args)
                
                self.assertTrue(res)
                # Verify second harness (the recovery attempt) received the recovery data from f1's history
                second_call_args = mock_harness.call_args_list[1][0][0]
                self.assertIn("original-goal", str(second_call_args))
                self.assertIn("fresh_bytes", str(second_call_args))
                self.assertIn("LATEST", str(second_call_args))

    def test_retry_exhaustion(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = WorkspaceManager(tmp)
            f_fail = SimpleNamespace(run=MagicMock(return_value=False), history=[], workspace=ws)
            
            # Total10 with chunk8 means at most 2 attempts (8+2=10)
            with patch('harness.harness.Harness', side_effect=[f_fail, f_fail]) as mock_harness:
                args = SimpleNamespace(
                    task="fail", workspace=tmp, check="python", 
                    max_rounds=10, llm_url="127.0.0.1:8099/v1", model="local", ponytail="full"
                )
                res = run_task(args)
                self.assertFalse(res)
                self.assertLessEqual(mock_harness.call_count, 2)

if __name__ == "__main__":
    unittest.main()
