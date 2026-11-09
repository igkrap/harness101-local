import json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-only/harness'))
from test_autonomy import native
from lint_frontend import run_lint
from frontend_checks import run_frontend

class LintTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);(self.root/'frontend/src').mkdir(parents=True);self.file=self.root/'frontend/src/App.tsx';self.checker=native.Checker(native.WorkspaceManager(self.root))
 def tearDown(self):self.tmp.cleanup()
 def test_actual_lint_accepts_valid_code(self):
  self.file.write_text('export default function App(){return null;}\n');r=run_lint(self.checker);self.assertTrue(r['success'],r);self.assertEqual(r['lint']['files'],1);self.assertEqual(r['lint']['errors'],0)
 def test_actual_lint_reports_unused_with_location_and_rule(self):
  self.file.write_text('const unused = 1;\nexport default function App(){return null;}\n');r=run_lint(self.checker);self.assertFalse(r['success']);self.assertIn('@typescript-eslint/no-unused-vars',r['stdout']);self.assertIn('frontend/src/App.tsx:1:',r['stdout'])
 def test_actual_lint_detects_conditional_hooks(self):
  self.file.write_text('import {useState} from "react";\nexport default function App(){if(Math.random()>0.5)useState(0);return null;}\n');r=run_lint(self.checker);self.assertFalse(r['success']);self.assertIn('react-hooks/rules-of-hooks',r['stdout'])
 def test_failed_lint_still_reports_type_failure_without_build(self):
  compiler={'success':False,'exit_code':2,'stdout':'src/App.tsx(1,1): error TS2305: Module has no exported member Ghost.','stderr':'compiler detail'}
  checker=SimpleNamespace(workspace=SimpleNamespace(root=self.root),_exec=Mock(return_value=compiler))
  failure={'success':False,'exit_code':1,'stdout':'specific lint error','stderr':'','lint':{'errors':1}}
  with patch('lint_frontend.run_lint',return_value=failure):result=run_frontend(checker)
  self.assertFalse(result['success']);self.assertNotEqual(result['exit_code'],0)
  self.assertIn('specific lint error',result['stdout']);self.assertIn('error TS2305',result['stdout'])
  self.assertIn('compiler detail',result['stderr']);self.assertEqual(result['lint'],failure['lint'])
  checker._exec.assert_called_once_with(['npx','tsc','--noEmit'],cwd=str(self.root/'frontend'))
 def test_failed_lint_cannot_be_hidden_by_successful_types(self):
  checker=SimpleNamespace(workspace=SimpleNamespace(root=self.root),_exec=Mock(return_value={'success':True,'exit_code':0,'stdout':'types passed','stderr':''}))
  failure={'success':False,'exit_code':1,'stdout':'conditional hook error','stderr':'','lint':{'errors':1}}
  with patch('lint_frontend.run_lint',return_value=failure):result=run_frontend(checker)
  self.assertFalse(result['success']);self.assertIn('types passed',result['stdout']);self.assertEqual(checker._exec.call_count,1)
 def test_failed_types_cannot_be_hidden_by_successful_lint(self):
  checker=SimpleNamespace(workspace=SimpleNamespace(root=self.root),_exec=Mock(return_value={'success':False,'exit_code':2,'stdout':'type mismatch','stderr':''}))
  lint={'success':True,'exit_code':0,'stdout':'lint passed','stderr':'','lint':{'errors':0}}
  with patch('lint_frontend.run_lint',return_value=lint):result=run_frontend(checker)
  self.assertFalse(result['success']);self.assertEqual(result['exit_code'],2);self.assertEqual(checker._exec.call_count,1)
 def test_success_preserves_lint_and_build_evidence(self):
  checker=SimpleNamespace(workspace=SimpleNamespace(root=self.root),_exec=Mock(side_effect=[{'success':True,'exit_code':0,'stdout':'types checked','stderr':''},{'success':True,'exit_code':0,'stdout':'built','stderr':''}]))
  lint={'success':True,'exit_code':0,'stdout':'ESLint: 1 files, 0 errors, 0 warnings','stderr':'','lint':{'files':1,'errors':0,'warnings':0}}
  with patch('lint_frontend.run_lint',return_value=lint):r=run_frontend(checker)
  self.assertTrue(r['success']);self.assertEqual(r['lint'],lint['lint']);self.assertIn('types checked',r['stdout']);self.assertIn('built',r['stdout']);self.assertEqual(checker._exec.call_count,2)
