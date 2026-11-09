import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))


class DivideBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.events = []
        self.h = SimpleNamespace(workspace=SimpleNamespace(root=self.root, safe_path=lambda p:self.root/p),
                                 log_event=lambda k,d:self.events.append((k,d)))
        self.child = SimpleNamespace(h=self.h)
        self.stage = {'id':'query','title':'조회','instructions':'조회 구현','domain':'backend',
                      'paths':['backend/src/main/Query.java'],'references':[], 'criterion_ids':['C2']}

    def tearDown(self): self.temp.cleanup()

    def write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def test_context_keeps_complete_sources_relative_permissions_and_missing_files(self):
        from divide_context import snapshot
        self.write(self.stage['paths'][0], 'class Query {}')
        self.stage['paths'].append('backend/src/main/New.java')
        self.stage['references']=['frontend/src/types.ts']
        self.write('frontend/src/types.ts', 'export type Query = string;')
        text, reads = snapshot(self.child, self.stage)
        self.assertEqual(reads, {'backend/src/main/Query.java','frontend/src/types.ts'})
        self.assertIn('class Query {}',text)
        self.assertIn('backend/src/main/Query.java',text)
        self.assertIn('New.java',text)
        self.assertIn('export type Query = string;',text)

    def test_context_does_not_include_partial_large_sources_or_symlink_targets(self):
        from divide_context import snapshot
        self.write(self.stage['paths'][0], 'X'*10000)
        self.stage['references']=['frontend/src/alias.ts']
        p = self.write('private.ts','SECRET')
        alias=self.root/'frontend/src/alias.ts';alias.parent.mkdir(parents=True);alias.symlink_to(p)
        text, reads = snapshot(self.child,self.stage)
        self.assertFalse(reads)
        self.assertNotIn('X'*100,text)
        self.assertNotIn('SECRET',text)

    def test_handoff_keeps_actual_results_and_relative_hashes(self):
        from divide_context import packet
        rel = self.stage['paths'][0]
        data = b'class Query {}'
        parent = SimpleNamespace(runner=self.child,contract_hash='frozen',
                                 _source_hashes=lambda root:{rel:hashlib.sha256(data).digest()})
        report={'success':True,'results':[{'id':'C2','status':'passed','reason':'actual body','evidence':{'value':42}}]}
        result=packet(parent,{rel},report)
        self.assertEqual(result['source_hashes'][rel],hashlib.sha256(data).hexdigest())
        self.assertEqual(result['verified_results'],report['results'])

    def test_frontend_catalog_larger_than_raw_limit_is_retained_whole(self):
        from divide_context import snapshot
        self.stage.update(domain='frontend',paths=['frontend/src/screens/Query.tsx'])
        self.write(self.stage['paths'][0],'export default function Query(){return null;}')
        self.write('frontend/src/workspace.json','{"activeTab":"Query"}')
        catalog={'snapshot_id':'original-id','nodes':[{'id':'node-'+str(i),'source':'x'*100} for i in range(100)]}
        with patch('ast_editing.editor',return_value=SimpleNamespace(snapshot=lambda rel:catalog)):
            text,reads=snapshot(self.child,self.stage)
        self.assertIn(json.dumps(catalog,ensure_ascii=False),text)
        self.assertIn('frontend/src/workspace.json',reads)
        self.assertIn('frontend/src/screens/Query.tsx',reads)
        self.assertLessEqual(len(text),36000)

    def test_stage_probe_preserves_upstream_and_cannot_emit_global_completion(self):
        from divide_gate import StageGate
        criteria=[{'id':'C1','check':{'op':'api'}},{'id':'C2','check':{'op':'api'}},{'id':'C3','check':{'op':'api'}}]
        probes=[]
        def probe(cs):
            probes.append([c['id'] for c in cs])
            return {'success':True,'results':[{'id':c['id'],'status':'passed'} for c in cs], 'layout':[{'actual':True}]}
        parent=SimpleNamespace(frozen_contract=json.dumps({'task':'original task','criteria':criteria}),
                               contract_hash='frozen',artifact_dir=self.root/'proof',_probe=probe)
        gate=StageGate(parent,self.child,self.stage,['C1'],[])
        report=gate.verify()
        self.assertTrue(report['success'])
        self.assertEqual(probes,[['C1','C2']])
        self.assertNotIn('layout',report)
        self.assertEqual(gate.last_report,report)
        self.assertNotIn('verification.finished',[k for k,_ in self.events])
        self.assertEqual([k for k,_ in self.events],['autonomy.stage_verified'])
        full=json.loads(Path(report['report_path']).read_text())
        self.assertEqual(full['layout'],[{'actual':True}])

    def test_domain_mutations_and_repeated_inspections(self):
        from divide_guard import guard
        with self.assertRaises(ValueError):guard(self.child,self.stage,'edit_file',{'path':'frontend/src/A.tsx'})
        guard(self.child,self.stage,'write_file',{'path':'backend/src/main/Helper.java'})
        self.assertIn('autonomy.stage_scope_extended',[k for k,_ in self.events])
        rel=self.stage['paths'][0]
        p=self.write(rel,'class Query {}')
        args={'path':rel,'action':'edit_ranges'}
        guard(self.child,self.stage,'inspect_code',args)
        guard(self.child,self.stage,'inspect_code',args)
        guard(self.child,self.stage,'inspect_code',args)
        self.assertTrue(self.child._division_ast_focus)
        self.assertIn(rel,self.child._division_ast_paths)
        guard(self.child,self.stage,'inspect_code',{'path':rel,'action':'diagnostics'})
        p.write_text('class Query { int value; }')
        guard(self.child,self.stage,'inspect_code',args)

    def test_stage_rejects_missing_duplicate_and_unverified_probe_results(self):
        from divide_gate import StageGate
        criteria=[{'id':'C2','check':{'op':'api'}}]
        for results in ([], [{'id':'C2','status':'passed'}]*2,
                        [{'id':'C2','status':'unverified'}], [{'id':'OTHER','status':'passed'}]):
            with self.subTest(results=results):
                parent=SimpleNamespace(frozen_contract=json.dumps({'task':'task','criteria':criteria}),
                    contract_hash='frozen',artifact_dir=self.root/'proof',
                    _probe=lambda cs:{'success':True,'results':results})
                gate=StageGate(parent,self.child,self.stage,[],[])
                self.assertFalse(gate.verify()['success'])


if __name__ == '__main__':unittest.main()
