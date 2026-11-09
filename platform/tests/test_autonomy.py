import importlib.util
from pathlib import Path
import os
import sys
import tempfile
import unittest

HARNESS=Path(__file__).resolve().parents[2]/'local-only/harness'
sys.path.insert(0,str(HARNESS))
from checkpoints import Checkpoint
spec=importlib.util.spec_from_file_location('native_autonomy_test',HARNESS/'harness.py')
native=importlib.util.module_from_spec(spec);spec.loader.exec_module(native)

class CheckpointTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.cp=Checkpoint(native.WorkspaceManager(self.root))
 def tearDown(self):self.tmp.cleanup()
 def make(self,name,content=b'original'):
  p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(content);return p
 def test_rollback_exact_bytes_and_mode(self):
  p=self.make('app.py',b'original\r\n');p.chmod(0o751);self.cp.stage('app.py');p.write_bytes(b'broken');p.chmod(0o644);self.cp.record('app.py')
  self.assertEqual([str(p) for p in self.cp.rollback()],['app.py']);self.assertEqual(p.read_bytes(),b'original\r\n');self.assertEqual(p.stat().st_mode&0o777,0o751)
 def test_new_file_removed(self):
  self.cp.stage('new.py');p=self.make('new.py',b'new');self.cp.record('new.py');self.cp.rollback();self.assertFalse(p.exists())
 def test_deleted_file_restored(self):
  p=self.make('app.py');self.cp.stage('app.py');p.unlink();self.cp.record('app.py');self.cp.rollback();self.assertEqual(p.read_bytes(),b'original')
 def test_commit_and_repeated_stage(self):
  p=self.make('app.py');self.cp.stage('app.py');p.write_bytes(b'one');self.cp.record('app.py');self.cp.stage('app.py');p.write_bytes(b'two');self.cp.record('app.py');self.cp.rollback();self.assertEqual(p.read_bytes(),b'original')
  self.cp.stage('app.py');p.write_bytes(b'accepted');self.cp.record('app.py');self.cp.commit();self.cp.rollback();self.assertEqual(p.read_bytes(),b'accepted');self.assertFalse(self.cp.pending)
 def test_path_alias_is_one_transaction(self):
  p=self.make('app.py');self.cp.stage('app.py');p.write_bytes(b'one');self.cp.record('app.py');self.cp.stage('./app.py');p.write_bytes(b'two');self.cp.record('./app.py');self.cp.rollback();self.assertEqual(p.read_bytes(),b'original')
 def test_concurrent_change_preserved(self):
  p=self.make('app.py');q=self.make('other.py');self.cp.stage('app.py');self.cp.stage('other.py');p.write_bytes(b'agent');q.write_bytes(b'agent');self.cp.record('app.py');self.cp.record('other.py');p.write_bytes(b'user edit')
  with self.assertRaises(RuntimeError):self.cp.rollback()
  self.assertEqual(p.read_bytes(),b'user edit');self.assertEqual(q.read_bytes(),b'original')
 def test_symlinks_and_protected_paths(self):
  p=self.make('app.py');(self.root/'link.py').symlink_to(p)
  (self.root/'linked').symlink_to(self.root,target_is_directory=True)
  (self.root/'nested').mkdir();(self.root/'nested/link').symlink_to(self.root,target_is_directory=True)
  for name in ('link.py','linked/app.py','nested/link/app.py','harness/core.py','tests/test.py','../outside.py'):
   with self.assertRaises((ValueError,RuntimeError,native.HarnessError)):self.cp.stage(name)
 def test_concurrent_symlink_preserved(self):
  p=self.make('app.py');q=self.make('other.py',b'user');self.cp.stage('app.py');p.write_bytes(b'agent');self.cp.record('app.py');p.unlink();p.symlink_to(q)
  with self.assertRaises(RuntimeError):self.cp.rollback()
  self.assertTrue(p.is_symlink());self.assertEqual(q.read_bytes(),b'user')

# Independent tests use deterministic model replies and real temporary file writes.
def reply_tool(name, **args):
 import json
 return {'choices':[{'message':{'role':'assistant','content':None,'tool_calls':[{'id':'tool-'+name,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}}]}
def reply_text(text):return {'choices':[{'message':{'role':'assistant','content':text}}]}

class SupervisorTests(unittest.TestCase):
 def setUp(self):
  import json
  from types import SimpleNamespace
  from unittest.mock import patch
  from completion_fixture import EditorTestGate
  gate_patch=patch('completion_runner.Gate',EditorTestGate);gate_patch.start();self.addCleanup(gate_patch.stop)
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);(self.root/'app.py').write_text('broken')
  self.args=SimpleNamespace(task='Fix app.py',workspace=str(self.root),check='python',max_rounds=10,ponytail='off',llm_url='http://127.0.0.1:8099/v1',model='fixture')
  self.script=[];self.messages=[];self.schemas=[];self.events=[];self.check_calls=0;self.check_hook=None;owner=self
  class LLM:
   def chat(self,messages,tools=None):
    owner.messages.append(json.loads(json.dumps(messages)));owner.schemas.append(tools)
    if not owner.script:raise RuntimeError('Unexpected extra model call')
    return owner.script.pop(0)
  class Checker:
   def run_check(self,mode):
    owner.check_calls+=1
    content=(owner.root/'app.py').read_text()
    if owner.check_hook:owner.check_hook(content)
    ok=content=='fixed'
    return {'success':ok,'stdout':'' if ok else '[ERROR] actual failing assertion from STDOUT','stderr':'','exit_code':0 if ok else 1}
  class Harness(native.Harness):
   def __init__(self,args):
    super().__init__(args);self.llm=LLM();self.checker=Checker();self.evidence_path=owner.root/'evidence.log'
   def log_event(self,kind,data):owner.events.append((kind,data))
  self.Harness=Harness
 def tearDown(self):self.tmp.cleanup()
 def plan(self,steps=None):
  import json
  return reply_text(json.dumps({'steps':steps or [{'title':'Fix app.py','kind':'change'}]}))
 def run_supervisor(self):
  from supervisor import run_supervised
  return run_supervised(self.args,self.Harness)
 def test_existing_migrations_are_immutable_and_next_version_is_numeric(self):
  from autonomy_runtime import Runner
  folder=self.root/'backend/src/main/resources/db/migration';folder.mkdir(parents=True)
  for version in (1,2,10):(folder/f'V{version}__seed.sql').write_text('SELECT 1;')
  self.args.check='backend';runner=Runner(self.args,self.Harness)
  for name,extra in [('write_file',{'content':'SELECT 2;'}),('edit_file',{'old_text':'SELECT 1;','new_text':'SELECT 2;'}),('delete_file',{})]:
   with self.assertRaisesRegex(ValueError,'existing Flyway migrations'):
    runner.apply(name,{'path':'backend/src/main/resources/db/migration/V1__seed.sql',**extra},{})
  self.assertEqual((folder/'V1__seed.sql').read_text(),'SELECT 1;');self.assertFalse(runner.cp.pending)
  self.assertIn('V11__',runner.backend_context())
 def test_task_target_survives_snapshot_budget(self):
  from autonomy_runtime import Runner
  for name in ('a.java','b.java','target.java'):(self.root/name).write_text(name+'x'*2900)
  self.args.task='Fix target.java';runner=Runner(self.args,self.Harness);runner.read={'a.java','b.java','target.java'}
  text,paths=runner.current_context();self.assertIn('target.java',paths);self.assertIn('CURRENT FILE target.java',text)
 def test_rollback_feedback_keeps_actual_baseline_distinct(self):
  from autonomy_runtime import Runner
  self.script=[reply_tool('read_file',path='app.py'),reply_tool('edit_file',path='app.py',old_text='broken',new_text='worse'),reply_tool('edit_file',path='app.py',old_text='broken',new_text='fixed'),reply_tool('finish')]
  runner=Runner(self.args,self.Harness)
  def check(mode):
   value=(self.root/'app.py').read_text();return {'success':value=='fixed','stdout':{'broken':'ERROR: baseline count expected6 actual30','worse':'ERROR: rejected candidate GET id1 returned404','fixed':'passed'}[value],'stderr':''}
  runner.h.checker.run_check=check
  self.assertTrue(runner.run());context=str(self.messages[3]);self.assertIn('baseline count expected6 actual30',context);self.assertIn('rejected candidate GET id1 returned404',context);self.assertIn('Success',runner.baseline_feedback)
 def test_spring_isolation_uses_checkpoint_and_native_edit(self):
  from autonomy_runtime import Runner
  path='backend/src/test/java/Fixture.java';file=self.root/path;file.parent.mkdir(parents=True);original='import working.Valid;\n@SpringBootTest\nclass Fixture {}\n';file.write_text(original)
  self.args.check='backend';runner=Runner(self.args,self.Harness);runner.read.add(path)
  result=runner.apply('isolate_spring_test',{'path':path,'cleanup_sql':"DELETE FROM inventory WHERE category='테스트'"},{})
  self.assertNotIn('error',result);self.assertTrue(runner.cp.pending);self.assertIn('@org.springframework.transaction.annotation.Transactional',file.read_text());runner.cp.rollback();self.assertEqual(file.read_text(),original)
  names=[tool['function']['name'] for tool in runner.tools()];self.assertIn('isolate_spring_test',names)
 def test_new_screen_request_cannot_finish_by_editing_existing_file(self):
  self.args.task='품목 등록 기능도 화면 하나 구현해줘 제조업체를 위한 프로그램'
  self.script=[reply_tool('read_file',path='app.py'),reply_tool('write_file',path='app.py',content='fixed'),reply_tool('finish'),reply_tool('write_file',path='frontend/src/screens/Registration.tsx',content='export const meta={title:"등록"}; export default function Registration() {}'),reply_tool('finish')]
  self.assertTrue(self.run_supervisor());self.assertTrue((self.root/'frontend/src/screens/Registration.tsx').is_file());self.assertIn('separate new screen',str(self.messages[4]))
 def test_identical_write_does_not_stage_rollback_or_claim_a_change(self):
  from autonomy_runtime import Runner
  runner=Runner(self.args,self.Harness);runner.read.add('app.py');result=runner.apply('write_file',{'path':'app.py','content':'broken'},{})
  self.assertNotIn('error',result);self.assertFalse(runner.cp.pending);self.assertFalse(runner.accepted)
 def test_rejected_new_file_reference_survives_workspace_rollback(self):
  from autonomy_runtime import Runner
  self.args.max_rounds=1;path='frontend/src/screens/Rejected.tsx';candidate='export default function Rejected() { return brokenSource; }'
  self.script=[reply_tool('write_file',path=path,content=candidate)];runner=Runner(self.args,self.Harness)
  self.assertFalse(runner.run());self.assertFalse((self.root/path).exists());self.assertIn(candidate,runner.feedback);self.assertIn('REJECTED NEW FILE',runner.feedback)
 def test_focused_repair_rechecks_corrected_new_file(self):
  import json
  from autonomy_runtime import Runner
  self.args.check='frontend'
  self.args.task='화면 하나 구현해줘';path='frontend/src/screens/Registration.tsx';bad='import unused;\nexport const meta={title:"등록"}; export default function Registration() {}'
  self.script=[reply_tool('write_file',path=path,content=bad),reply_text(json.dumps({'edits':[{'old_text':'import unused;\n','new_text':''}]}))]
  runner=Runner(self.args,self.Harness)
  def check(mode):
   file=self.root/path;ok=not file.exists() or 'unused' not in file.read_text();return {'success':ok,'stdout':'' if ok else 'error TS6133 unused import','stderr':''}
  runner.h.checker.run_check=check;self.assertTrue(runner.run());self.assertNotIn('unused',(self.root/path).read_text());self.assertEqual(runner.used,2);self.assertIn('supplied rejected NEW file',str(self.messages[1]));self.assertTrue(any(k=='autonomy.rollback' for k,d in self.events))
 def test_final_verification_runs_at_exact_model_budget(self):
  from autonomy_runtime import Runner
  self.args.max_rounds=3;self.script=[reply_tool('read_file',path='app.py'),reply_tool('write_file',path='app.py',content='fixed'),reply_tool('finish')]
  runner=Runner(self.args,self.Harness);runner.plan=lambda:setattr(runner,'steps',[{'title':'Fix app.py','kind':'change'},{'title':'Verify','kind':'verify'}]);self.assertTrue(runner.run());self.assertEqual(runner.used,3);self.assertEqual(len([k for k,d in self.events if k=='autonomy.step_finished']),2)
 def test_deterministic_plan_cannot_skip_requested_screen(self):
  (self.root/'app.py').write_text('fixed');self.args.task='화면 하나 구현해줘';self.script=[reply_tool('write_file',path='frontend/src/screens/New.tsx',content='export const meta={title:"새 화면"}; export default function New() {}'),reply_tool('finish')]
  self.assertTrue(self.run_supervisor());self.assertTrue((self.root/'frontend/src/screens/New.tsx').is_file());self.assertIn('For separate screen requests',str(self.messages[0]));self.assertEqual(next(d['model_calls']for k,d in self.events if k=='autonomy.plan'),0)
 def test_failed_patch_rollback_then_actual_success(self):
  self.script=[reply_tool('read_file',path='app.py'),reply_tool('edit_file',path='app.py',old_text='broken',new_text='worse'),reply_tool('read_file',path='app.py'),reply_tool('edit_file',path='app.py',old_text='broken',new_text='fixed'),reply_tool('finish')]
  self.assertIs(self.run_supervisor(),True);self.assertEqual((self.root/'app.py').read_text(),'fixed')
  self.assertTrue(any(k=='autonomy.rollback' for k,d in self.events));self.assertTrue(any(k=='autonomy.accepted' for k,d in self.events))
  self.assertIn('actual failing assertion',str(self.messages[3]));self.assertIn('CURRENT FILE app.py\\nbroken',str(self.messages[3]))
 def test_distinct_reads_preserve_context_until_patch(self):
  (self.root/'note.py').write_text('context');(self.root/'other.py').write_text('context')
  self.script=[reply_tool('read_file',path='app.py'),reply_tool('read_file',path='note.py'),reply_tool('read_file',path='other.py'),reply_tool('edit_file',path='app.py',old_text='broken',new_text='fixed'),reply_tool('finish')]
  self.assertIs(self.run_supervisor(),True);self.assertEqual((self.root/'app.py').read_text(),'fixed')
 def test_known_failed_candidate_is_blocked_before_check(self):
  from failure_memory import FailureMemory
  FailureMemory(self.root).record({'app.py':{'before':b'broken','expected':b'worse'}},'earlier failure',True)
  self.script=[reply_tool('read_file',path='app.py'),reply_tool('edit_file',path='app.py',old_text='broken',new_text='worse'),reply_tool('read_file',path='app.py'),reply_tool('edit_file',path='app.py',old_text='broken',new_text='fixed'),reply_tool('finish')]
  self.assertIs(self.run_supervisor(),True);self.assertEqual(self.check_calls,3);self.assertTrue(any(k=='autonomy.blocked' for k,d in self.events));self.assertIn('REJECTED',str(self.messages[1]))
 def test_additive_tool_preserves_learned_imports(self):
  from failure_memory import FailureMemory
  (self.root/'app.py').write_text('fixed');path='backend/src/test/java/Fixture.java';p=self.root/path;p.parent.mkdir(parents=True);before=b'import working.Valid;\nclass Fixture {}\n';p.write_bytes(before)
  FailureMemory(self.root).record({path:{'before':before,'expected':before.replace(b'working.Valid',b'wrong.Missing')}},'COMPILATION ERROR',True)
  self.script=[reply_tool('read_file',path=path),reply_tool('insert_text',path=path,anchor='class Fixture {}',text='@java.lang.Deprecated\n',position='before'),reply_tool('finish')]
  self.assertIs(self.run_supervisor(),True);self.assertIn('import working.Valid;',p.read_text());self.assertIn('@java.lang.Deprecated',p.read_text())
 def test_multiple_additions_share_one_verified_transaction(self):
  (self.root/'app.py').write_text('fixed');path='backend/src/test/java/Fixture.java';p=self.root/path;p.parent.mkdir(parents=True);p.write_text('import working.Valid;\nclass Fixture {}\n')
  self.script=[reply_tool('read_file',path=path),reply_tool('apply_insertions',path=path,blocks=[{'anchor':'import working.Valid;','text':'\nimport new.Annotation;','position':'after'},{'anchor':'class Fixture {}','text':'@Annotation\n','position':'before'}]),reply_tool('finish')]
  self.assertIs(self.run_supervisor(),True);self.assertEqual(self.check_calls,3);self.assertIn('@Annotation',p.read_text());self.assertIn('import working.Valid;',p.read_text())
 def test_new_directory_discovery_does_not_reset_context(self):
  (self.root/'frontend/src/screens').mkdir(parents=True)
  self.script=[]+[reply_tool('list_files',path=p) for p in ['frontend','frontend/src','frontend/src/screens']]+[reply_tool('read_file',path='app.py'),reply_tool('edit_file',path='app.py',old_text='broken',new_text='fixed'),reply_tool('finish')]
  self.assertIs(self.run_supervisor(),True);self.assertFalse(any(k=='autonomy.retry' for k,d in self.events))
 def test_repeated_directory_walk_keeps_discovered_paths(self):
  (self.root/'frontend/src/screens').mkdir(parents=True)
  self.script=[]+[reply_tool('list_files',path=p) for p in ['frontend','frontend/src','frontend/src/screens']*2]+[reply_tool('read_file',path='app.py'),reply_tool('edit_file',path='app.py',old_text='broken',new_text='fixed'),reply_tool('finish')]
  self.assertIs(self.run_supervisor(),True);self.assertIn('frontend/src/screens',str(self.messages[7]));self.assertNotIn('list_files',[t['function']['name'] for t in self.schemas[7]])
 def test_frontend_gets_icon_accessibility_contract(self):
  self.args.check='frontend';self.args.max_rounds=2;self.script=[reply_tool('read_file',path='app.py')]
  self.assertIs(self.run_supervisor(),False);self.assertIn('isIconOnly',str(self.messages[1]));self.assertIn('accessible',str(self.messages[1]))
 def test_exact_patch_keeps_hooks_and_changes_import_plus_usage(self):
  self.args.edit_format='diff'  # Explicit legacy mode; default frontend editing uses AST IDs.
  (self.root/'app.py').write_text('fixed');path='frontend/src/App.tsx';p=self.root/path;p.parent.mkdir(parents=True);before="import {useState} from 'react';\nimport {Button} from 'ui';\nconst c=<Button/>;\n";p.write_text(before)
  self.script=[reply_tool('read_file',path=path),reply_tool('apply_edits',path=path,edits=[{'old_text':'{Button}','new_text':'{IconButton}'},{'old_text':'<Button/>','new_text':'<IconButton/>'}]),reply_tool('finish')]
  self.assertIs(self.run_supervisor(),True);self.assertTrue(p.read_text().startswith("import {useState} from 'react';"));self.assertIn('<IconButton/>',p.read_text())
 def test_backend_uses_actual_api_index(self):
  import json
  from unittest.mock import patch
  self.args.check='backend';self.args.max_rounds=2;self.script=[reply_tool('read_file',path='app.py')]
  cache=self.root/'.local/share/mlx-server/java-api';cache.mkdir(parents=True);(cache/'spring-test-api.json').write_text(json.dumps({'classes':{'Transactional':['verified.example.Transactional']},'signatures':{'Transactional':'interface verified.example.Transactional'},'artifacts':{'spring-test':'test-version'}}))
  with patch('pathlib.Path.home',return_value=self.root):self.assertIs(self.run_supervisor(),False)
  self.assertIn('verified.example.Transactional',str(self.messages[1]));self.assertIn('seed',str(self.messages[1]).lower())
 def test_repeated_bad_operation_keeps_tool_for_corrected_arguments(self):
  self.script=[reply_tool('read_file',path='app.py'),reply_tool('edit_file',path='app.py',old_text='absent',new_text='x'),reply_tool('edit_file',path='app.py',old_text='absent',new_text='x'),reply_tool('edit_file',path='app.py',old_text='broken',new_text='fixed'),reply_tool('finish')]
  self.assertIs(self.run_supervisor(),True);self.assertIn('edit_file',[t['function']['name'] for t in self.schemas[4]]);self.assertTrue(any(k=='autonomy.strategy' for k,d in self.events))
 def test_repeated_failed_write_keeps_creation_of_other_files_available(self):
  (self.root/'app.py').write_text('fixed');path='backend/src/main/resources/db/migration/V6__fixture.sql'
  self.script=[reply_tool('write_file',path='app.py',content='without prior read'),reply_tool('write_file',path='app.py',content='without prior read'),reply_tool('write_file',path=path,content='SELECT 1;'),reply_tool('finish')]
  self.assertTrue(self.run_supervisor());self.assertEqual((self.root/path).read_text(),'SELECT 1;');self.assertIn('write_file',[t['function']['name'] for t in self.schemas[2]])
 def test_sibling_write_later_in_batch_invalidates_old_dependency_failure(self):
  from autonomy_runtime import Runner
  path='backend/src/main/java/fixture/Entity.java';source='package fixture; class Entity {}';migration='backend/src/main/resources/db/migration/V6__fixture.sql'
  runner=Runner(self.args,self.Harness);runner.memory.record({path:{'before':None,'expected':source.encode()}},'Schema validation: missing table [fixture]',True)
  with self.assertRaisesRegex(ValueError,'exact candidate'):runner.memory.guard(path,None,source.encode(),'write_file')
  message=reply_tool('write_file',path=path,content=source)['choices'][0]['message']
  message['tool_calls']+=reply_tool('write_file',path=migration,content='CREATE TABLE fixture (id bigint);')['choices'][0]['message']['tool_calls']
  paths,error,_=runner.batch(message)
  self.assertEqual(error,'');self.assertEqual(set(paths),{path,migration});self.assertTrue((self.root/path).exists());self.assertTrue((self.root/migration).exists())
  runner.cp.rollback()
 def test_java_annotations_preserve_import_and_body(self):
  self.args.check='backend';(self.root/'app.py').write_text('fixed');path='backend/src/test/java/Fixture.java';p=self.root/path;p.parent.mkdir(parents=True);p.write_text('import good.Valid;\nclass Fixture {\n void test() {}\n}\n')
  self.script=[reply_tool('read_file',path=path),reply_tool('add_java_annotations',path=path,annotations=['java.lang.Deprecated']),reply_tool('finish')]
  self.assertIs(self.run_supervisor(),True);self.assertIn('import good.Valid;',p.read_text());self.assertIn('@java.lang.Deprecated\nclass Fixture',p.read_text());self.assertEqual(p.read_text().count('class Fixture'),1)
 def test_read_only_rounds_do_not_repeat_checks(self):
  self.args.max_rounds=4;self.script=[]+[reply_tool('read_file',path='app.py')]*3
  self.assertIs(self.run_supervisor(),False);self.assertEqual(self.check_calls,1)
 def test_finish_without_change_cannot_claim_success(self):
  (self.root/'app.py').write_text('fixed');self.args.max_rounds=2;self.script=[reply_tool('finish')]
  self.assertIs(self.run_supervisor(),False)
 def test_malformed_args_recovers_without_crash(self):
  bad=reply_tool('edit_file',path='app.py');bad['choices'][0]['message']['tool_calls'][0]['function']['arguments']='{bad'
  self.args.max_rounds=3;self.script=[bad,reply_tool('finish')]
  self.assertIs(self.run_supervisor(),False);self.assertEqual((self.root/'app.py').read_text(),'broken')
 def test_budget_exhaustion_rolls_back_broken_edit(self):
  self.args.max_rounds=3;self.script=[reply_tool('read_file',path='app.py'),reply_tool('write_file',path='app.py',content='worse')]
  self.assertIs(self.run_supervisor(),False);self.assertEqual((self.root/'app.py').read_text(),'broken')
 def test_concurrent_user_edit_preserved(self):
  self.script=[reply_tool('read_file',path='app.py'),reply_tool('edit_file',path='app.py',old_text='broken',new_text='worse')]
  def hook(content):
   if content=='worse':(self.root/'app.py').write_text('user edit')
  self.check_hook=hook
  self.assertIs(self.run_supervisor(),False);self.assertEqual((self.root/'app.py').read_text(),'user edit')
 def test_stop_restores_pending_edit(self):
  import signal
  self.script=[reply_tool('read_file',path='app.py'),reply_tool('edit_file',path='app.py',old_text='broken',new_text='worse')]
  def hook(content):
   if content=='worse':signal.getsignal(signal.SIGTERM)(signal.SIGTERM,None)
  self.check_hook=hook
  self.assertIs(self.run_supervisor(),False);self.assertEqual((self.root/'app.py').read_text(),'broken')
 def test_existing_java_assertion_cannot_be_weakened(self):
  path='backend/src/test/java/Test.java';p=self.root/path;p.parent.mkdir(parents=True);before='class Test { @Test void t() {\n.andExpect(status().isOk());\n}}';p.write_text(before)
  self.args.max_rounds=3;self.script=[reply_tool('read_file',path=path),reply_tool('edit_file',path=path,old_text='isOk()',new_text='isCreated()')]
  self.assertIs(self.run_supervisor(),False);self.assertEqual(p.read_text(),before)
 def test_two_steps_are_checked_and_advanced(self):
  from autonomy_runtime import Runner
  self.script=[reply_tool('read_file',path='app.py'),reply_tool('edit_file',path='app.py',old_text='broken',new_text='fixed'),reply_tool('finish')]
  runner=Runner(self.args,self.Harness);runner.plan=lambda:setattr(runner,'steps',[{'title':'Fix app.py','kind':'change'},{'title':'Verify','kind':'verify'}])
  self.assertIs(runner.run(),True);self.assertEqual(sum(k=='autonomy.step_finished' for k,d in self.events),2);self.assertEqual(len(self.messages),3)
 def test_initial_plan_uses_no_model(self):
  from autonomy_runtime import Runner
  runner=Runner(self.args,self.Harness);runner.plan();self.assertEqual(runner.used,0);self.assertEqual(self.messages,[]);self.assertEqual(runner.steps,[{'title':self.args.task,'kind':'change'}]);self.assertEqual(self.events[-1][1]['model_calls'],0)
