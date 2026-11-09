from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import test_autonomy
from ast_editing import editor
from candidate_targets import order_candidate_nodes


class CandidateTargetTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.rel='frontend/src/Demo.tsx';self.file=self.root/self.rel
        self.file.parent.mkdir(parents=True)
        self.source='export default function Demo(){return <main data-testid="root"><aside data-testid="right"><form><input/></form></aside><article data-testid="left"/></main>;}'
        self.file.write_text(self.source)
        self.r=SimpleNamespace(h=SimpleNamespace(workspace=test_autonomy.native.WorkspaceManager(self.root)),requirement_gate=SimpleNamespace(contract={'criteria':[{'id':'C1','check':{'selector':"[data-testid='root']"}},{'id':'C5','check':{'selector':"[data-testid='right']"}}]},last_report={'results':[{'id':'C1','status':'passed'},{'id':'C5','status':'failed'}]}))
        self.ed=editor(self.r.h);self.snap=self.ed.snapshot(self.rel)
        self.catalog=[n for n in self.snap['nodes'] if not(n['kind']=='JsxOpeningElement' and 'complete JSX node 'in n['label'])]
        self.proposal=dict(path=self.rel,snapshot_id=self.snap['snapshot_id'],source_hash=self.snap['source_hash'],edits=[])
        self.aside=next(n for n in self.catalog if n['kind']=='JsxElement' and n['source'].startswith('<aside'))
        self.main=next(n for n in self.catalog if n['kind']=='JsxElement' and n['source'].startswith('<main'))
        self.slot=next(n for n in self.catalog if n['kind']=='insert')

    def tearDown(self):
        self.r.h._code_intelligence.close();self.tmp.cleanup()

    def test_actual_selector_matches_own_opening_not_ancestor_containing_descendant(self):
        ordered,hint=order_candidate_nodes(self.r,self.proposal,self.catalog,[])
        self.assertEqual(ordered[0]['id'],self.aside['id'])
        self.assertIn(self.aside['id'],hint)
        self.assertNotIn(self.main['id'],hint)
        self.assertEqual(self.catalog,[n for n in self.snap['nodes'] if not(n['kind']=='JsxOpeningElement' and 'complete JSX node 'in n['label'])])
        self.assertEqual(self.file.read_text(),self.source)

    def test_compiler_fault_takes_priority_over_native_selector_then_insertions_come_last(self):
        ordered,hint=order_candidate_nodes(self.r,self.proposal,self.catalog,[self.slot['id']])
        self.assertEqual(ordered[0]['id'],self.slot['id'])
        self.assertEqual(ordered[1]['id'],self.aside['id'])
        remaining=[n for n in ordered if n['id'] not in {self.slot['id'],self.aside['id']}]
        if any(n['kind']=='insert'for n in remaining):
            self.assertEqual(remaining[-1]['kind'],'insert')

    def test_unsupported_selector_and_stale_source_dont_guess_target(self):
        self.r.requirement_gate.contract['criteria'][1]['check']['selector']='.unknown > form'
        _,hint=order_candidate_nodes(self.r,self.proposal,self.catalog,[])
        self.assertFalse(hint)
        self.r.requirement_gate.contract['criteria'][1]['check']['selector']="[data-testid='right']"
        self.file.write_text(self.source+'// user change')
        _,hint=order_candidate_nodes(self.r,self.proposal,self.catalog,[])
        self.assertFalse(hint)
        self.assertIn('// user change',self.file.read_text())
