import unittest
import tempfile
import shutil
from pathlib import Path
from harness.harness import Harness, WorkspaceManager, argparse

class TestToolFeedback(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp()).resolve()
        (self.test_dir / "subdir").mkdir()
        (self.test_dir / "file.txt").write_text("line1\nline2\nline3")
        
        # Mock args for Harness
        class Args:
            workspace = str(self.test_dir)
            llm_url = "http://127.0.0.1:8099/v1"
            model = "dummy"
            ponytail = "off"
            max_rounds = 1
            check = ""
            task = ""
        
        self.args = Args()
        # We need to mock checker and llm to avoid network/heavy lifting
        from unittest.mock import MagicMock
        self.harness = Harness(self.args)
        self.harness.checker = MagicMock()
        self.harness.llm = MagicMock()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_edit_file_stale_recovery(self):
        # 1. Simulate stale edit: old_text is from an old version
        path = "file.txt"
        old_text_stale = "line1\nline2_STALE\nline3"
        new_text = "line1\nline2_FIXED\nline3"
        
        res = self.harness._execute_tool("edit_file", {
            "path": path,
            "old_text": old_text_stale,
            "new_text": new_text
        })
        
        # Should return error and include current_content
        self.assertIn("error", res)
        self.assertIn("old_text not found", res["error"])
        self.assertEqual(res["current_content"], "line1\nline2\nline3")

        # 2. Subsequent correct edit using fresh content
        res_correct = self.harness._execute_tool("edit_file", {
            "path": path,
            "old_text": "line1\nline2\nline3",
            "new_text": "line1\nline2_FIXED\nline3"
        })
        self.assertEqual(res_correct["status"], "ok")
        self.assertEqual((self.test_dir / "file.txt").read_text(), "line1\nline2_FIXED\nline3")

    def test_edit_file_constraints(self):
        # Empty old_text
        res = self.harness._execute_tool("edit_file", {
            "path": "file.txt", "old_text": "", "new_text": "something"
        })
        self.assertIn("error", res)
        self.assertEqual(res["current_content"], "line1\nline2\nline3")

        # old_text == new_text (No-op)
        res = self.harness._execute_tool("edit_file", {
            "path": "file.txt", "old_text": "line1", "new_text": "line1"
        })
        self.assertIn("error", res)
        self.assertEqual(res["current_content"], "line1\nline2\nline3")

        # Multiple matches (Ambiguous)
        (self.test_dir / "multi.txt").write_text("A\nB\nA")
        res = self.harness._execute_tool("edit_file", {
            "path": "multi.txt", "old_text": "A", "new_text": "C"
        })
        self.assertIn("error", res)
        self.assertIn("ambiguous", res["error"])
        self.assertEqual(res["current_content"], "A\nB\nA")

    def test_write_file_identical_reject(self):
        # Write identical content
        res = self.harness._execute_tool("write_file", {
            "path": "file.txt", "content": "line1\nline2\nline3"
        })
        self.assertIn("error", res)
        self.assertIn("already identical", res["error"])

if __name__ == "__main__":
    unittest.main()
