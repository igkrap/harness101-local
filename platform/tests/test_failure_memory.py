from pathlib import Path
import sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-only/harness'))
from failure_memory import FailureMemory
from edit_tools import insert_arguments
from unittest.mock import patch

class MemoryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.path='backend/src/test/java/Fixture.java';self.file=self.root/self.path;self.file.parent.mkdir(parents=True);self.before=b'import boot4.Valid;\nclass Fixture {}\n';self.after=b'import boot3.Missing;\nclass Fixture {}\n';self.file.write_bytes(self.before);self.m=FailureMemory(self.root)
 def tearDown(self):self.tmp.cleanup()
 def remember(self,error='COMPILATION ERROR cannot find symbol',compiled=True):self.m.record({self.path:{'before':self.before,'expected':self.after}},error,compiled)
 def test_persisted_rejections_block_same_candidate(self):
  self.remember();loaded=FailureMemory(self.root)
  with self.assertRaisesRegex(ValueError,'cannot find symbol'):loaded.guard(self.path,self.before,self.after,'edit_file')
  self.assertIn('REJECTED',loaded.context());self.assertIn('boot4.Valid',loaded.context())
 def test_failed_new_file_is_remembered_after_rollback_removal(self):
  path='frontend/src/screens/New.tsx';candidate=b'bad new code';self.m.record({path:{'before':None,'expected':candidate}},'error TS2322 unsupported prop',False)
  self.assertIn('error TS2322',self.m.context());self.assertIn(path,self.m.context())
  with self.assertRaises(ValueError):self.m.guard(path,None,candidate,'write_file')
  self.m.guard(path,None,b'valid replacement','write_file')
 def test_working_import_guard_accepts_addition(self):
  self.remember();added=self.before+b'// extra\n';self.m.guard(self.path,self.before,added,'edit_file')
  with self.assertRaises(ValueError):self.m.guard(self.path,self.before,b'import another.Missing;\nclass Fixture {}','edit_file')
 def test_rewrite_banned_but_small_addition_allowed(self):
  self.remember()
  with self.assertRaises(ValueError):self.m.guard(self.path,self.before,self.before+b'//new','write_file')
  self.m.guard(self.path,self.before,self.before+b'//new','edit_file')
 def test_changed_source_invalidates_old_facts(self):
  self.remember();changed=self.before+b'// user change';self.file.write_bytes(changed)
  self.m.guard(self.path,changed,self.after,'write_file');self.assertEqual(self.m.context(),'')
 def test_changed_dependencies_invalidate_old_facts(self):
  self.remember();pom=self.root/'backend/pom.xml';pom.write_text('new version');self.m.guard(self.path,self.before,self.after,'write_file');self.assertEqual(self.m.context(),'')
 def new_entity_failure(self):
  path='backend/src/main/java/items/Item.java';candidate=b'package items; class Item {}'
  file=self.root/path;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(candidate)
  self.m.record({path:{'before':None,'expected':candidate}},'Schema validation: missing table [items]',False)
  file.unlink()
  return path,candidate
 def test_target_candidate_is_excluded_from_dependency_fingerprint(self):
  path,candidate=self.new_entity_failure()
  with self.assertRaisesRegex(ValueError,'missing table'):self.m.guard(path,None,candidate,'write_file')
  self.assertIn('missing table',self.m.context())
 def test_new_migration_allows_identical_entity_and_invalidates_stale_context(self):
  path,candidate=self.new_entity_failure()
  migration=self.root/'backend/src/main/resources/db/migration/V6__items.sql'
  migration.parent.mkdir(parents=True);migration.write_text('CREATE TABLE items (id bigint);')
  self.m.guard(path,None,candidate,'write_file');self.assertEqual(self.m.context(),'')
  self.assertEqual(len(self.m.entries),1)
  migration.unlink()
  with self.assertRaisesRegex(ValueError,'missing table'):self.m.guard(path,None,candidate,'write_file')
 def test_changed_sibling_source_allows_revalidation(self):
  sibling=self.root/'backend/src/main/java/Dependency.java';sibling.parent.mkdir(parents=True);sibling.write_text('class Dependency {}')
  path,candidate=self.new_entity_failure()
  with self.assertRaises(ValueError):self.m.guard(path,None,candidate,'write_file')
  sibling.write_text('class Dependency { int value; }')
  self.m.guard(path,None,candidate,'write_file');self.assertEqual(self.m.context(),'')
 def test_build_outputs_and_evidence_do_not_invalidate_rejections(self):
  path,candidate=self.new_entity_failure()
  for relative in ('backend/target/generated.java','frontend/dist/index.js','harness_evidence.log'):
   file=self.root/relative;file.parent.mkdir(parents=True,exist_ok=True);file.write_text('unrelated runtime output')
  with self.assertRaises(ValueError):self.m.guard(path,None,candidate,'write_file')
 def test_proposed_migration_allows_retry_without_writing_or_discarding_history(self):
  path,candidate=self.new_entity_failure()
  migration='backend/src/main/resources/db/migration/V6__items.sql';sql=b'CREATE TABLE items (id bigint);'
  overrides={path:candidate,migration:sql}
  proposed=self.m._dependencies(path,overrides)
  self.m.guard(path,None,candidate,'write_file',dependency_overrides=overrides)
  self.assertFalse((self.root/migration).exists());self.assertEqual(len(self.m.entries),1)
  with self.assertRaises(ValueError):self.m.guard(path,None,candidate,'write_file')
  file=self.root/migration;file.parent.mkdir(parents=True);file.write_bytes(sql)
  self.assertEqual(proposed,self.m._dependencies(path))
 def test_target_only_override_does_not_bypass_the_same_failed_candidate(self):
  path,candidate=self.new_entity_failure()
  with self.assertRaisesRegex(ValueError,'missing table'):
   self.m.guard(path,None,candidate,'write_file',dependency_overrides={path:b'different target bytes'})
 def test_proposed_delete_matches_actual_dependency_removal(self):
  path,candidate=self.new_entity_failure()
  sibling=self.root/'backend/src/main/java/BadDependency.java';sibling.write_text('bad dependency')
  proposed=self.m._dependencies(path,{str(sibling.relative_to(self.root)):None})
  sibling.unlink()
  self.assertEqual(proposed,self.m._dependencies(path))
  with self.assertRaises(ValueError):self.m.guard(path,None,candidate,'write_file')
 def test_invalid_dependency_overrides_fail_before_candidate_permission(self):
  path,candidate=self.new_entity_failure()
  invalid=[[],{'../escape.java':b'x'},{'/absolute.java':b'x'},{'backend/src/../escape.java':b'x'},
           {'backend//src/x.java':b'x'},{'backend\\src\\x.java':b'x'},{'backend/src/x.java':'not bytes'},
           {3:b'x'},{'':b'x'}]
  for override in invalid:
   with self.subTest(override=override),self.assertRaises(ValueError):
    self.m.guard(path,None,candidate,'write_file',dependency_overrides=override)
 def test_dependency_override_cannot_follow_symlink(self):
  path,candidate=self.new_entity_failure()
  outside=self.root/'outside';outside.mkdir()
  (self.root/'backend/src/main/java/linked').symlink_to(outside,target_is_directory=True)
  with self.assertRaisesRegex(ValueError,'symlink'):
   self.m.guard(path,None,candidate,'write_file',dependency_overrides={'backend/src/main/java/linked/Sibling.java':b'x'})
  self.assertFalse((outside/'Sibling.java').exists())
 def test_legacy_records_without_dependency_identity_are_not_current_facts(self):
  path,candidate=self.new_entity_failure();self.m.entries[-1].pop('dependencies_sha')
  self.m.guard(path,None,candidate,'write_file');self.assertEqual(self.m.context(),'')
 def test_changed_runtime_policy_invalidates_rejected_candidate_without_deleting_history(self):
  policies=self.root/'runtime';policies.mkdir();policy=policies/'java_assertion_policy.py';policy.write_text('old guard')
  with patch('failure_memory.__file__',str(policies/'failure_memory.py')):
   self.remember(error='Existing Java assertions and test count must be preserved',compiled=False)
   with self.assertRaises(ValueError):self.m.guard(self.path,self.before,self.after,'insert_text')
   policy.write_text('new guard permits added assertions')
   self.m.guard(self.path,self.before,self.after,'insert_text')
   self.assertEqual(self.m.context(),'')
   self.assertEqual(len(self.m.entries),1)
 def test_failed_baseline_does_not_freeze_bad_imports(self):
  self.remember(compiled=False);self.assertEqual(self.m.entries[-1]['imports'],[])
 def test_path_escape_rejected(self):
  with self.assertRaises(ValueError):self.m.guard('../outside.java',b'a',b'b','edit_file')
 def test_memory_bounded_and_recent_failures_shown(self):
  for i in range(30):self.m.record({self.path:{'before':self.before,'expected':self.after+str(i).encode()}},'failure-'+str(i),False)
  loaded=FailureMemory(self.root);self.assertEqual(len(loaded.entries),24);self.assertIn('failure-29',loaded.context());self.assertNotIn('failure-6\n',loaded.context())

class InsertTests(unittest.TestCase):
 def test_anchor_retained_before_and_after(self):
  for position,expected in [('before','NEW\nANCHOR'),('after','ANCHORNEW\n')]:
   a=insert_arguments({'path':'x','anchor':'ANCHOR','text':'NEW\n','position':position});self.assertEqual(a['old_text'],'ANCHOR');self.assertEqual(a['new_text'],expected)
 def test_bad_arguments_rejected(self):
  for patch in ({'anchor':''},{'text':''},{'position':'replace'},{'text':None},{'anchor':'x'*801}):
   args={'path':'x','anchor':'a','text':'b','position':'after',**patch}
   with self.assertRaises(ValueError):insert_arguments(args)
if __name__=='__main__':unittest.main()

class BatchInsertTests(unittest.TestCase):
 def test_two_locations_are_one_retained_replacement(self):
  from batch_edits import batch_arguments
  current='import working.Valid;\nclass Fixture {}\n'
  args=batch_arguments({'path':'Fixture.java','blocks':[{'anchor':'import working.Valid;','text':'\nimport new.Annotation;','position':'after'},{'anchor':'class Fixture {}','text':'@Annotation\n','position':'before'}]},current)
  self.assertEqual(args['old_text'],current);self.assertIn('import working.Valid;\nimport new.Annotation;',args['new_text']);self.assertIn('@Annotation\nclass Fixture {}',args['new_text'])
 def test_missing_or_ambiguous_anchor_rejects_whole_batch(self):
  from batch_edits import batch_arguments
  for current,anchor in [('a\na','a'),('a','missing')]:
   with self.assertRaises(ValueError):batch_arguments({'path':'Fixture.java','blocks':[{'anchor':anchor,'text':'b','position':'after'}]},current)

class ExactPatchTests(unittest.TestCase):
 def test_import_and_usage_change_preserves_unrelated_code(self):
  from patch_edits import patch_arguments
  current="import {useState} from 'react';\nimport {Button} from 'ui';\nconst c=<Button/>;\n"
  a=patch_arguments({'path':'App.tsx','edits':[{'old_text':'{Button}','new_text':'{IconButton}'},{'old_text':'<Button/>','new_text':'<IconButton/>'}]},current)
  self.assertTrue(a['new_text'].startswith("import {useState} from 'react';"));self.assertIn('<IconButton/>',a['new_text']);self.assertEqual(a['old_text'],current)
 def test_ambiguous_or_empty_replacements_rejected(self):
  from patch_edits import patch_arguments
  for old,new in [('', 'x'),('a','a'),('a','b')]:
   with self.assertRaises(ValueError):patch_arguments({'path':'x','edits':[{'old_text':old,'new_text':new}]},'aa')
