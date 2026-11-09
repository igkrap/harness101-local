import pathlib
import subprocess
import unittest

class NativeUiRequirementTests(unittest.TestCase):
    def test_real_browser_requires_controls_geometry_and_readonly_query(self):
        script=pathlib.Path(__file__).with_name('native-ui-requirements.cjs')
        result=subprocess.run(['node',str(script)],cwd=script.parents[2],capture_output=True,text=True,timeout=90)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('POST intercepted before server',result.stdout)

if __name__=='__main__':unittest.main()
