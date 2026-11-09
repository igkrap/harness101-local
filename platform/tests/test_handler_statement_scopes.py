import sys,tempfile,unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parents[2]/'local-only/harness')]
from test_autonomy import native
from code_intelligence import Service
from ast_editing import Editor
from ast_candidate_buffer import CandidateBuffer

class HandlerStatementTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.rel='frontend/src/screens/Receipt.tsx';self.file=self.root/self.rel;self.file.parent.mkdir(parents=True)
  self.source='// 한글 😀\r\nconst outside = 1;\r\nexport default function Receipt(){\r\n const value=0;\r\n async function handleSubmit(id: string | null) {\r\n  if (id !== null) throw new Error("pending");\r\n  const code = "A";\r\n  console.log(code);\r\n }\r\n return <main>{value}</main>;\r\n}\r\n'
  self.file.write_bytes(self.source.encode());self.workspace=native.WorkspaceManager(self.root);self.service=Service(self.workspace);self.addCleanup(self.service.close);self.editor=Editor(self.service,allow_nested_handlers=True)
 def node(self,source,editor=None):
  editor=editor or self.editor;snap=editor.snapshot(self.rel);node=next(n for n in snap['nodes'] if n['source']==source);return snap,node
 def replace(self,source,code,editor=None):
  editor=editor or self.editor;snap,node=self.node(source,editor);return editor.apply(self.rel,snap['snapshot_id'],[{'node_id':node['id'],'code':code}])
 def test_if_to_variable_and_sequence_preserve_exact_surrounding_source(self):
  old='if (id !== null) throw new Error("pending");'
  for new in ['const isEditing = id !== null;','const isEditing = id !== null;\nif (isEditing) console.log(id);']:
   result=self.replace(old,new);self.assertEqual(result['new_text'],self.source.replace(old,new));self.assertEqual(self.file.read_bytes(),self.source.encode())
 def test_variable_can_become_control_flow(self):
  result=self.replace('const code = "A";','if (id === null) return;');self.assertIn('if (id === null) return;',result['new_text'])
 def test_flags_are_only_on_local_handler_statement_lists(self):
  snap=self.editor.snapshot(self.rel);tagged=[n for n in snap['nodes'] if n.get('handler_statement_scope')];self.assertTrue(tagged)
  self.assertTrue(all(n['kind'] not in ('FunctionDeclaration','SourceFile','ClassDeclaration','Block') and 'handleSubmit' in n['label'] for n in tagged))
  self.assertFalse(next(n for n in snap['nodes'] if n['source']=='const outside = 1;').get('handler_statement_scope'))
  self.assertFalse(next(n for n in snap['nodes'] if n['source']=='const value=0;').get('handler_statement_scope'))
 def test_legacy_and_component_nodes_keep_old_kind_rule(self):
  legacy=Editor(self.service)
  for editor,old,new in [(legacy,'if (id !== null) throw new Error("pending");','const editing=true;'),(self.editor,'const value=0;','if (true) console.log(1);'),(self.editor,'const outside = 1;','if (true) console.log(1);')]:
   with self.subTest(old=old):
    with self.assertRaises(ValueError):self.replace(old,new,editor)
 def test_local_scope_rejects_module_jsx_invalid_and_oversized_code(self):
  for bad in ['import x from "x";','export const x=1;','export default function Screen(){return null;}','const view = <div/>;','const x = ;','const x="'+('a'*3100)+'";']:
   with self.subTest(bad=bad[:40]):
    with self.assertRaises(ValueError):self.replace('const code = "A";',bad)
    self.assertEqual(self.file.read_bytes(),self.source.encode())
 def test_stale_snapshot_and_forged_flags_still_rejected(self):
  snap,node=self.node('const code = "A";')
  with self.assertRaises(ValueError):self.editor.apply(self.rel,snap['snapshot_id'],[{'node_id':node['id'],'code':'const code="B";','handler_statement_scope':True}])
  self.file.write_text(self.source+'// drift')
  with self.assertRaisesRegex(ValueError,'stale'):self.editor.apply(self.rel,snap['snapshot_id'],[{'node_id':node['id'],'code':'const other=2;'}])
 def test_candidate_inherits_scope_and_strict_variable_normalization_accepts_control_flow(self):
  candidate=CandidateBuffer(self.workspace,self.editor,self.rel,self.source);self.addCleanup(candidate.close);self.assertTrue(candidate.editor.allow_nested_handlers)
  snap=candidate.snapshot();node=next(n for n in snap['nodes'] if n['source']=='const code = "A";');self.assertTrue(node.get('handler_statement_scope'))
  candidate.prepare(snap['snapshot_id'],[{'node_id':node['id'],'code':'if (id === null) return;'}]);self.assertIn('if (id === null) return;',candidate.source);self.assertEqual(self.file.read_bytes(),self.source.encode())
 def test_large_handler_still_has_bounded_local_statement_scope(self):
  self.file.write_text(self.source.replace('  const code = "A";','  /*'+'x'*3100+'*/\n  const code = "A";'))
  snap,node=self.node('const code = "A";');self.assertTrue(node.get('handler_statement_scope'));result=self.editor.apply(self.rel,snap['snapshot_id'],[{'node_id':node['id'],'code':'if (id === null) return;'}]);self.assertIn('if (id === null) return;',result['new_text'])
if __name__=='__main__':unittest.main()
