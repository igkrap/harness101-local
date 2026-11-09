import unittest
import os
import sys
import tempfile
import shutil
from pathlib import Path

# Import the harness
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from harness.harness import Harness, LocalLLMClient, WorkspaceManager, Checker, HarnessError

class BrokenApp:
    def add(self, a, b):
        return a + b

class TestBrokenApp(unittest.TestCase):
    def test_add(self):
        app = BrokenApp()
        self.assertEqual(app.add(1, 2), 3)

class TestSelfDemo(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.workspace = Path(self.test_dir)
        self.workspace.mkdir(exist_ok=True)
        (self.workspace / "tests").mkdir(exist_ok=True)
        
        # Create the broken app
        self.app_file = self.workspace / "app.py"
        self.app_file.write_text("class BrokenApp:\n    def add(self, a, b):\n        return a - b\n")
        
        # Create the test
        self.test_file = self.workspace / "tests" / "test_app.py"
        self.test_file.write_text(
            "import unittest\n"
            "from app import BrokenApp\n"
            "class TestApp(unittest.TestCase):\n"
            "    def test_add(self):\n"
            "        self.assertEqual(BrokenApp().add(1, 2), 3)\n"
        )

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_harness_repair_loop(self):
        # This test is meant to be run by the harness itself
        # It simulates the harness running against the broken app
        pass

if __name__ == "__main__":
    unittest.main()
