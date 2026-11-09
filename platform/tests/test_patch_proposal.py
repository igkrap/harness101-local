import json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-only/harness'))
from test_autonomy import native
from cycle_context import cycle_context as cycle

class ProposalTests(unittest.TestCase):
 def setUp(self):
  from patch_proposal import propose_patch
  self.propose=propose_patch;self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.src=self.root/'frontend/src/screens';self.src.mkdir(parents=True)
  self.file=self.src/'Registration.tsx';self.original='export function Registration(){return <form><TextInput/></form>;}';self.file.write_text(self.original);(self.src/'Inventory.tsx').write_text('export function Inventory(){return <Table data={rows}/>;}')
  self.h=SimpleNamespace(workspace=native.WorkspaceManager(self.root),_execute_tool=Mock(return_value={'docs':'Table data and columns props'}),log_event=Mock())
  self.r=SimpleNamespace(h=self.h,args=SimpleNamespace(task='조회 결과 그리드 없는 화면에 추가',ponytail='off',edit_format='diff'),modes=['frontend'],messages=[],read=set(),feedback='',accepted=False,used=1)
  self.service=cycle.service(self.h);self.service.run=Mock(return_value={'engine':'typescript-lsp','result':{'ready':True,'diagnostics':[]}})
 def tearDown(self):self.service.close();self.tmp.cleanup()
 def patch(self,new=None):return {'edits':[{'old_text':'return <form><TextInput/></form>;','new_text':new or 'return <form><TextInput/><Table data={rows}/></form>;'}]}
 def test_one_model_proposal_is_validated_without_writing(self):
  call=Mock(return_value={'content':json.dumps(self.patch())});out=self.propose(self.r,call);call.assert_called_once();self.assertEqual(out['tool_calls'][0]['function']['name'],'apply_edits');args=json.loads(out['tool_calls'][0]['function']['arguments']);self.assertEqual(args['path'],'frontend/src/screens/Registration.tsx');self.assertEqual(self.file.read_text(),self.original);self.assertIn(args['path'],self.r.read);self.assertEqual(call.call_args.args[1],[])
 def test_import_only_change_is_rejected_before_write(self):
  call=Mock(return_value={'content':json.dumps({'edits':[{'old_text':'export function','new_text':"import {Table} from 'ui';\nexport function"}]})});out=self.propose(self.r,call);self.assertFalse(out.get('tool_calls'));self.assertTrue(self.r.feedback);self.assertEqual(self.file.read_text(),self.original)
 def test_invalid_json_does_not_finish_or_write(self):
  out=self.propose(self.r,Mock(return_value={'content':'{"edits":['}));self.assertFalse(out.get('tool_calls'));self.assertIn('rejected',self.r.feedback.lower());self.assertEqual(self.file.read_text(),self.original)
 def test_request_failure_propagates_to_existing_recovery(self):
  with self.assertRaises(TimeoutError):self.propose(self.r,Mock(side_effect=TimeoutError('response headers timed out')))
 def test_confirmed_complete_contract_needs_no_model_call(self):
  self.file.write_text('export function Registration(){return <form><TextInput/><Table/></form>;}');self.r.accepted=True;call=Mock();out=self.propose(self.r,call);call.assert_not_called();self.assertEqual(out['tool_calls'][0]['function']['name'],'finish')
 def test_json_prose_uses_complete_valid_object(self):
  call=Mock(return_value={'content':'Proposed edits:\n```json\n'+json.dumps(self.patch())+'\n```'});out=self.propose(self.r,call);self.assertEqual(out['tool_calls'][0]['function']['name'],'apply_edits')

 def test_bounded_component_patch_larger_than_1800_reaches_validation(self):
  replacement='return <form><TextInput/><Table data={rows}/>{/*'+' existing form context '*100+'*/}</form>;'
  out=self.propose(self.r,Mock(return_value={'content':json.dumps(self.patch(replacement))}))
  self.assertEqual(out['tool_calls'][0]['function']['name'],'apply_edits')
  self.assertEqual(self.file.read_text(),self.original)

 def test_whole_candidate_still_has_size_bound(self):
  replacement='return <form><TextInput/><Table/>{/*'+'x'*31930+'*/}</form>;'
  out=self.propose(self.r,Mock(return_value={'content':json.dumps(self.patch(replacement))}))
  self.assertFalse(out.get('tool_calls'))
  self.assertEqual(self.file.read_text(),self.original)

 def test_identical_invalid_proposals_stop_without_automatic_whole_file_fallback(self):
  call=Mock(return_value={'content':'{"edits":['})
  for _ in range(3):self.propose(self.r,call)
  with self.assertRaisesRegex(RuntimeError,'No progress'):self.propose(self.r,call)
  self.assertEqual(call.call_count,3)
  self.assertEqual(self.file.read_text(),self.original)

 def test_changed_rejection_is_a_new_attempt_and_success_resets_stall(self):
  self.propose(self.r,Mock(return_value={'content':'bad-one'}))
  self.propose(self.r,Mock(return_value={'content':'bad-two'}))
  self.assertEqual(self.r._identical_rejections,1)
  out=self.propose(self.r,Mock(return_value={'content':json.dumps(self.patch())}))
  self.assertTrue(out.get('tool_calls'))
  self.assertEqual(self.r._identical_rejections,0)

 def test_explicit_whole_mode_excludes_rejected_json(self):
  for text in ('bad-json-one','bad-json-two'):
   self.propose(self.r,Mock(return_value={'content':text}))
  self.r.args.edit_format='whole'
  source='export function Registration(){return <form><TextInput/><Table data={rows}/></form>;}'
  call=Mock(return_value={'content':'```tsx\n'+source+'\n```'})
  out=self.propose(self.r,call)
  self.assertTrue(out.get('tool_calls'))
  args=json.loads(out['tool_calls'][0]['function']['arguments'])
  self.assertEqual(args['edits'],[{'old_text':self.original,'new_text':source}])
  prompt='\n'.join(m['content'] for m in call.call_args.args[0])
  self.assertIn(self.original,prompt)
  self.assertNotIn('bad-json-two',prompt)
  self.assertEqual(self.file.read_text(),self.original)

 def test_explicit_whole_mode_rejects_broken_jsx_without_writing(self):
  self.r.args.edit_format='whole'
  self.r._proposal_failures=2
  call=Mock(return_value={'content':'```tsx\nexport function Registration(){return <form><Table/>;\n```'})
  out=self.propose(self.r,call)
  self.assertFalse(out.get('tool_calls'))
  self.assertEqual(self.file.read_text(),self.original)

 def test_duplicate_replacement_key_is_rejected_explicitly(self):
  content='{"edits":[{"old_text":"return <form><TextInput/></form>;","new_text":"return <Table/>;","new_text":""}]}'
  out=self.propose(self.r,Mock(return_value={'content':content}))
  self.assertFalse(out.get('tool_calls'))
  self.assertIn('Duplicate JSON key',self.r.feedback)
  self.assertEqual(self.file.read_text(),self.original)

 def test_explicit_whole_mode_rejects_ambiguous_multiple_files(self):
  self.r.args.edit_format='whole'
  self.r._proposal_failures=2
  source='export function Registration(){return <form><TextInput/><Table/></form>;}'
  content='```tsx\n'+source+'\n```\n```tsx\n'+source+'\n```'
  out=self.propose(self.r,Mock(return_value={'content':content}))
  self.assertFalse(out.get('tool_calls'))
  self.assertEqual(self.file.read_text(),self.original)

 def test_default_uses_ast_fragments_even_after_prior_failures(self):
  del self.r.args.edit_format
  from ast_editing import editor
  self.r._proposal_failures=2
  snapshot=editor(self.h).snapshot('frontend/src/screens/Registration.tsx')
  node=next(n for n in snapshot['nodes'] if n['kind']=='insert' and 'JSX' in n['label'])
  fragment={'node_id':node['id'],'code':'<Table data={[]}/>'}
  call=Mock(return_value={'content':json.dumps({'edits':[fragment]})})
  out=self.propose(self.r,call)
  self.assertTrue(out.get('tool_calls'))
  args=json.loads(out['tool_calls'][0]['function']['arguments'])
  self.assertEqual(out['tool_calls'][0]['function']['name'],'apply_ast_edits')
  self.assertEqual(args['edits'],[fragment])
  self.assertIn('snapshot_id',args)
  self.assertEqual(self.file.read_text(),self.original)

 def test_ast_replacement_may_not_drop_existing_registration_form(self):
  del self.r.args.edit_format
  from ast_editing import editor
  snapshot=editor(self.h).snapshot('frontend/src/screens/Registration.tsx')
  node=next(n for n in snapshot['nodes'] if n['source']=='<form><TextInput/></form>')
  out=self.propose(self.r,Mock(return_value={'content':json.dumps({'edits':[{'node_id':node['id'],'code':'<Table/>'}]})}))
  self.assertFalse(out.get('tool_calls'))
  self.assertIn('form must be preserved',self.r.feedback)
  self.assertEqual(self.file.read_text(),self.original)

 def test_truncated_output_is_not_misreported_as_context_full(self):
  self.h.llm=SimpleNamespace(last_finish_reason='length')
  out=self.propose(self.r,Mock(return_value={'content':'{"edits":['}));self.assertFalse(out.get('tool_calls'));self.assertIn('trunc',self.r.feedback.lower());self.assertNotIn('context full',self.r.feedback.lower());self.assertEqual(self.file.read_text(),self.original)
