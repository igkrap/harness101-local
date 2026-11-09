from pathlib import Path
import json,sys,tempfile,unittest
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-only/harness'))
from focused_repair import repair_new
class RepairTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.calls=[];self.reply={'content':json.dumps({'edits':[{'old_text':'import unused;\n','new_text':''}]})}
  def ask(messages,tools):self.calls.append(messages);return self.reply
  self.runner=SimpleNamespace(used=3,h=SimpleNamespace(workspace=SimpleNamespace(safe_path=lambda p:self.root/p)),ask=ask)
  self.record={'path':'New.tsx','source':'import unused;\nexport default function New() {}','error':'TS6133 unused'}
 def tearDown(self):self.tmp.cleanup()
 def test_only_model_patch_is_applied_and_not_written(self):
  response=repair_new(self.runner,self.record);args=json.loads(response['tool_calls'][0]['function']['arguments']);self.assertEqual(args['content'],'export default function New() {}');self.assertFalse((self.root/'New.tsx').exists());self.assertEqual(self.calls[0][0]['role'],'system')
 def test_structured_tool_response_applies_only_model_edits(self):
  from unittest.mock import Mock
  self.runner.ask=Mock(return_value={'role':'assistant','content':None,'tool_calls':[{'type':'function','id':'repair','function':{'name':'repair_new_file','arguments':self.reply['content']}}]})
  result=repair_new(self.runner,self.record)
  self.assertEqual(self.runner.ask.call_args.kwargs['tools'][0]['function']['name'],'repair_new_file')
  self.assertEqual(json.loads(result['tool_calls'][0]['function']['arguments'])['content'],'export default function New() {}')
  self.assertIn('repair_new_file',self.record['repair_reply'])
 def test_concurrent_file_is_not_overwritten(self):
  (self.root/'New.tsx').write_text('user edit')
  with self.assertRaises(ValueError):repair_new(self.runner,self.record)
  self.assertEqual((self.root/'New.tsx').read_text(),'user edit');self.assertEqual(self.calls,[])
 def test_bad_model_reply_is_rejected(self):
  for content in (None,'','{}','{"edits":{}}','{"edits":["bad"]}',json.dumps({'edits':[{'old_text':'absent','new_text':'x'}]}),json.dumps({'edits':[{'old_text':'','new_text':'x'}]})):
   self.reply={'content':content}
   with self.subTest(content=content),self.assertRaises(ValueError):repair_new(self.runner,self.record)
 def test_large_source_is_rejected_before_call(self):
  self.record['source']='x'*12001
  with self.assertRaises(ValueError):repair_new(self.runner,self.record)
  self.assertEqual(self.calls,[])
 def test_final_model_draft_is_used_without_combining_earlier_edits(self):
  earlier=json.dumps({'edits':[{'old_text':'export default','new_text':'wrong draft'}]})
  final=self.reply['content']
  self.reply={'content':f'```json\n{earlier}\n```\nCorrection:\n```json\n{final}\n```\n'}
  result=repair_new(self.runner,self.record)
  self.assertEqual(json.loads(result['tool_calls'][0]['function']['arguments'])['content'],'export default function New() {}')
 def test_invalid_final_draft_never_falls_back_to_earlier_valid_one(self):
  valid=self.reply['content']
  for tail in ('```json\n{"edits":', '```json\n{"edits":}\n```', '```json\n{}\n```', '```json\n'+valid+'\n```\nactually wrong', '```typescript\n'+valid+'\n```'):
   self.reply={'content':f'```json\n{valid}\n```\nRevision:\n{tail}'}
   with self.subTest(tail=tail),self.assertRaises(ValueError):repair_new(self.runner,self.record)
 def test_duplicate_keys_extra_keys_and_concatenated_objects_are_rejected(self):
  valid=self.reply['content']
  for text in (valid+valid, '{"edits":[],"edits":[]}', '{"edits":[{"old_text":"a","old_text":"b","new_text":"c"}]}', '{"edits":[],"extra":true}', '{"edits":[{"old_text":"import unused;","new_text":"","extra":1}]}'):
   self.reply={'content':text}
   with self.subTest(text=text),self.assertRaises(ValueError):repair_new(self.runner,self.record)
 def test_exact_edit_validation_still_applies_to_final_block(self):
  for edits in ([{'old_text':'import unused;','new_text':'import unused;'}], [{'old_text':'absent','new_text':'x'}]):
   self.reply={'content':'```json\n'+json.dumps({'edits':edits})+'\n```'}
   with self.assertRaises(ValueError):repair_new(self.runner,self.record)
 def test_retry_includes_original_error_source_and_format_feedback(self):
  self.record.update(repair_error='Invalid JSON shape',repair_reply='bad prior response')
  repair_new(self.runner,self.record)
  prompt=self.calls[0][1]['content']
  for value in (self.record['source'],self.record['error'],'Invalid JSON shape','bad prior response'):
   self.assertIn(value,prompt)
 def test_type_contracts_have_separate_budget_and_virtual_candidate_owner(self):
  from unittest.mock import patch
  from focused_repair import repair_diagnostic
  self.runner.h.workspace.root=self.root
  self.record['error']='Type mismatch FieldDefinition. '+('diagnostic '*400)
  declaration='Project declaration fields.ts:1\nexport type FieldDefinition = '+('x'*3000)+';'
  with patch('installed_type_records.declarations',return_value=[declaration,'overflow'*1000]) as lookup:
   context=repair_diagnostic(self.runner,self.record)
  self.assertIn(declaration,context);self.assertNotIn('overflow',context)
  self.assertLess(len(context),5300)
  self.assertEqual(lookup.call_args.kwargs,{'source':'New.tsx','source_text':self.record['source']})
 def test_type_lookup_warning_alone_does_not_shorten_original_diagnostic(self):
  from unittest.mock import patch
  from focused_repair import repair_diagnostic
  self.runner.h.workspace.root=self.root
  self.record['error']='FieldDefinition '+('diagnostic '*400)
  with patch('installed_type_records.declarations',return_value=['Local type extraction unavailable: missing source']):
   self.assertEqual(repair_diagnostic(self.runner,self.record),self.record['error'][:2500])
 def test_compiler_excerpt_uses_own_candidate_lines_for_lint_and_tsc(self):
  from focused_repair import candidate_error_context
  record={'path':'frontend/src/screens/New.tsx','source':'\n'.join('source '+str(n) for n in range(1,21)),
          'error':'frontend/src/App.tsx:2:1 warning unrelated\nfrontend/src/screens/New.tsx:10:3 error parse\nsrc/screens/New.tsx(14,2): error TS1234: bad'}
  context=candidate_error_context(record)
  self.assertIn('10: source 10',context);self.assertIn('14: source 14',context)
  self.assertNotIn('2: source 2\n',context)

class RepairLoopTests(unittest.TestCase):
 def make_runner(self,replies):
  from autonomy_runtime import Runner
  runner=Runner.__new__(Runner)
  runner.args=SimpleNamespace(max_rounds=len(replies),task='Fix new source')
  runner.used=0;runner.step=0;runner.idle=0;runner.progress=0;runner.read=set();runner.accepted=False
  runner.rejected_candidate={'path':'New.ts','source':'const unused = 1;\nexport const value = 2;','error':'TS6133 unused'}
  runner.h=SimpleNamespace(workspace=SimpleNamespace(root=Path('/unused'),safe_path=lambda p:SimpleNamespace(exists=lambda:False)),log_event=lambda *a:None)
  runner.cp=SimpleNamespace(pending=False)
  runner.verify=lambda:(True,'');runner.verify_step=lambda:False
  runner.plan=lambda:setattr(runner,'steps',[{'title':'Fix new source','kind':'change'}])
  runner.fresh=lambda reason='':setattr(runner,'messages',[])
  seen=[];written=[]
  def ask(messages,tools):
   seen.append(messages);reply=replies[runner.used];runner.used+=1;return {'content':reply}
  def batch(msg):
   written.append(json.loads(msg['tool_calls'][0]['function']['arguments'])['content'])
   runner.accepted=True
   return [],'',True
  runner.ask=ask;runner.batch=batch;runner.initial_screens=set()
  return runner,seen,written
 def test_bad_reply_preserves_candidate_for_next_focused_call(self):
  valid=json.dumps({'edits':[{'old_text':'const unused = 1;\n','new_text':''}]})
  runner,seen,written=self.make_runner(['not json',valid])
  self.assertTrue(runner.run())
  self.assertEqual(written,['export const value = 2;'])
  self.assertIn('const unused = 1;',seen[1][1]['content'])
  self.assertIn('TS6133 unused',seen[1][1]['content'])
  self.assertIn('not json',seen[1][1]['content'])
  self.assertIsNone(runner.rejected_candidate)
 def test_repeated_bad_replies_still_stop_at_budget_with_no_write(self):
  runner,seen,written=self.make_runner(['not json','still not json'])
  self.assertFalse(runner.run())
  self.assertEqual(len(seen),2);self.assertEqual(written,[])
  self.assertEqual(runner.rejected_candidate['source'],'const unused = 1;\nexport const value = 2;')
 def test_pre_call_source_conflict_returns_to_normal_budgeted_discovery(self):
  from unittest.mock import patch
  runner,seen,written=self.make_runner(['unused'])
  runner.h.workspace.safe_path=lambda p:SimpleNamespace(exists=lambda:True)
  runner.batch=lambda msg:([],'',False)
  def normal_ask(r):
   r.used+=1
   return {'content':'Inspect changed source'}
  with patch('call_budget.ask_with_recovery',side_effect=normal_ask) as normal:
   self.assertFalse(runner.run())
   self.assertEqual(normal.call_count,1)
  self.assertEqual(seen,[]);self.assertEqual(written,[])
  self.assertIsNone(runner.rejected_candidate)
