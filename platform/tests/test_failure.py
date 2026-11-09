import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from failure import describe_failure,diagnostic
class FailureTests(unittest.TestCase):
 def job(self,**overrides):return {'id':'test','kind':'agent','status':'failed','rounds':16,'exit_code':1,**overrides}
 def test_budget_end_and_previously_verified_error_are_separate(self):
  event={'seq':5,'type':'autonomy.rollback','data':{'reason':'[frontend] src/New.tsx(1,2): error TS2322: invalid prop','paths':['frontend/src/New.tsx']}}
  report=describe_failure(self.job(),event,{'model.request':16,'autonomy.step_finished':1},{'data':{'steps':[{},{}]}},{'seq':10})
  self.assertEqual(report['code'],'round_limit');self.assertTrue(report['later_verified']);self.assertEqual(report['completed_steps'],1);self.assertEqual(report['total_steps'],2);self.assertEqual(report['failure']['path'],'frontend/src/New.tsx')
 def test_actual_type_error_precedes_success_and_warning_noise(self):
  result=diagnostic({'seq':1,'type':'check.finished','data':{'mode':'frontend','stdout':'[INFO] setup\nsrc/New.tsx: error TS2322: invalid prop\n[framework] Success\n WARN expected400\nError message = null'}})
  self.assertEqual(result['message'],'src/New.tsx: error TS2322: invalid prop')
 def test_fatal_request_error_not_mislabeled_budget(self):
  report=describe_failure(self.job(),{'seq':1,'type':'model.error','data':{'error':'connection refused'}},{'model.request':16});self.assertEqual(report['code'],'error');self.assertIn('connection refused',report['failure']['message'])
 def test_no_unrecorded_cause_is_invented(self):
  report=describe_failure(self.job(exit_code=-9),None,{});self.assertEqual(report['code'],'incomplete');self.assertIsNone(report['failure']);self.assertEqual(report['exit_code'],-9)
 def test_explicit_larger_limit_is_preserved(self):
  report=describe_failure(self.job(rounds=64),{'type':'tool.finished','data':{'name':'read_file','error':'missing file'}},{'model.request':16});self.assertEqual(report['code'],'error');self.assertEqual(report['limit'],64)
