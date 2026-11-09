from pathlib import Path
import sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-only/harness'))
from project_context import project_files,project_context,missing_path_message,new_screen_error

class ProjectContextTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  self.controller='backend/src/main/java/example/ActualController.java';self.write(self.controller,'@RequestMapping("/api/actual") class ActualController { @PostMapping void create() {} } record ActualRequest(String name) {}')
  self.home='frontend/src/screens/Home.tsx';self.write(self.home,'export const meta = {title:"홈"}; export default function Home() {}')
 def tearDown(self):self.tmp.cleanup()
 def write(self,name,text):
  p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text);return p
 def test_actual_paths_and_api_survive_context(self):
  self.assertIn(self.controller,project_files(self.root));context=project_context(self.root);self.assertIn(self.controller,context);self.assertIn('/api/actual',context);self.assertIn('ActualRequest(String name)',context);self.assertLessEqual(len(context),6500)
 def test_long_paths_are_preserved_and_file_count_is_bounded(self):
  path='backend/src/main/java/'+('longpackage/'*8)+'OtherController.java';self.write(path,'class OtherController {}');self.assertIn(path,project_files(self.root))
  for i in range(100):self.write('frontend/src/screens/Screen'+str(i)+'.tsx','')
  self.assertLessEqual(len(project_files(self.root)),80)
 def test_missing_path_returns_existing_matching_file(self):
  message=missing_path_message(self.root,'backend/src/main/java/invented/ActualController.java');self.assertIn('does not exist',message);self.assertIn(self.controller,message)
 def test_existing_screen_edit_does_not_satisfy_new_screen_request(self):
  self.assertTrue(new_screen_error(self.root,'품목 등록 기능도 화면 하나 구현해줘',{self.home}));self.write(self.home,'export const meta={title:"품목 등록"}; export default function Home() {}');self.assertTrue(new_screen_error(self.root,'품목 등록 기능도 화면 하나 구현해줘',{self.home}))
 def test_new_screen_needs_registry_exports(self):
  p=self.write('frontend/src/screens/Registration.tsx','export default function Registration() {}');self.assertTrue(new_screen_error(self.root,'화면 하나 구현해줘',{self.home}));p.write_text('export const meta={title:"등록"}; export default function Registration() {}');self.assertEqual(new_screen_error(self.root,'화면 하나 구현해줘',{self.home}),'')
 def test_existing_feature_fix_needs_no_extra_screen(self):
  self.assertEqual(new_screen_error(self.root,'탭 닫기 버튼을 수정해줘',{self.home}),'')

 def test_adding_grid_to_existing_screens_does_not_require_new_file(self):
  self.assertEqual(new_screen_error(self.root,'기존 화면들에서 조회 결과 그리드가 없는 곳은 추가해줘',{self.home}),'')
  self.assertEqual(new_screen_error(self.root,'기존 화면에 조회 버튼을 추가해줘',{self.home}),'')

 def test_explicit_new_screen_requests_still_require_new_file(self):
  for task in ('새 화면 만들어줘','새로운 화면을 만들어줘','화면을 추가해줘','화면 추가해줘','별도 화면 구현','new screen'):
   self.assertTrue(new_screen_error(self.root,task,{self.home}),task)

 def test_sql_resources_are_discoverable_in_facts_and_missing_file_feedback(self):
  rel='backend/src/main/resources/db/migration/V1__inventory.sql';self.write(rel,'CREATE TABLE inventory(id BIGINT);')
  self.assertIn(rel,project_files(self.root));self.assertIn(rel,project_context(self.root));self.assertIn(rel,missing_path_message(self.root,'backend/src/main/resources/data.sql'))
 def test_test_java_is_suggested_instead_of_invented_main_java(self):
  rel='backend/src/test/java/example/InventoryIntegrationTest.java';self.write(rel,'class InventoryIntegrationTest {}')
  self.assertIn(rel,project_files(self.root));self.assertIn(rel,missing_path_message(self.root,'backend/src/main/java/example/InventoryIntegrationTest.java'))
