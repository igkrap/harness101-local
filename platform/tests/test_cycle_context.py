import sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-only/harness'))
from test_autonomy import native
from cycle_context import cycle_context as cycle

class AutomaticContextTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.screens=self.root/'frontend/src/screens';self.screens.mkdir(parents=True)
  for name,text in {'Home':'export function Home(){return <Text/>;}','Inventory':'export function Inventory(){return <Table data={rows}/>;}','Registration':'export function Registration(){return <form><TextInput/></form>;}'}.items():(self.screens/(name+'.tsx')).write_text(text)
  self.h=SimpleNamespace(workspace=native.WorkspaceManager(self.root),llm=Mock(),log_event=Mock())
  self.r=SimpleNamespace(h=self.h,modes=['frontend'],args=SimpleNamespace(task='기존 화면 조회 결과 그리드 없는 곳에 추가'),read=set(),messages=[],steps=[{'title':'change'}],step=0)
 def tearDown(self):
  if hasattr(self.h,'_code_intelligence'):self.h._code_intelligence.close()
  self.tmp.cleanup()
 def test_automatic_context_supplies_exact_target_reference_and_cached_diagnostics_without_llm(self):
  service=cycle.service(self.h)
  with patch.object(service,'run',return_value={'engine':'typescript-lsp','result':{'ready':True,'diagnostics':[]}}) as query:
   text,paths=cycle.snapshot(self.r);again,again_paths=cycle.snapshot(self.r)
  self.assertIn('frontend/src/screens/Registration.tsx',paths);self.assertIn('frontend/src/screens/Inventory.tsx',paths);self.assertIn((self.screens/'Registration.tsx').read_text(),text);self.assertEqual(paths,again_paths);self.assertEqual(query.call_count,1);self.h.llm.assert_not_called()
  self.assertEqual(service.duplicate_reads,0);self.assertEqual(self.h.log_event.call_count,1)
 def test_coverage_requires_grid_on_actual_business_screen(self):
  self.assertIn('Registration.tsx',cycle.coverage(self.r));self.assertNotIn('Home.tsx',cycle.coverage(self.r));(self.screens/'Registration.tsx').write_text('export function Registration(){return <form><TextInput/><Table/></form>;}');self.assertEqual(cycle.coverage(self.r),'')
 def test_layout_grid_request_does_not_apply_data_contract(self):
  self.r.args.task='CSS 그리드 레이아웃 변경';self.assertFalse(cycle.is_grid_task(self.r.args.task));self.assertEqual(cycle.coverage(self.r),'')
 def test_syntax_error_cannot_be_treated_as_complete_coverage(self):
  (self.screens/'Registration.tsx').write_text('export function Registration( {');self.assertTrue(cycle.coverage(self.r))

 def test_runner_hides_duplicate_whole_file_reads_but_restores_after_change(self):
  from runner_extensions import extend_runner
  class Base:
   def tools(self):return [{'function':{'name':n}} for n in ('read_file','inspect_code','apply_edits')]
  runner=extend_runner(Base)();runner.h=self.h;service=cycle.service(self.h);path='frontend/src/screens/Registration.tsx';service.read(path)
  for _ in range(3):service.read(path)
  self.assertNotIn('read_file',[t['function']['name']for t in runner.tools()]);self.assertIn('inspect_code',[t['function']['name']for t in runner.tools()])
  file=self.screens/'Registration.tsx';file.write_text(file.read_text()+'\n// actual edit\n');self.assertIn('read_file',[t['function']['name']for t in runner.tools()]);self.h.llm.assert_not_called()
 def test_truncated_symbol_cannot_grant_full_read_permission(self):
  from runner_extensions import extend_runner
  class Base:
   def apply(self,*a):return {'symbol':{'source':'partial','truncated':True}}
  runner=extend_runner(Base)();runner.read=set();runner.apply('inspect_code',{'path':'frontend/src/screens/Registration.tsx','action':'symbol'},{});self.assertEqual(runner.read,set())
