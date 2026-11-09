import unittest
import os
import sys
import json
import subprocess
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

# Import the harness
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from harness.harness import Harness, LocalLLMClient, WorkspaceManager, Checker, HarnessError

class TestHarness(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.workspace_path = Path(self.test_dir)
        self.workspace_path.mkdir(exist_ok=True)
        (self.workspace_path / "tests").mkdir(exist_ok=True)
        
        # Create a dummy test file
        with open(self.workspace_path / "tests" / "test_dummy.py", "w") as f:
            f.write("import unittest\nclass Test(unittest.TestCase):\n    def test_pass(self):\n        self.assertTrue(True)\n")

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_workspace_traversal(self):
        wm = WorkspaceManager(self.test_dir)
        with self.assertRaises(HarnessError):
            wm.safe_path("../../etc/passwd")

    def test_protected_path(self):
        wm = WorkspaceManager(self.test_dir)
        # Simulate node_modules
        nm_path = Path(self.test_dir) / "node_modules"
        self.assertTrue(wm.is_protected(nm_path))

    def test_non_loopback_rejection(self):
        with self.assertRaises(HarnessError):
            LocalLLMClient("http://google.com/v1", "model")

    def test_python_check_success(self):
        wm = WorkspaceManager(self.test_dir)
        checker = Checker(wm)
        res = checker.run_check("python")
        self.assertTrue(res["success"])

class TestSelfDemo(unittest.TestCase):
    def test_demo_flow(self):
        # This is a placeholder for the actual self-demo logic
        pass

if __name__ == "__main__":
    unittest.main()
