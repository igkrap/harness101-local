import signal,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-only/harness'))
import autonomy_runtime,supervisor
from call_budget import ask_with_recovery

class ExecutionPolicyTests(unittest.TestCase):
 def test_unlimited_can_complete_after_more_than_32_calls(self):
  with tempfile.TemporaryDirectory() as d:
   r=autonomy_runtime.Runner.__new__(autonomy_runtime.Runner)
   r.requirement_gate=SimpleNamespace(enabled=False,context=lambda:'');r._failed_ast_candidate=None
   r.args=SimpleNamespace(max_rounds=0,task='test');r.used=0;r.steps=[{'kind':'change','title':'test'}];r.step=0
   r.modes=[];r.messages=[];r.read=set();r.progress=0;r.idle=0;r.rejected_candidate=None;r.initial_screens=set();r.accepted=True
   r.h=SimpleNamespace(llm=SimpleNamespace(chat=Mock(return_value={'choices':[{'message':{'content':'work','tool_calls':[]}}]})),workspace=SimpleNamespace(root=Path(d)),log_event=Mock())
   r.cp=SimpleNamespace(pending=False);r.verify=Mock(return_value=(True,''));r.plan=Mock();r.fresh=Mock();r.tools=Mock(return_value=[]);r.verify_step=Mock(return_value=False)
   r.batch=Mock(side_effect=[([], '', False)]*39+[([], '', True)])
   with patch('autonomy_runtime.new_screen_error',return_value=None):self.assertTrue(r.run())
   self.assertEqual(r.used,40)
 def test_unlimited_keeps_timeout_recovery(self):
  r=SimpleNamespace(cp=SimpleNamespace(pending=False),used=40,args=SimpleNamespace(max_rounds=0),step=0,messages=[],tools=Mock(return_value=[]),h=SimpleNamespace(log_event=Mock()),fresh=Mock(),ask=Mock(side_effect=[TimeoutError('timed out'),{'ok':True}]))
  self.assertEqual(ask_with_recovery(r),{'ok':True});self.assertEqual(r.ask.call_count,2)
 def test_optional_positive_call_budget_still_works(self):
  r=autonomy_runtime.Runner.__new__(autonomy_runtime.Runner);r.args=SimpleNamespace(max_rounds=2);r.used=2;r.messages=[]
  with self.assertRaises(autonomy_runtime.BudgetEnd):r.ask([],[])
 def test_user_stop_rolls_back_once_and_repeated_signal_does_not_interrupt_cleanup(self):
  before=signal.getsignal(signal.SIGTERM);args=SimpleNamespace()
  def stop():signal.getsignal(signal.SIGTERM)(signal.SIGTERM,None)
  def cleanup():stop();return ['unfinished.tsx']
  r=SimpleNamespace(h=SimpleNamespace(log_event=Mock()),cp=SimpleNamespace(pending=True,rollback=Mock(side_effect=cleanup)),run=Mock(side_effect=stop))
  with patch('supervisor.Runner',return_value=r):self.assertFalse(supervisor.run_supervised(args,Mock()))
  self.assertTrue(args.stop_requested);r.cp.rollback.assert_called_once();self.assertIs(signal.getsignal(signal.SIGTERM),before)
  self.assertTrue(any(c.args[0]=='autonomy.stopped' for c in r.h.log_event.call_args_list))
 def test_clean_user_stop_preserves_committed_changes(self):
  args=SimpleNamespace()
  def stop():signal.getsignal(signal.SIGTERM)(signal.SIGTERM,None)
  r=SimpleNamespace(h=SimpleNamespace(log_event=Mock()),cp=SimpleNamespace(pending=False,rollback=Mock()),run=Mock(side_effect=stop))
  with patch('supervisor.Runner',return_value=r):self.assertFalse(supervisor.run_supervised(args,Mock()))
  r.cp.rollback.assert_not_called();self.assertTrue(args.stop_requested)

 def test_rollback_failure_is_not_a_clean_stop(self):
  args=SimpleNamespace()
  def stop():signal.getsignal(signal.SIGTERM)(signal.SIGTERM,None)
  r=SimpleNamespace(h=SimpleNamespace(log_event=Mock()),cp=SimpleNamespace(pending=True,rollback=Mock(side_effect=OSError('cannot restore'))),run=Mock(side_effect=stop))
  with patch('supervisor.Runner',return_value=r):self.assertFalse(supervisor.run_supervised(args,Mock()))
  self.assertTrue(args.stop_requested);self.assertTrue(args.stop_cleanup_failed)

 def test_large_base_prompt_does_not_reset_context_each_turn(self):
  with tempfile.TemporaryDirectory() as d:
   r=autonomy_runtime.Runner.__new__(autonomy_runtime.Runner);r.args=SimpleNamespace(max_rounds=1,task='ordinary edit');r.used=0;r.steps=[{'kind':'change','title':'test'}];r.step=0
   r.requirement_gate=SimpleNamespace(enabled=False,context=lambda:'');r._failed_ast_candidate=None
   r.modes=[];r.messages=[{'role':'system','content':'s'*32000},{'role':'user','content':'u'*12000}];r.read=set();r.progress=0;r.idle=0;r.rejected_candidate=None;r.initial_screens=set();r.accepted=True
   r.h=SimpleNamespace(llm=SimpleNamespace(chat=Mock(return_value={'choices':[{'message':{'content':'finish','tool_calls':[]}}]})),workspace=SimpleNamespace(root=Path(d)),log_event=Mock());r.cp=SimpleNamespace(pending=False)
   r.verify=Mock(return_value=(True,''));r.plan=Mock();r.fresh=Mock();r.tools=Mock(return_value=[]);r.verify_step=Mock(return_value=False);r.batch=Mock(return_value=([],'',True))
   with patch('autonomy_runtime.new_screen_error',return_value=None):self.assertTrue(r.run())
   self.assertEqual(r.used,1);r.fresh.assert_called_once_with()
