import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from history import History
from context_report import context_report

class ContextReportTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.h=History(self.root);self.job={'id':'a'*32,'kind':'agent','status':'running','started_at':'2026-11-01T00:00:00Z'};self.folder=self.root/self.job['id'];self.folder.mkdir()
 def tearDown(self):self.h.close();self.tmp.cleanup()
 def report(self,events):
  (self.folder/'events.jsonl').write_text(''.join(json.dumps({'seq':i+1,'type':kind,'time':'2026-11-01T00:00:00Z','data':data})+'\n'for i,(kind,data)in enumerate(events)));self.h.sync(self.job);return context_report(self.h,self.job)
 def test_pending_request_is_distinct_from_previous_confirmed_usage(self):
  r=self.report([('model.request',{'estimated_input_tokens':100}),('model.response',{'usage':{'prompt_tokens':80,'completion_tokens':12},'text':'private source must not leak','finish_reason':'length'}),('model.request',{'estimated_input_tokens':200,'context':{'budget_tokens':32768,'reserved_output_tokens':4096}})])
  self.assertTrue(r['waiting']);self.assertEqual(r['current']['estimated_input_tokens'],200);self.assertEqual(r['confirmed']['usage']['prompt_tokens'],80);self.assertNotIn('private source',json.dumps(r));self.assertEqual(r['confirmed']['finish_reason'],'length');self.assertEqual(r['counts']['requests'],2)
 def test_legacy_budget_remains_unknown(self):
  r=self.report([('model.request',{'estimated_input_tokens':1234})]);self.assertIsNone(r['current']['context']);self.assertIsNone(r['confirmed']);self.assertEqual(r['counts']['compactions'],0)
 def test_compaction_is_actual_record_and_does_not_leak_prompt(self):
  cut={'before':{'estimated_input_tokens':18000},'after':{'estimated_input_tokens':9000},'reason':'history budget','removed_messages':8,'model_calls':0,'retained_paths':['frontend/src/A.tsx']}
  r=self.report([('autonomy.compact',cut),('autonomy.analysis',{'paths':['frontend/src/A.tsx'],'model_calls':0})]);self.assertEqual(r['compaction']['after']['estimated_input_tokens'],9000);self.assertEqual(r['counts']['compactions'],1);self.assertEqual(r['files'],['frontend/src/A.tsx'])
 def test_stopped_request_does_not_look_like_a_pending_model(self):
  self.job['status']='stopped';r=self.report([('model.request',{'estimated_input_tokens':100})]);self.assertFalse(r['waiting'])
 def test_model_error_ends_pending_state(self):
  r=self.report([('model.request',{'estimated_input_tokens':100}),('model.error',{'error':'connection failed'})]);self.assertFalse(r['waiting'])
