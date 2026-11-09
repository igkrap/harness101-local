from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-only/harness'))

class SeedUpdatesTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.migrations=self.root/'backend/src/main/resources/db/migration';self.migrations.mkdir(parents=True)
  (self.migrations/'V1__create.sql').write_text('CREATE TABLE inventory (id bigint, name text, category text);')
  self.test=self.root/'backend/src/test/java/InventoryTest.java';self.test.parent.mkdir(parents=True);self.test.write_text('@Test\n.andExpect(jsonPath("$[0].name").value("고춧가루"))\n.andExpect(jsonPath("$.length()").value(6))')
  self.args={'table':'inventory','rows':[{'id':1,'old_values':{'name':'고춧가루'},'values':{'name':"Maker's Steel",'category':'자재'}}]}
 def tearDown(self):self.tmp.cleanup()
 def edits(self,args=None):
  from seed_updates import seed_edits
  return seed_edits(self.root,args or self.args)
 def test_sql_and_test_are_one_atomic_operation_set(self):
  ops=self.edits();sql=next(op['args']['content'] for op in ops if op['name']=='write_file')
  self.assertIn("Maker''s Steel",sql);self.assertIn('WHERE',sql);self.assertRegex(sql,r'id\s*=\s*1');self.assertIn('고춧가루',sql)
  self.assertNotRegex(sql.upper(),r'CREATE|INSERT|DELETE|DROP');self.assertNotIn('\\n',sql)
  changes=[op for op in ops if op['name']=='edit_file'];self.assertEqual(len(changes),1);self.assertIn('.value("Maker\'s Steel")',changes[0]['args']['new_text']);self.assertIn('.value(6)',changes[0]['args']['new_text']);self.assertIn('$[0].name',changes[0]['args']['new_text'])
  self.assertEqual(len(list(self.migrations.glob('*.sql'))),1);self.assertIn('고춧가루',self.test.read_text())
 def test_invalid_payloads_cannot_create_operations(self):
  for bad in [{**self.args,'table':'inventory; DROP TABLE x'}, {'table':'missing','rows':self.args['rows']}, {**self.args,'rows':[]}, {**self.args,'rows':self.args['rows']*2}, {**self.args,'rows':[{'id':True,'old_values':{'name':'x'},'values':{'name':'y'}}]}, {**self.args,'rows':[{'id':1,'old_values':{'name':'x'},'values':{'id':7}}]}, {**self.args,'rows':[{'id':1,'old_values':{},'values':{'name':'y'}}]}, {**self.args,'rows':[{'id':1,'old_values':{'name':'x'},'values':{'name':float('nan')}}]}]:
   with self.subTest(bad=bad),self.assertRaises((ValueError,TypeError)):self.edits(bad)
 def test_numeric_version_and_symlink_escape(self):
  (self.migrations/'V10__other.sql').write_text('SELECT 1;');ops=self.edits();self.assertTrue(next(op['args']['path'] for op in ops if op['name']=='write_file').endswith('V11__update_seed_examples.sql'))
  with tempfile.TemporaryDirectory() as other:
   f=Path(other)/'External.java';f.write_text(self.test.read_text());self.test.unlink();self.test.symlink_to(f)
   try:ops=self.edits()
   except ValueError:return
   self.assertFalse(any(op['name']=='edit_file' for op in ops))
 def test_distinct_categories_allowed_when_tests_do_not_assert_old_category(self):
  rows=[{'id':1,'old_values':{'name':'고춧가루','category':'양념'},'values':{'name':'Steel','category':'금속'}},{'id':2,'old_values':{'name':'참기름','category':'양념'},'values':{'name':'Capacitor','category':'전자부품'}}]
  ops=self.edits({'table':'inventory','rows':rows});self.assertEqual(len(ops),2)
  self.test.write_text(self.test.read_text()+'\n.andExpect(jsonPath("$[0].category").value("양념"))')
  with self.assertRaises(ValueError):self.edits({'table':'inventory','rows':rows})
 def test_seed_task_routing(self):
  from seed_updates import is_seed_request
  self.assertTrue(is_seed_request('재고가 음식재료인데 제조업체 예시로'))
  self.assertFalse(is_seed_request('탭 닫기 버튼을 아이콘으로 바꿔줘'))

class SeedRunnerTests(SeedUpdatesTests):
 def setUp(self):
  super().setUp()
  from unittest.mock import patch
  from completion_fixture import EditorTestGate
  gate_patch=patch('completion_runner.Gate',EditorTestGate);gate_patch.start();self.addCleanup(gate_patch.stop)
 def test_native_tool_keeps_atomic_checkpoint_and_schema(self):
  import importlib.util
  from types import SimpleNamespace
  from autonomy_runtime import Runner
  hpath=Path(__file__).resolve().parents[2]/'local-only/harness/harness.py'
  spec=importlib.util.spec_from_file_location('seed_native',hpath);native=importlib.util.module_from_spec(spec);spec.loader.exec_module(native)
  args=SimpleNamespace(workspace=str(self.root),task='재고 예시를 제조업 자재로',check='backend',model='fixture',llm_url='http://127.0.0.1:8099/v1',ponytail='off',max_rounds=8)
  runner=Runner(args,native.Harness);names=[t['function']['name'] for t in runner.tools()]
  self.assertIn('update_seed_rows',names);self.assertNotIn('write_file',names)
  before={};result=runner.apply('update_seed_rows',self.args,before)
  self.assertNotIn('error',result);self.assertEqual(len(before),2);self.assertTrue(runner.cp.pending)
  self.assertIn("Maker's Steel",self.test.read_text());self.assertEqual(len(list(self.migrations.glob('*.sql'))),2)
  runner.cp.rollback();self.assertIn('고춧가루',self.test.read_text());self.assertEqual(len(list(self.migrations.glob('*.sql'))),1)
 def test_early_native_error_is_not_reported_as_success(self):
  from types import SimpleNamespace
  from unittest.mock import patch
  from seed_executor import apply_seed
  runner=SimpleNamespace(h=SimpleNamespace(workspace=SimpleNamespace(root=self.root)),apply=lambda *args:{'error':'native validation rejected'})
  with patch('seed_executor.seed_edits',return_value=[{'name':'write_file','args':{'path':'a'}}]):
   self.assertEqual(apply_seed(runner,{},{}),{'error':'native validation rejected'})
 def test_verified_seed_update_finishes_without_another_model_call(self):
  import importlib.util,json
  from types import SimpleNamespace
  from unittest.mock import Mock
  from autonomy_runtime import Runner
  hp=Path(__file__).resolve().parents[2]/'local-only/harness/harness.py';spec=importlib.util.spec_from_file_location('seed_finish_native',hp);native=importlib.util.module_from_spec(spec);spec.loader.exec_module(native)
  args=SimpleNamespace(workspace=str(self.root),task='재고 예시를 제조업 자재로',check='backend',model='fixture',llm_url='http://127.0.0.1:8099/v1',ponytail='off',max_rounds=8)
  runner=Runner(args,native.Harness);runner.h.evidence_path=self.root/'events.jsonl'
  messages=[{'content':json.dumps({'steps':[{'title':'Replace seed examples','kind':'change'}]})},{'content':None,'tool_calls':[{'id':'seed-call','type':'function','function':{'name':'update_seed_rows','arguments':json.dumps(self.args)}}]}]
  runner.h.llm.chat=Mock(side_effect=[{'choices':[{'message':m}]} for m in messages]);runner.h.checker.run_check=Mock(return_value={'success':True,'stdout':'','stderr':''})
  self.assertTrue(runner.run());self.assertEqual(runner.h.llm.chat.call_count,2);self.assertEqual(runner.h.checker.run_check.call_count,3);self.assertFalse(runner.cp.pending)  # baseline, patch, final completion check
