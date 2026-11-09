import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-only/harness'))
from test_autonomy import native

class IntelligenceTests(unittest.TestCase):
 def setUp(self):
  from code_intelligence import Service
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);(self.root/'frontend/src/screens').mkdir(parents=True)
  self.file=self.root/'frontend/src/screens/Demo.tsx';self.file.write_text('// 😀 unicode\nexport function Demo(){return <Table data={[]} />;}\n')
  self.service=Service(native.WorkspaceManager(self.root));self.rel='frontend/src/screens/Demo.tsx'
 def tearDown(self):self.service.close();self.tmp.cleanup()
 def test_real_ast_symbols_jsx_and_exact_symbol(self):
  out=self.service.run({'path':self.rel,'action':'outline'});self.assertEqual(out['engine'],'typescript-ast');self.assertIn('Table',out['jsx_tags']);self.assertEqual(out['symbols'][0]['name'],'Demo')
  symbol=self.service.run({'path':self.rel,'action':'symbol','symbol':'Demo'})['symbol'];self.assertEqual(symbol['start_line'],2);self.assertIn('return <Table',symbol['source'])
 def test_reads_are_deduplicated_across_context_resets_and_change_refreshes(self):
  first=self.service.read(self.rel);self.assertIn('export function',first['content'])
  for _ in range(3):self.assertTrue(self.service.read(self.rel)['unchanged'])
  self.assertFalse(self.service.allow_reads());self.service.context();self.assertFalse(self.service.allow_reads())
  self.file.write_text('export function Updated(){return null;}');self.assertTrue(self.service.allow_reads());fresh=self.service.read(self.rel);self.assertIn('Updated',fresh['content']);self.assertNotEqual(first['sha256'],fresh['sha256'])
 def test_outline_detects_syntax_errors_without_claiming_clean(self):
  self.file.write_text('export function Demo( {');out=self.service.run({'path':self.rel,'action':'outline'});self.assertTrue(out['diagnostics'])
 def test_missing_symbol_and_unsupported_language_are_errors(self):
  self.assertIn('error',self.service.run({'path':self.rel,'action':'symbol','symbol':'Missing'}));self.assertIn('error',self.service.run({'path':'backend/Thing.java','action':'outline'}))
 def test_workspace_boundary_and_symlink(self):
  outside=Path(self.tmp.name).parent/'no-read.ts';link=self.root/'frontend/src/linked.ts';link.symlink_to('/etc/passwd')
  for rel in ('../secret.ts','/etc/passwd','frontend/src/linked.ts'):
   self.assertIn('error',self.service.run({'path':rel,'action':'outline'}))
 def test_screen_context_is_structure_without_full_source(self):
  text=self.service.context();self.assertIn('Demo',text);self.assertIn('Table',text);self.assertLess(len(text),6001)
 def test_novel_inspection_unlocks_discovery(self):
  self.service.read(self.rel)
  for _ in range(3):self.service.read(self.rel)
  self.assertFalse(self.service.allow_reads());self.service.run({'path':self.rel,'action':'outline'});self.assertTrue(self.service.allow_reads())

class RealLspTests(unittest.TestCase):
 def setUp(self):
  from lsp_client import Client
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);(self.root/'frontend/src').mkdir(parents=True)
  self.math=self.root/'frontend/src/math.ts';self.main=self.root/'frontend/src/main.ts';self.math.write_text('export function add(a: number,b: number){return a+b;}\n');self.main.write_text("import {add} from './math';\nconst answer = add(1,2);\nconst broken: number = 'wrong';\n")
  self.client=Client(self.root)
 def tearDown(self):self.client.close();self.tmp.cleanup()
 def test_actual_cross_file_definition_references_and_diagnostics(self):
  use='const answer = add(1,2);';pos=use.index('add')+1
  definition=self.client.query(self.main,'definition',2,pos);self.assertTrue(any('math.ts' in (d.get('uri')or d.get('targetUri',''))for d in definition))
  refs=self.client.query(self.main,'references',2,pos);self.assertGreaterEqual(len(refs),2)
  result=self.client.query(self.main,'diagnostics');self.assertTrue(result['ready']);self.assertTrue(any(d.get('code')==2322 for d in result['diagnostics']))
  self.main.write_text(self.main.read_text().replace("'wrong'",'3'));after=self.client.query(self.main,'diagnostics');self.assertTrue(after['ready']);self.assertFalse(any(d.get('code')==2322 for d in after['diagnostics']))
 def test_process_closes_and_coordinate_validation(self):
  with self.assertRaises(ValueError):self.client.query(self.main,'definition',0,1)
  self.client.close();self.assertIsNotNone(self.client.proc.poll())
