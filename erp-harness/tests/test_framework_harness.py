import unittest
from unittest.mock import MagicMock, patch
import subprocess
from pathlib import Path
from harness.harness import Checker, WorkspaceManager, HarnessError

class TestFrameworkHarness(unittest.TestCase):
    def setUp(self):
        # Create a temporary workspace structure
        self.workspace_dir = Path("test_workspace_tmp")
        self.workspace_dir.mkdir(exist_ok=True)
        (self.workspace_dir / "frontend").mkdir(exist_ok=True)
        (self.workspace_dir / "tests").mkdir(exist_ok=True)
        
        self.workspace_manager = WorkspaceManager(str(self.workspace_dir))
        self.checker = Checker(self.workspace_manager)

    def tearDown(self):
        import shutil
        if self.workspace_dir.exists():
            shutil.rmtree(self.workspace_dir)

    @patch("subprocess.run")
    def test_run_check_framework_success(self, mock_run):
        # Mock successful execution of the framework check
        mock_run.return_value = MagicMock(
            returncode=0, 
            stdout="Framework check passed", 
            stderr=""
        )
        
        result = self.checker.run_check("framework")
        
        self.assertTrue(result["success"])
        self.assertEqual(result["stdout"], "Framework check passed")
        
        # Verify the command structure: node <browser_script> <workspace_root>
        args, kwargs = mock_run.call_args
        cmd = args[0]
        self.assertEqual(cmd[0], "node")
        self.assertTrue(cmd[1].endswith("framework_browser.cjs"))
        self.assertEqual(cmd[2], str(self.workspace_dir.resolve()))
        self.assertEqual(kwargs["cwd"], str(self.workspace_dir.resolve()))

    @patch("subprocess.run")
    def test_run_check_framework_failure(self, mock_run):
        # Mock failed execution of the framework check
        mock_run.return_value = MagicMock(
            returncode=7, 
            stdout="", 
            stderr="Framework check failed"
        )
        
        result = self.checker.run_check("framework")
        
        self.assertFalse(result["success"])
        self.assertEqual(result["exit_code"], 7)
        self.assertEqual(result["stderr"], "Framework check failed")

    @patch("subprocess.run")
    def test_run_check_unknown_mode(self, mock_run):
        with self.assertRaises(HarnessError) as cm:
            self.checker.run_check("invalid_mode")
        self.assertIn("Unknown check mode", str(cm.exception))

if __name__ == "__main__":
    unittest.main()
