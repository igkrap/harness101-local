import pathlib
import subprocess
import unittest

class FrameworkControlScopeTests(unittest.TestCase):
    @unittest.skip('exercises the retired Inventory example screen (cases control.cjs are NOT_APPLICABLE without Inventory.tsx)')
    def test_duplicate_labels_and_hmr_movement(self):
        script=pathlib.Path(__file__).with_name('framework-control-scope.cjs')
        result=subprocess.run(['node',str(script)],cwd=script.parents[2],capture_output=True,text=True,timeout=45)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('sidebar HMR movement still required',result.stdout)
