import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-only/harness'))
from test_autonomy import native
from ast_editing import Editor
from code_intelligence import Service


class AstRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.app='frontend/src/App.tsx';self.inventory='frontend/src/screens/Inventory.tsx'
        for rel,name in [(self.app,'App'),(self.inventory,'Inventory')]:
            p=self.root/rel;p.parent.mkdir(parents=True,exist_ok=True)
            p.write_text(f'export default function {name}(){{return <main/>;}}')
        self.service=Service(native.WorkspaceManager(self.root));self.editor=Editor(self.service)

    def tearDown(self):self.service.close();self.temp.cleanup()

    def test_unchanged_rebuilds_do_not_evict_other_file_or_rerun_parser(self):
        import subprocess
        with patch('ast_editing.subprocess.run',wraps=subprocess.run) as parser:
            app=self.editor.snapshot(self.app)
            for _ in range(20):self.editor.snapshot(self.inventory)
            again=self.editor.snapshot(self.app)
        self.assertEqual(parser.call_count,2)
        self.assertEqual(app['snapshot_id'],again['snapshot_id'])
        self.assertEqual(app['nodes'],again['nodes'])
        self.assertTrue(again['cached'])
        self.assertEqual(len(self.editor._history),2)

    def test_cache_preserves_diagnostics_and_revalidates_source_hash(self):
        p=self.root/self.app;original=p.read_text();p.write_text('export const broken = ;')
        bad=self.editor.snapshot(self.app);again=self.editor.snapshot(self.app)
        self.assertTrue(bad['diagnostics'])
        self.assertEqual(again['diagnostics'],bad['diagnostics'])
        p.write_text(original);fixed=self.editor.snapshot(self.app)
        self.assertNotEqual(fixed['snapshot_id'],bad['snapshot_id'])
        self.assertFalse(fixed['diagnostics'])
        with self.assertRaisesRegex(ValueError,'stale'):
            self.editor.apply(self.app,bad['snapshot_id'],[{'node_id':bad['nodes'][0]['id'],'code':'const x=1;'}])

    def test_repeated_read_is_recoverable_and_tools_focus_on_mutation(self):
        from divide_guard import guard
        from frontend_tools import filter_tools
        events=[]
        child=SimpleNamespace(h=SimpleNamespace(workspace=native.WorkspaceManager(self.root),log_event=lambda k,d:events.append((k,d))),
            modes=['frontend'],args=SimpleNamespace(),initial_frontend_files={self.app,self.inventory})
        stage={'id':'layout','domain':'frontend','paths':[self.inventory]}
        for _ in range(12):guard(child,stage,'inspect_code',{'path':self.app,'action':'edit_ranges'})
        self.assertTrue(child._division_ast_focus)
        self.assertEqual(child._division_ast_paths,[self.app])
        self.assertEqual(len([e for e in events if e[0]=='autonomy.strategy']),1)
        tools=[{'type':'function','function':{'name':n,'parameters':{}}} for n in ('inspect_code','read_file','list_files','apply_ast_edits','write_file','finish')]
        names=[t['function']['name'] for t in filter_tools(child,tools)]
        self.assertEqual(names,['apply_ast_edits','write_file'])

    def test_failed_patch_context_retains_actual_catalogs_for_both_files(self):
        from divide_context import snapshot
        child=SimpleNamespace(h=SimpleNamespace(workspace=native.WorkspaceManager(self.root)),_division_ast_paths=[self.app])
        stage={'id':'layout','domain':'frontend','paths':[self.inventory],'references':[]}
        catalogs={rel:{'path':rel,'snapshot_id':rel,'nodes':[{'id':rel,'kind':'JsxOpeningElement','source':'x'*10000}]} for rel in (self.app,self.inventory)}
        with patch('ast_editing.editor',return_value=SimpleNamespace(snapshot=lambda rel:copy.deepcopy(catalogs[rel]))):
            text,reads=snapshot(child,stage)
        self.assertTrue({self.app,self.inventory}<=reads)
        for catalog in catalogs.values():self.assertIn(json.dumps(catalog,ensure_ascii=False),text)
        self.assertLessEqual(len(text),36000)
        self.assertLess(text.index('--- '+self.inventory),text.index('--- '+self.app))

    def test_real_stage_recovers_repeated_reads_then_accepts_scoped_mutation(self):
        from autonomy_runtime import Runner
        from divide_stage import run_stage
        from verification_gate import Gate
        from ast_editing import editor
        from test_autonomy import reply_tool
        owner=self;children=[];calls=[];events=[]
        (self.root/self.app).write_text('export default function App(){return <main data-state="old"></main>;}')
        args=SimpleNamespace(task='change state',workspace=str(self.root),check='frontend',max_rounds=10,
                             ponytail='off',llm_url='http://127.0.0.1:8099/v1',model='fixture')
        class LLM:
            def chat(self,messages,tools=None):
                calls.append(messages)
                child=children[-1];n=len(calls)
                if n<=4:
                    return reply_tool('inspect_code',path=owner.inventory if n==2 else owner.app,action='edit_ranges')
                if n==5:
                    child.fresh('failed patch')
                    text=json.dumps(child.messages)
                    owner.assertIn(owner.app,text);owner.assertIn(owner.inventory,text)
                    owner.assertTrue(child._division_ast_focus)
                    names={t['function']['name'] for t in child.tools()}
                    owner.assertTrue({'apply_ast_edits','write_file'}<=names)
                    owner.assertFalse({'inspect_code','read_file','list_files'} & names)
                    catalog=editor(child.h).snapshot(owner.app)
                    node=next(n for n in catalog['nodes'] if n['kind']=='JsxOpeningElement')
                    return reply_tool('apply_ast_edits',path=owner.app,snapshot_id=catalog['snapshot_id'],
                                      edits=[{'node_id':node['id'],'code':'<main data-state="new">'}])
                owner.assertFalse(child._division_ast_focus)
                return reply_tool('finish')
        class Harness(native.Harness):
            def __init__(self,args):
                super().__init__(args);self.llm=LLM();self.evidence_path=owner.root/'stage-events.jsonl'
                self.checker.run_check=lambda mode:{'success':True,'stdout':'fixture check','stderr':''}
            def log_event(self,kind,data):events.append((kind,data))
        class Base(Runner.__mro__[1]):
            def __init__(self,*args):super().__init__(*args);children.append(self)
        parent=Runner(args,Harness)
        stage={'id':'layout','title':'layout','instructions':'change state','domain':'frontend',
               'criterion_ids':['C1'],'paths':[self.inventory],'references':[],'depends_on':[]}
        parent.steps=[stage]
        gate=Gate(parent);parent.requirement_gate=gate
        gate.frozen_contract=json.dumps({'task':'change state','criteria':[{'id':'C1','check':{'op':'visible'}}]})
        gate.contract_hash='fixture';gate.artifact_dir=self.root/'proof'
        def probe(criteria):
            passed='data-state="new"' in (self.root/self.app).read_text()
            return {'success':passed,'results':[{'id':'C1','status':'passed' if passed else 'failed'}]}
        gate._probe=probe
        ok,proof=run_stage(parent,Base,Harness,stage,0,{},'')
        self.assertTrue(ok,parent.feedback)
        self.assertIn('data-state="new"',(self.root/self.app).read_text())
        self.assertFalse(children[-1]._division_ast_focus)
        self.assertEqual(proof['verified_results'][0]['status'],'passed')
        self.assertTrue(any(k=='autonomy.accepted' for k,_ in events))
        self.assertFalse(any(k=='autonomy.rollback' for k,_ in events))

    def test_exact_return_wrapper_extracts_only_authored_jsx_and_preserves_surrounding_bytes(self):
        p=self.root/self.app
        source='// 한글\r\nexport default function App(){return (<main><p>old</p></main>);}// tail'
        p.write_bytes(source.encode())
        catalog=self.editor.snapshot(self.app)
        node=next(n for n in catalog['nodes'] if n['kind']=='JsxElement' and n['source'].startswith('<main>'))
        jsx='<section data-state="new"><p>한글</p></section>'
        result=self.editor.apply(self.app,catalog['snapshot_id'],[{'node_id':node['id'],'code':'return (('+jsx+'));'}])
        self.assertEqual(result['new_text'],source.replace(node['source'],jsx))
        self.assertEqual(p.read_bytes(),source.encode())

    def test_return_normalization_never_accepts_extra_statements_or_scope_escape(self):
        p=self.root/self.app;source=p.read_bytes();catalog=self.editor.snapshot(self.app)
        node=next(n for n in catalog['nodes'] if n['kind']=='JsxSelfClosingElement')
        for code in ('return <section/>; const hidden=1;',
                     'export default function Escape(){return <section/>;}',
                     'return\n<section/>;',
                     'return (<section/>); } function Hidden(){',
                     'return <section/>; globalThis.changed=true;'):
            with self.subTest(code=code):
                with self.assertRaises(ValueError):self.editor.apply(self.app,catalog['snapshot_id'],[{'node_id':node['id'],'code':code}])
                self.assertEqual(p.read_bytes(),source)
        slot=next(n for n in catalog['nodes'] if n['kind']=='insert' and 'function prologue' in n['label'])
        with self.assertRaises(ValueError):self.editor.apply(self.app,catalog['snapshot_id'],[{'node_id':slot['id'],'code':'return <section/>;'}])

    def test_opening_tag_error_does_not_ask_for_a_closing_tag(self):
        p=self.root/self.app;p.write_text('export default function App(){return <main><p>old</p></main>;}')
        catalog=self.editor.snapshot(self.app)
        opening=next(n for n in catalog['nodes'] if n['kind']=='JsxOpeningElement' and n['source']=='<main>')
        with self.assertRaises(ValueError) as caught:
            self.editor.apply(self.app,catalog['snapshot_id'],[{'node_id':opening['id'],'code':'<main><aside/></main>'}])
        report=json.loads(str(caught.exception).split('AST_EDIT_FEEDBACK ',1)[1])
        self.assertIn('attributes',report['fix_hint'].lower())
        self.assertIn('never children',report['fix_hint'].lower())
        self.assertNotIn('end with its JSX closing tag',report['fix_hint'])
        full=next(n for n in catalog['nodes'] if n['kind']=='JsxElement' and n['source'].startswith('<main>'))
        candidate=self.editor.apply(self.app,catalog['snapshot_id'],[{'node_id':full['id'],'code':'<main><p>old</p><aside/></main>'}])
        self.assertIn('<aside/>',candidate['new_text'])

    def test_browser_check_waits_for_frontend_compile_success(self):
        from autonomy_runtime import Runner
        args=SimpleNamespace(task='layout',workspace=str(self.root),check='frontend|framework|backend',max_rounds=0,
                             ponytail='off',llm_url='http://127.0.0.1:8099/v1',model='fixture')
        runner=Runner(args,native.Harness);runner.h.evidence_path=self.root/'events.jsonl';calls=[]
        def check(mode):
            calls.append(mode)
            if mode=='framework':raise AssertionError('Browser must not run on invalid frontend')
            return {'success':mode!='frontend','stdout':'error TS2300: Duplicate identifier' if mode=='frontend' else 'ok','stderr':''}
        runner.h.checker.run_check=check
        ok,feedback=runner.verify()
        self.assertFalse(ok)
        self.assertEqual(calls,['frontend','backend'])
        self.assertIn('skipped',feedback)


if __name__=='__main__':unittest.main()
