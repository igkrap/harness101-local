import json,os,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-only/harness'))
from call_budget import snapshot,ask_with_recovery
from test_autonomy import native

class ContextTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.paths=['frontend/src/App.tsx']+['frontend/src/screens/'+x+'.tsx' for x in ('A','B','C')]
  for rel in self.paths:p=self.root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(rel+'\n'+'x'*1000)
  self.r=SimpleNamespace(args=SimpleNamespace(task='기존 화면들 조회'),steps=[{'title':'Add query grids'}],step=0,read=set(self.paths),h=SimpleNamespace(workspace=native.WorkspaceManager(self.root)),messages=[{'role':'assistant','tool_calls':[{'function':{'name':'read_file','arguments':json.dumps({'path':p})}}]}for p in self.paths[1:]])
 def tearDown(self):self.tmp.cleanup()
 def test_recent_sources_survive_instead_of_alphabetical_app(self):
  text,paths=snapshot(self.r);self.assertEqual(paths,set(self.paths[1:]));self.assertIn('CURRENT FILE',text);self.assertNotIn('frontend/src/App.tsx',text)
 def test_explicit_step_file_takes_priority(self):
  self.r.steps=[{'title':'Fix '+self.paths[1]}];_,paths=snapshot(self.r);self.assertIn(self.paths[1],paths)
 def test_complete_source_limit_skips_oversized_file(self):
  (self.root/self.paths[-1]).write_text('x'*9001);text,paths=snapshot(self.r);self.assertNotIn(self.paths[-1],paths);self.assertEqual(len(paths),2);self.assertLess(len(text),10200)

class RecoveryTests(unittest.TestCase):
 def runner(self):return SimpleNamespace(cp=SimpleNamespace(pending=False),used=1,args=SimpleNamespace(max_rounds=5),step=0,messages=[{'role':'user','content':'goal'}],tools=Mock(return_value=[]),h=SimpleNamespace(log_event=Mock()),fresh=Mock(),ask=Mock())
 def test_timeout_retries_once_with_fresh_context(self):
  r=self.runner();r.ask.side_effect=[TimeoutError('timed out'),{'reply':'ok'}];self.assertEqual(ask_with_recovery(r),{'reply':'ok'});self.assertEqual(r.ask.call_count,2);r.fresh.assert_called_once();self.assertEqual(r.timeout_retries[1],1)
 def test_second_timeout_propagates(self):
  r=self.runner();r.ask.side_effect=TimeoutError('timed out')
  with self.assertRaises(TimeoutError):ask_with_recovery(r)
  self.assertEqual(r.ask.call_count,2)
 def test_non_timeout_does_not_retry(self):
  r=self.runner();r.ask.side_effect=ValueError('invalid API request')
  with self.assertRaises(ValueError):ask_with_recovery(r)
  self.assertEqual(r.ask.call_count,1);r.fresh.assert_not_called()
 def test_interruption_does_not_retry(self):
  r=self.runner();r.ask.side_effect=KeyboardInterrupt()
  with self.assertRaises(KeyboardInterrupt):ask_with_recovery(r)
  r.fresh.assert_not_called()
 def test_no_retry_with_pending_mutation(self):
  r=self.runner();r.cp.pending=True;r.ask.side_effect=TimeoutError()
  with self.assertRaises(TimeoutError):ask_with_recovery(r)
  self.assertEqual(r.ask.call_count,1)
 def test_retry_respects_exhausted_budget(self):
  r=self.runner()
  def timeout(*a,**k):r.used=5;raise TimeoutError('timed out')
  r.ask.side_effect=timeout
  with self.assertRaises(TimeoutError):ask_with_recovery(r)
  self.assertEqual(r.ask.call_count,1);r.fresh.assert_not_called()
 def test_default_call_timeout_is_ten_minutes(self):
  from runtime_policy import generation_settings
  with patch.dict(os.environ,{},clear=True):self.assertEqual(generation_settings()['timeout'],600)
