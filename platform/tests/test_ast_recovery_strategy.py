import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-only/harness'))
from test_autonomy import native
from ast_editing import editor
from ast_recovery import extend_recovery

class RecoveryStrategyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.rel='frontend/src/screens/Demo.tsx'
        self.source='// keep 한글 😀\nexport const meta={title:"demo"};export default function Demo(){return <main><form><input/><button>조회</button></form></main>;}'
        p=self.root/self.rel;p.parent.mkdir(parents=True);p.write_text(self.source)
        (self.root/'frontend/src/App.tsx').write_text('export default function App(){return <section><div>screen</div></section>;}')
        owner=self
        class Base:
            def __init__(self):
                self.args=SimpleNamespace(task='조회 영역과 그리드 수정');self.cp=SimpleNamespace(pending=False);self.messages=[{'role':'user','content':'large old history'}];self.read=set();self.used=0
                self.h=SimpleNamespace(workspace=native.WorkspaceManager(owner.root),log_event=Mock())
                self.requirement_gate=SimpleNamespace(context=lambda:json.dumps({'unresolved_checks':[{'id':'C1','reason':'height 265 instead of remaining height'}]}))
            def reject_repeat(self,*args):pass
            def apply(self,name,inputs,before=None):return editor(self.h).apply(inputs['path'],inputs.get('snapshot_id'),inputs['edits'])
            def ask(self,messages,tools):self.used+=1;owner.sent.append((messages,tools));owner.temperatures.append(float(os.environ.get('LOCAL_LLM_TEMPERATURE','1')));return owner.reply
        self.sent=[];self.temperatures=[];self.reply={'role':'assistant','content':'ordinary','tool_calls':[]};self.r=extend_recovery(Base)()
    def tearDown(self):
        svc=getattr(self.r.h,'_code_intelligence',None)
        if svc:svc.close()
        self.tmp.cleanup()
    def failed(self):
        for _ in range(2):self.r.reject_repeat('apply_ast_edits',{'path':self.rel,'edits':[]},'No-op edit')
    def response(self,path=None):
        path=path or self.rel;snap=editor(self.r.h).snapshot(path);node=next(n for n in snap['nodes'] if n['kind']=='JsxElement')
        code=node['source'].replace('>',' style={{minHeight:0}}>',1)
        self.reply={'content':json.dumps({'path':path,'edits':[{'node_id':node['id'],'code':code}]})}
    def test_two_errors_switch_to_smaller_packet_and_native_atomic_application(self):
        self.failed();self.response();reply=self.r.ask(self.r.messages,tools=[{'normal':'tools'}])
        messages,tools=self.sent[-1];self.assertEqual(tools,[])
        text=json.dumps(messages,ensure_ascii=False);self.assertIn('height 265',text);self.assertIn('frontend/src/App.tsx',text);self.assertIn('keep 한글',text);self.assertNotIn('large old history',text)
        fn=reply['tool_calls'][0]['function'];self.assertEqual(fn['name'],'apply_ast_edits');args=json.loads(fn['arguments']);result=self.r.apply(fn['name'],args)
        self.assertIn('minHeight:0',result['new_text']);self.assertEqual((self.root/self.rel).read_text(),self.source)
        self.reply={'content':'ordinary'};self.r.ask(self.r.messages,tools=['normal']);self.assertEqual(self.sent[-1][1],['normal'])
    def test_pending_and_unrelated_calls_use_normal_model_path(self):
        self.failed();self.r.cp.pending=True;self.r.ask(self.r.messages,tools=['normal']);self.assertEqual(self.sent[-1][1],['normal'])
        self.r.cp.pending=False;self.r.ask([{'content':'contract draft'}],tools=[]);self.assertEqual(self.sent[-1][0],[{'content':'contract draft'}])
    def test_bad_path_duplicate_keys_and_noop_cannot_mutate(self):
        self.failed()
        for content in ['{"path":"../../outside","edits":[]}','{"path":"x","path":"y","edits":[]}']:
            self.reply={'content':content};response=self.r.ask(self.r.messages,tools=['normal']);self.assertFalse(response.get('tool_calls'));self.assertEqual((self.root/self.rel).read_text(),self.source)
    def test_user_edit_after_focused_response_is_still_stale(self):
        self.failed();self.response();reply=self.r.ask(self.r.messages,tools=[]);fn=reply['tool_calls'][0]['function'];(self.root/self.rel).write_text(self.source+'\n// user change')
        with self.assertRaises(ValueError):self.r.apply(fn['name'],json.loads(fn['arguments']))
        self.assertIn('// user change',(self.root/self.rel).read_text())

    def test_valid_path_cannot_hide_duplicate_keys_or_truncate_nine_edits(self):
        self.failed();self.response();data=json.loads(self.reply['content'])
        duplicate=self.reply['content'].replace('{','{"path":'+json.dumps(self.rel)+',',1)
        self.reply={'content':duplicate};self.assertFalse(self.r.ask(self.r.messages,[])['tool_calls'])
        data['edits']*=9;self.reply={'content':json.dumps(data)};self.assertFalse(self.r.ask(self.r.messages,[])['tool_calls'])

    def test_recovery_does_not_read_sensitive_files_or_symlink_aliases(self):
        (self.root/'.env').write_text('DO_NOT_READ_SECRET')
        alias=self.root/'frontend/src/screens/Alias.tsx';alias.symlink_to(self.root/self.rel)
        for path in ('.env','frontend/src/screens/Alias.tsx'):
            self.r._ast_recovery_count=0
            for _ in range(2):self.r.reject_repeat('apply_ast_edits',{'path':path},'Invalid path')
            self.reply={'content':'{}'};self.r.ask(self.r.messages,[])
            text=json.dumps(self.sent[-1][0],ensure_ascii=False);self.assertNotIn('DO_NOT_READ_SECRET',text);self.assertNotIn('// keep',text)

    def test_full_grid_identity_survives_compaction_without_paired_opening_ids(self):
        import re
        source=(Path(__file__).parent/'fixtures/ast_dense_inventory.tsx').read_text()
        (self.root/'frontend/src/App.tsx').write_text((Path(__file__).parent/'fixtures/ast_parent_app.tsx').read_text())
        (self.root/self.rel).write_text(source);snap=editor(self.r.h).snapshot(self.rel)
        opening=next(n for n in snap['nodes']if n['kind']=='JsxOpeningElement' and 'data-testid="results-grid"' in n['source'])
        full=next(n for n in snap['nodes']if n['kind']=='JsxElement' and n['source'].startswith(opening['source']))
        self.failed();self.reply={'content':json.dumps({'path':self.rel,'edits':[{'node_id':full['id'],'code':full['source'].replace('minHeight: 0','minHeight: 1',1)}]})}
        response=self.r.ask(self.r.messages,[]);self.assertTrue(response['tool_calls'])
        self.assertEqual([m['role']for m in self.sent[-1][0]],['system','user'])
        text=self.sent[-1][0][-1]['content'];catalog=json.loads(re.search(r'Catalog: ([^\n]+)\nSource:',text)[1])
        self.assertFalse(any(n['id']==opening['id']for n in catalog))
        node=next(n for n in catalog if n['id']==full['id']);self.assertEqual(node['source'],full['source']);self.assertNotIn('source_preview',node)
        from context_budget import measure
        self.assertLess(measure(self.sent[-1][0],[],reserved=4096)['pressure'],1)
        fn=response['tool_calls'][0]['function'];result=self.r.apply(fn['name'],json.loads(fn['arguments']))
        self.assertEqual(result['new_text'],source.replace('minHeight: 0','minHeight: 1',1))

    def test_repeated_invalid_proposal_increases_variation_and_success_restores_baseline(self):
        self.failed();self.reply={'content':'{}'}
        with patch.dict(os.environ,{'LOCAL_LLM_TEMPERATURE':'0.2'}):
            self.assertFalse(self.r.ask(self.r.messages,[])['tool_calls']);self.response();reply=self.r.ask(self.r.messages,[])
            fn=reply['tool_calls'][0]['function'];self.r.apply(fn['name'],json.loads(fn['arguments']))
            self.reply={'content':'normal'};self.r.ask(self.r.messages,['normal'])
            self.assertEqual(self.temperatures,[0.4,0.5,0.2]);self.assertEqual(os.environ['LOCAL_LLM_TEMPERATURE'],'0.2')

    def test_recovery_sampling_is_bounded_and_does_not_lower_high_user_setting(self):
        self.failed();self.response()
        for baseline,expected in [('0.2',0.8),('1.2',1.2)]:
            self.r._ast_recovery_count=20
            with patch.dict(os.environ,{'LOCAL_LLM_TEMPERATURE':baseline}):
                self.r.ask(self.r.messages,[]);self.assertEqual(self.temperatures[-1],expected);self.assertEqual(os.environ['LOCAL_LLM_TEMPERATURE'],baseline)

    def test_sampling_mode_is_restored_even_on_model_error_or_stop(self):
        self.failed();self.response();base=self.r.__class__.__mro__[1]
        for error in (RuntimeError('generation failure'),KeyboardInterrupt()):
            with patch.dict(os.environ,{'LOCAL_LLM_TEMPERATURE':'0.2'}),patch.object(base,'ask',side_effect=error):
                with self.assertRaises(type(error)):self.r.ask(self.r.messages,[])
                self.assertEqual(os.environ['LOCAL_LLM_TEMPERATURE'],'0.2');self.assertFalse(self.r.cp.pending)
