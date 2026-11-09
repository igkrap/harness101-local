import os
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-only/harness'))
from isolated_backend import run_backend


class IsolatedBackendTests(unittest.TestCase):
 def setUp(self):
  self.calls=[]
  self.checker=SimpleNamespace(_exec=lambda cmd:(self.calls.append(cmd) or {'success':True,'stdout':'','stderr':''}))
 def test_unique_database_used_and_environment_restored(self):
  seen=[]
  with patch.dict(os.environ,{'HARNESS_TEST_DB_URL':'jdbc:postgresql://mdi-db:5432/project_test'}):
   for _ in range(2):
    result=run_backend(self.checker,lambda:(seen.append(os.environ['HARNESS_TEST_DB_URL']) or {'success':True,'stdout':'passed'}));self.assertTrue(result['success'])
    self.assertEqual(os.environ['HARNESS_TEST_DB_URL'],'jdbc:postgresql://mdi-db:5432/project_test')
  self.assertNotEqual(seen[0],seen[1]);self.assertTrue(all('/mdi_gate_' in url for url in seen));self.assertEqual(len(self.calls),4)
  for create,drop in zip(self.calls[::2],self.calls[1::2]):self.assertIn(create[-1].split()[-1],drop[-1]);self.assertTrue(drop[-1].startswith('DROP DATABASE IF EXISTS mdi_gate_'))
 def test_create_failure_never_runs_callback_or_drops(self):
  self.checker._exec=lambda cmd:(self.calls.append(cmd) or {'success':False,'stderr':'create denied'})
  result=run_backend(self.checker,lambda:self.fail('callback must not run'))
  self.assertFalse(result['success']);self.assertEqual(len(self.calls),1)
 def test_callback_failure_still_drops_database(self):
  with self.assertRaisesRegex(KeyboardInterrupt,'cancelled'):
   run_backend(self.checker,lambda:(_ for _ in ()).throw(KeyboardInterrupt('cancelled')))
  self.assertEqual(len(self.calls),2)
 def test_cleanup_failure_does_not_report_success(self):
  self.checker._exec=lambda cmd:(self.calls.append(cmd) or {'success':len(self.calls)==1,'stderr':'drop denied'})
  self.assertFalse(run_backend(self.checker,lambda:{'success':True})['success'])
 def test_cleanup_failure_preserves_callback_exception(self):
  self.checker._exec=lambda cmd:(self.calls.append(cmd) or {'success':len(self.calls)==1,'stderr':'drop denied'})
  with self.assertRaisesRegex(ValueError,'callback error'):
   run_backend(self.checker,lambda:(_ for _ in ()).throw(ValueError('callback error')))
 def test_unsupported_host_cannot_target_another_database(self):
  with patch.dict(os.environ,{'HARNESS_TEST_DB_URL':'jdbc:postgresql://elsewhere:5432/production'}):
   self.assertFalse(run_backend(self.checker,lambda:self.fail('unexpected callback'))['success'])
  self.assertEqual(self.calls,[])
