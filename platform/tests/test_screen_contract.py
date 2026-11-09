from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-only/harness'))
CASE=Path(__file__).resolve().parents[2]/'local-only/harness/tests/framework_cases/source.cjs'

class ScreenContractTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.screens=self.root/'frontend/src/screens';self.screens.mkdir(parents=True)
 def tearDown(self):self.tmp.cleanup()
 def check(self):
  code='const check=require(process.argv[1]);check({root:process.argv[2],assert:require("node:assert/strict")}).then(()=>console.log("PASS")).catch(e=>{console.error(e.message);process.exitCode=1});'
  return subprocess.run(['node','-e',code,str(CASE),str(self.root)],capture_output=True,text=True,timeout=5)
 def test_missing_meta_fails_with_file_and_actionable_contract(self):
  (self.screens/'Broken.tsx').write_text('export default function Broken(){return null;}')
  r=self.check();self.assertNotEqual(r.returncode,0);self.assertIn('Broken.tsx',r.stderr);self.assertIn('export const meta',r.stderr);self.assertNotIn('Timeout',r.stderr)
 def test_imported_meta_does_not_satisfy_registry(self):
  (self.screens/'Broken.tsx').write_text('import {meta} from "other"; export default function Broken(){return null;}')
  self.assertNotEqual(self.check().returncode,0)
 def test_valid_screen_and_nested_helper_pass(self):
  (self.screens/'Good.tsx').write_text('export const meta={title:"Good"};export default function Good(){return null;}')
  helper=self.screens/'components/Field.tsx';helper.parent.mkdir();helper.write_text('export default function Field(){return null;}')
  self.assertEqual(self.check().returncode,0)
 def test_actual_reference_contains_template_and_existing_post_contract(self):
  from screen_context import screen_reference
  (self.screens/'ItemRegistration.tsx').write_text('export const meta={title:"등록"};export default function Example(){}')
  api=self.root/'backend/src/main/java/example/WorkSiteController.java';api.parent.mkdir(parents=True);api.write_text('@RequestMapping("/api/work-sites") class WorkSiteController{@PostMapping void create(){}}')
  text,paths=screen_reference(self.root,'작업장 등록 화면 추가');self.assertIn('export const meta',text);self.assertIn('/api/work-sites',text);self.assertIn(str(api.relative_to(self.root)),paths);self.assertTrue(all(isinstance(p,str)for p in paths));self.assertLessEqual(len(text),13000)
 def test_browser_root_cause_precedes_timeout_noise_in_feedback(self):
  from test_feedback import feedback
  output='BROWSER_RUNTIME_ERROR: TypeError: missing meta\n'+('locator.waitFor Timeout detail\n'*100)
  report=feedback(self.root,'framework',{'success':False,'stdout':'','stderr':output},0)
  self.assertIn('TypeError: missing meta',report[:200]);self.assertLessEqual(len(report),5000)
