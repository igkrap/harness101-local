import sys,unittest,json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-only/harness'))
from context_budget import measure,extend_context

class ContextBudgetTests(unittest.TestCase):
 def test_documentation_compaction_keeps_current_source_and_edit_ids(self):
  from recent_context import compact
  r=SimpleNamespace(args=SimpleNamespace(task='Change screen'),baseline_feedback='',feedback='',read=set(),
   current_context=lambda:('CURRENT AST n17 return <main/>',{'frontend/src/Screen.tsx'}),
   h=SimpleNamespace(log_event=Mock()))
  r.messages=[{'role':'system','content':'rules'},{'role':'user','content':'old source'},
   {'role':'assistant','tool_calls':[{'id':'one','function':{'name':'astryx_docs','arguments':'{}'}}]},
   {'role':'tool','tool_call_id':'one','content':'Stack docs'},
   {'role':'assistant','tool_calls':[{'id':'two','function':{'name':'astryx_docs','arguments':'{}'}}]},
   {'role':'tool','tool_call_id':'two','content':'Table docs'}]
  self.assertTrue(compact(r,[],4096,32768,'long history'))
  self.assertIn('CURRENT AST n17',r.messages[1]['content'])
  self.assertIn('frontend/src/Screen.tsx',r.read)
  self.assertIn('Table docs',str(r.messages))
 def test_capacity_is_budget_not_remaining_and_reservation_is_separate(self):
  messages=[{'role':'system','content':'rules'},{'role':'user','content':'한글 source'}];s=measure(messages,[],reserved=100,capacity=1000);self.assertEqual(s['budget_tokens'],1000);self.assertEqual(s['remaining_tokens'],1000-s['estimated_input_tokens']-100);self.assertTrue(s['estimated']);self.assertEqual(s['message_count'],2);self.assertEqual(s['reserved_output_tokens'],100)
 def test_tool_results_and_schema_are_counted(self):
  s=measure([{'role':'tool','content':'result'}],[{'type':'function','function':{'name':'read'}}]);self.assertEqual(s['tool_result_count'],1);self.assertGreater(s['tools_tokens_estimate'],0)
 def test_pressure_rebuilds_from_current_state_without_extra_model_call(self):
  class Base:
   def tools(self):return []
   def fresh(self,reason=''):self.messages=[{'role':'system','content':'rules'},{'role':'user','content':'goal, current source and last error'}]
   def ask(self,messages,tools):self.calls+=1;return {'message_count':len(messages)}
  r=extend_context(Base)();r.calls=0;r.h=SimpleNamespace(log_event=Mock());r.read={'frontend/src/A.tsx'};r.messages=[{'role':'system','content':'rules'},{'role':'user','content':'goal'},{'role':'assistant','content':'x'*85000}]
  result=r.ask(r.messages,[]);self.assertEqual(result['message_count'],2);self.assertEqual(r.calls,1);event,data=r.h.log_event.call_args.args;self.assertEqual(event,'autonomy.compact');self.assertEqual(data['model_calls'],0);self.assertEqual(data['removed_messages'],1);self.assertIn('frontend/src/A.tsx',data['retained_paths']);self.assertLess(data['after']['estimated_input_tokens'],data['before']['estimated_input_tokens'])
