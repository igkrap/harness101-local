"""Exercise real TSX indexing and the invalid scopes observed in live runs."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-only/harness'))
from test_autonomy import native
from ast_editing import Editor
from code_intelligence import Service


class AstScopeRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.rel='frontend/src/screens/Demo.tsx'
        self.file=self.root/self.rel
        self.file.parent.mkdir(parents=True)
        self.source="// 한글 😀\r\nimport {useState} from 'react';\r\nexport const meta={title:'화면'};\r\nexport default function Demo(){\r\n const [count,setCount]=useState(0);\r\n return (<form><h1>등록</h1><button onClick={()=>setCount(count+1)}>{count}</button></form>);\r\n}\r\n"
        self.file.write_bytes(self.source.encode())
        self.service=Service(native.WorkspaceManager(self.root))
        self.editor=Editor(self.service)

    def tearDown(self):
        self.service.close();self.temp.cleanup()

    def snapshot(self):return self.editor.snapshot(self.rel)

    def test_dense_screen_indexes_table_for_a_precise_attribute_edit(self):
        self.source = (Path(__file__).parent / 'fixtures/ast_dense_inventory.tsx').read_text()
        self.file.write_text(self.source)
        snap = self.snapshot()
        table = next(n for n in snap['nodes'] if n['kind'] == 'JsxSelfClosingElement' and n['source'].startswith('<Table '))
        replacement = table['source'].replace('idKey="id"', 'idKey="id" aria-label="재고 목록"')
        self.assertNotEqual(replacement, table['source'])
        result = self.editor.apply(self.rel, snap['snapshot_id'], [{'node_id': table['id'], 'code': replacement}])
        self.assertEqual(result['new_text'], self.source.replace(table['source'], replacement, 1))
        self.assertEqual(self.file.read_text(), self.source)
        self.assertTrue(any(n['source'].startswith('<TextInput label="단가"') for n in snap['nodes']))
        self.assertLessEqual(sum(len(n['source']) for n in snap['nodes']), 32000)

    def slot(self,snap,phrase):return next(n for n in snap['nodes'] if n['kind']=='insert' and phrase in n['label'])

    def test_metadata_and_root_layout_have_distinct_owners_roles_and_lines(self):
        snap=self.snapshot()
        meta=next(n for n in snap['nodes'] if n['source']=="export const meta={title:'화면'};")
        self.assertEqual(meta['kind'],'VariableStatement')
        self.assertIn('meta',meta['label'].lower())
        root=next(n for n in snap['nodes'] if n['kind']=='JsxElement' and n['source'].startswith('<form>'))
        self.assertIn('Demo',root['label'])
        self.assertIn('return',root['label'].lower())
        self.assertIn('form',root['label'])
        self.assertRegex(root['label'],r'\b6\b')

    def test_large_jsx_keeps_small_opening_tag_and_preserves_every_other_byte(self):
        self.source=self.source.replace('<h1>등록</h1>','<h1>'+('긴 내용 😀 '*500)+'</h1>')
        self.file.write_bytes(self.source.encode())
        snap=self.snapshot()
        opening=next(n for n in snap['nodes'] if n['kind']=='JsxOpeningElement' and n['source']=='<form>')
        self.assertIn('return',opening['label'].lower())
        result=self.editor.apply(self.rel,snap['snapshot_id'],[{'node_id':opening['id'],'code':'<form data-testid="main-content-area">'}])
        self.assertEqual(result['new_text'].encode(),self.source.replace('<form>','<form data-testid="main-content-area">',1).encode())
        self.assertEqual(self.file.read_bytes(),self.source.encode())

    def test_opening_tag_cannot_smuggle_children_siblings_or_statements(self):
        snap=self.snapshot()
        opening=next(n for n in snap['nodes'] if n['kind']=='JsxOpeningElement' and n['source']=='<form>')
        for code in ('<form><aside/>','<form/>','<form></form><aside>','<form>);const hacked=1;const x=(<form>'):
            with self.subTest(code=code),self.assertRaises(ValueError):
                self.editor.apply(self.rel,snap['snapshot_id'],[{'node_id':opening['id'],'code':code}])
        self.assertEqual(self.file.read_bytes(),self.source.encode())

    def test_opening_tag_stays_available_when_large_body_statements_fill_source_budget(self):
        locals_code='\n'.join(f'const block{i}="'+('x'*2500)+'";' for i in range(5))
        self.source='export default function Demo(){'+locals_code+'return (<form><h1>'+('내용 '*1000)+'</h1></form>);}'
        self.file.write_bytes(self.source.encode());snap=self.snapshot()
        self.assertTrue(any(n['kind']=='JsxOpeningElement' and n['source']=='<form>' for n in snap['nodes']))
        self.assertLessEqual(sum(len(n['source']) for n in snap['nodes']),32000)

    def test_fragment_return_is_exposed_as_a_layout_target(self):
        self.source='export default function Demo(){return (<><h1>등록</h1><p>설명</p></>);}'
        self.file.write_bytes(self.source.encode());snap=self.snapshot()
        fragment=next(n for n in snap['nodes'] if n['kind']=='JsxFragment')
        self.assertIn('return',fragment['label'].lower())
        result=self.editor.apply(self.rel,snap['snapshot_id'],[{'node_id':fragment['id'],'code':'<main><h1>등록</h1><p>설명</p></main>'}])
        self.assertIn('return (<main>',result['new_text'])

    def test_structural_jsx_over_1500_chars_has_complete_root_and_both_regions(self):
        left='<section data-testid="left"><h1>'+('내용 😀 '*400)+'</h1></section>'
        right='<aside data-testid="right">등록</aside>'
        root='<main>'+left+right+'</main>'
        self.source="// 한글 😀\r\nexport default function Demo(){const caption='stable'; return ("+root+");}\r\n"
        self.file.write_bytes(self.source.encode());snap=self.snapshot()
        full=next(n for n in snap['nodes'] if n['kind']=='JsxElement' and n['source']==left)
        self.assertGreater(len(full['source']),1500)
        self.assertTrue(any(n['source']==root and n['kind']=='JsxElement' for n in snap['nodes']))
        self.assertTrue(any(n['source']==right and n['kind']=='JsxElement' for n in snap['nodes']))
        opening=next(n for n in snap['nodes'] if n['kind']=='JsxOpeningElement' and n['source']=='<section data-testid="left">')
        self.assertIn(full['id'],opening['label'])
        replacement=left.replace('<section data-testid="left">','<section data-testid="left" style={{minWidth:0}}>')
        with self.assertRaises(ValueError) as caught:self.editor.apply(self.rel,snap['snapshot_id'],[{'node_id':opening['id'],'code':replacement}])
        self.assertIn(full['id'],str(caught.exception))
        result=self.editor.apply(self.rel,snap['snapshot_id'],[{'node_id':full['id'],'code':replacement}])
        self.assertEqual(result['new_text'].encode(),self.source.replace(left,replacement,1).encode())
        self.assertEqual(self.file.read_bytes(),self.source.encode())
        self.assertLessEqual(sum(len(n['source']) for n in snap['nodes']),32000)
        self.assertFalse({'SourceFile','FunctionDeclaration','Block'} & {n['kind'] for n in snap['nodes']})

    def test_render_root_is_reserved_before_large_body_statements_fill_budget(self):
        locals_code='\n'.join('const block'+str(i)+'="'+('x'*2200)+'";' for i in range(6))
        root='<main><h1>'+('내용 '*800)+'</h1></main>'
        self.source='export default function Demo(){'+locals_code+'return ('+root+');}'
        self.file.write_text(self.source);snap=self.snapshot()
        self.assertTrue(any(n['kind']=='JsxElement' and n['source']==root for n in snap['nodes']))
        self.assertLessEqual(sum(len(n['source']) for n in snap['nodes']),32000)

    def test_live_dense_screen_keeps_each_named_region_and_matching_opening_hint(self):
        self.source=(Path(__file__).parent/'fixtures/ast_dense_inventory.tsx').read_text()
        self.file.write_text(self.source);snap=self.snapshot()
        for name in ('main-content-area','query-panel','results-grid','side-panel'):
            marker='data-testid="'+name+'"'
            opening=next(n for n in snap['nodes'] if n['kind']=='JsxOpeningElement' and marker in n['source'])
            full=next(n for n in snap['nodes'] if n['kind']=='JsxElement' and n['source'].startswith(opening['source']))
            self.assertIn('complete JSX node '+full['id'],opening['label'])
            result=self.editor.apply(self.rel,snap['snapshot_id'],[{'node_id':full['id'],'code':full['source'].replace(marker,marker+' aria-label="영역"',1)}])
            self.assertEqual(result['new_text'],self.source.replace(marker,marker+' aria-label="영역"',1))
        self.assertLessEqual(sum(len(n['source'])for n in snap['nodes']),32000)

    def test_function_slot_rejects_the_observed_whole_file_proposal(self):
        snap=self.snapshot();slot=self.slot(snap,'function prologue')
        for code in (
            'export interface InventoryItem {id:number}\nexport default function Inventory(){return <main/>;}',
            "import {Text} from 'ui';\nconst item=1;",
            '}\nexport default function Escape(){return <main/>;}\nfunction Extra(){',
            'if(true){export const nested=1;}',
            'return <main/>;',
        ):
            with self.subTest(code=code),self.assertRaises(ValueError) as caught:
                self.editor.apply(self.rel,snap['snapshot_id'],[{'node_id':slot['id'],'code':code}])
            detail=json.loads(str(caught.exception).split('AST_EDIT_FEEDBACK ',1)[1])
            self.assertFalse(detail['applied'])
            self.assertTrue(detail['layout_targets'])
            self.assertIn('scope_rule',detail)
        self.assertEqual(self.file.read_bytes(),self.source.encode())

    def test_local_statements_and_module_helpers_still_work(self):
        snap=self.snapshot();slot=self.slot(snap,'function prologue')
        code='const ready=true;\ninterface Local {id:number}\nfunction format(v:number){return String(v);}'
        self.assertIn(code,self.editor.apply(self.rel,snap['snapshot_id'],[{'node_id':slot['id'],'code':code}])['new_text'])
        after=self.slot(snap,'after imports')
        helper="import {Text} from 'ui';\nexport interface Extra {id:number}"
        self.assertIn(helper,self.editor.apply(self.rel,snap['snapshot_id'],[{'node_id':after['id'],'code':helper}])['new_text'])
        with self.assertRaises(ValueError):
            self.editor.apply(self.rel,snap['snapshot_id'],[{'node_id':after['id'],'code':'export default function Duplicate(){return null;}'}])

    def test_bad_multi_edit_batch_never_starts_a_file_transaction(self):
        from autonomy_runtime import Runner
        args=SimpleNamespace(task='레이아웃 변경',workspace=str(self.root),check='frontend',max_rounds=0,
                             ponytail='off',llm_url='http://127.0.0.1:8099/v1',model='fixture')
        runner=Runner(args,native.Harness);runner.h.evidence_path=self.root/'evidence.jsonl'
        try:
            snap=runner.apply('inspect_code',{'path':self.rel,'action':'edit_ranges'}, {})
            imp=next(n for n in snap['nodes'] if n['kind']=='ImportDeclaration')
            slot=self.slot(snap,'function prologue')
            with self.assertRaises(ValueError):
                runner.apply('apply_ast_edits',{'path':self.rel,'snapshot_id':snap['snapshot_id'],'edits':[
                    {'node_id':imp['id'],'code':"import {useState,useEffect} from 'react';"},
                    {'node_id':slot['id'],'code':'export default function Inventory(){return <main/>;}'}]}, {})
            self.assertFalse(runner.cp.pending)
            self.assertEqual(self.file.read_bytes(),self.source.encode())
        finally:
            if getattr(runner.h,'_code_intelligence',None):runner.h._code_intelligence.close()

    def test_default_frontend_prompt_does_not_recommend_blocked_raw_edits(self):
        from autonomy_runtime import Runner
        args=SimpleNamespace(task='레이아웃 변경',workspace=str(self.root),check='frontend',max_rounds=0,
                             ponytail='off',llm_url='http://127.0.0.1:8099/v1',model='fixture')
        runner=Runner(args,native.Harness);runner.h.evidence_path=self.root/'evidence.jsonl'
        runner.steps=[{'title':args.task,'kind':'change'}]
        try:
            runner.fresh();system=runner.messages[0]['content']
            self.assertNotIn('For an existing file, prefer apply_edits',system)
            self.assertNotIn('For additive changes use insert_text',system)
            self.assertIn('return JSX',system)
        finally:
            if getattr(runner.h,'_code_intelligence',None):runner.h._code_intelligence.close()


if __name__=='__main__':unittest.main()
