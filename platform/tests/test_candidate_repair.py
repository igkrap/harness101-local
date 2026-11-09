import copy
import json
import pathlib
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]/'local-only/harness'))
from test_autonomy import native,reply_tool
from ast_editing import editor
from lint_frontend import run_lint
from completion_fixture import EditorTestGate

class CandidateRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.temp.name);self.rel='frontend/src/App.tsx';self.file=self.root/self.rel;self.file.parent.mkdir(parents=True)
        self.original="export default function App(){const save=()=>console.log('save');return (<main><form onSubmit={save}><input aria-label=\"이름\"/><button type=\"submit\">추가</button></form><aside>empty</aside></main>);}\n"
        self.file.write_text(self.original);self.events=[];self.checks=[];self.model_calls=0;owner=self
        self.args=SimpleNamespace(task='Separate query and registration',workspace=str(self.root),check='frontend',max_rounds=8,ponytail='off',llm_url='http://127.0.0.1:8099/v1',model='fixture')
        class LLM:
            def chat(self,messages,tools=None):return owner.respond(messages,tools)
        class Harness(native.Harness):
            def __init__(self,args):
                super().__init__(args);self.llm=LLM();self.evidence_path=owner.root/'events.jsonl'
                def check(mode):
                    result=run_lint(self.checker);owner.checks.append(result);return result
                self.checker.run_check=check
            def log_event(self,kind,data):owner.events.append((kind,data))
        from autonomy_runtime import Runner
        from candidate_repair import extend_candidate
        base=next(c for c in Runner.__mro__ if c.__module__=='context_budget')
        self.Runner=extend_candidate(base);self.Harness=Harness
        gate=patch('completion_runner.Gate',EditorTestGate);gate.start();self.addCleanup(gate.stop)
        self.runner=self.Runner(self.args,Harness)
    def tearDown(self):
        service=getattr(self.runner.h,'_code_intelligence',None)
        if service:service.close()
        self.temp.cleanup()
    def proposal(self):
        snap=editor(self.runner.h).snapshot(self.rel)
        self.aside=next(n for n in snap['nodes'] if n['kind']=='JsxElement' and n['source'].startswith('<aside>'))
        form=next(n for n in snap['nodes'] if n['kind']=='JsxElement' and n['source'].startswith('<form '))
        slot=next(n for n in snap['nodes'] if n['kind']=='insert' and 'function prologue' in n['label'])
        return {'path':self.rel,'snapshot_id':snap['snapshot_id'],'edits':[{'node_id':slot['id'],'code':"const search=()=>console.log('query');"},{'node_id':form['id'],'code':'<form onSubmit={search}><input aria-label="조회 조건"/><button type="submit">조회</button></form>'}]}
    def repair(self):return {'changes':[{'node_id':self.aside['id'],'code':'<aside><form onSubmit={save}><input aria-label="이름"/><button type="submit">추가</button></form></aside>'}],'remove':[]}
    def respond(self,messages,tools):
        self.model_calls+=1;names={t['function']['name'] for t in tools}
        if self.model_calls==1:return reply_tool('apply_ast_edits',**self.proposal())
        if self.model_calls==2:
            self.assertEqual(names,{'replace_ast_fragments'})
            self.assertEqual(self.file.read_text(),self.original)
            self.assertIn('search',json.dumps(messages))
            return {'choices':[{'message':{'role':'assistant','content':json.dumps(self.repair())}}]}
        self.assertIn('apply_ast_edits',names)
        return reply_tool('finish')
    def test_failed_atomic_batch_keeps_handler_and_jsx_while_repair_adds_missing_form(self):
        self.assertTrue(self.runner.run(),self.runner.feedback)
        source=self.file.read_text();self.assertIn('const search=',source);self.assertIn('onSubmit={search}',source);self.assertIn('onSubmit={save}',source)
        self.assertTrue(any(not r['success'] and 'save' in r['stdout'] for r in self.checks))
        self.assertTrue(self.checks[-1]['success']);self.assertEqual(self.model_calls,2)
        self.assertFalse(self.runner.cp.pending);self.assertFalse(self.runner._failed_ast_candidate)
    def test_stale_base_is_never_overwritten_and_discard_restores_tools(self):
        self.runner.apply('inspect_code',{'path':self.rel,'action':'edit_ranges'}, {})
        self.runner.apply('apply_ast_edits',self.proposal(),{})
        ok,_=self.runner.verify();self.assertFalse(ok);self.runner.cp.rollback()
        changed=self.original+'// user edit\n';self.file.write_text(changed)
        with self.assertRaisesRegex(ValueError,'stale|Snapshot'):
            self.runner.apply('repair_ast_candidate',self.repair(),{})
        self.assertEqual(self.file.read_text(),changed);self.assertFalse(self.runner.cp.pending)
        self.runner.apply('discard_ast_candidate',{},{});self.assertFalse(self.runner._failed_ast_candidate)
        self.assertIn('read_file',{t['function']['name'] for t in self.runner.tools()})
    def test_context_refresh_does_not_duplicate_retained_proposal(self):
        self.runner.apply('inspect_code',{'path':self.rel,'action':'edit_ranges'}, {})
        proposal=self.proposal();self.runner.apply('apply_ast_edits',proposal,{})
        ok,_=self.runner.verify();self.assertFalse(ok);self.runner.cp.rollback()
        self.runner.steps=[{'title':'Recovery fixture','kind':'change'}]
        self.runner.messages=[{'role':'user','content':'original request'},
            {'role':'assistant','content':None,'tool_calls':reply_tool('apply_ast_edits',**proposal)['choices'][0]['message']['tool_calls']},
            {'role':'tool','tool_call_id':'tool-apply_ast_edits','content':json.dumps({'status':'applied'})}]
        sizes=[]
        for _ in range(6):
            self.runner.fresh('failed patch')
            text=json.dumps(self.runner.messages)
            self.assertEqual(text.count('FAILED ATOMIC AST PROPOSAL'),1)
            sizes.append(len(text))
        self.assertLessEqual(max(sizes)-min(sizes),1000)

    def test_revise_rejects_paths_duplicate_updates_and_unknown_removals(self):
        from candidate_patch import revise
        proposal={'path':self.rel,'snapshot_id':'id','source_hash':'hash','edits':[{'node_id':'a','code':'keep'}]}
        good=revise(proposal,[{'node_id':'b','code':'new'}],[]);self.assertEqual(good['edits'][0],proposal['edits'][0]);self.assertEqual(len(good['edits']),2)
        for changes,remove in [([{'path':'../escape','node_id':'a','code':'bad'}],[]),([{'node_id':'a','code':'x'},{'node_id':'a','code':'y'}],[]),([],['unknown'])]:
            with self.assertRaises(ValueError):revise(proposal,changes,remove)
        self.assertEqual(proposal['edits'],[{'node_id':'a','code':'keep'}])

if __name__=='__main__':unittest.main()
