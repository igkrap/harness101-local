import pathlib
import subprocess
import unittest
class FrameworkRegistrationFlowTests(unittest.TestCase):
    @unittest.skip('exercises the retired Inventory example screen (cases registration.cjs are NOT_APPLICABLE without Inventory.tsx)')
    def test_creation_payload_grid_refresh_and_no_real_writes(self):
        script=pathlib.Path(__file__).with_name('framework-registration-flow.cjs')
        result=subprocess.run(['node',str(script)],cwd=script.parents[2],capture_output=True,text=True,timeout=90)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('no real writes or draft mutation',result.stdout)
