import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]/'local-only/harness'))
from test_autonomy import native
HELPER=pathlib.Path(__file__).resolve().parents[2]/'local-only/harness/ast_organize_imports.cjs'

class ImportReflexTests(unittest.TestCase):
    def organize(self,source,path='/tmp/reflex-fixture.tsx'):
        p=subprocess.run(['node',str(HELPER)],input=json.dumps({'source':source,'path':path}),capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr or p.stdout)
        return json.loads(p.stdout)

    def test_compiler_removes_duplicate_unused_imports_and_preserves_body_and_side_effects(self):
        body='export default function App(){const [n]=useState(0);return <main title="한글 😀">{n}</main>;}\r\n'
        source="import './boot';\r\nimport {useState} from 'react';\r\nimport {useState} from 'react';\r\nimport {Box} from 'unused';\r\n"+body
        with tempfile.TemporaryDirectory() as td:
            p=pathlib.Path(td)/'App.tsx';p.write_bytes(source.encode());r=self.organize(source,str(p))
            self.assertTrue(r['changed']);self.assertEqual(p.read_bytes(),source.encode())
        self.assertEqual(r['source'].count('useState'),2)
        self.assertNotIn('Box',r['source'])
        self.assertIn("'./boot'",r['source'])
        self.assertTrue(r['source'].endswith(body))

    def test_never_organizes_interleaved_imports_across_body(self):
        source="import {A} from 'a';\nconsole.log('body');\nimport {B} from 'b';\n"
        p=subprocess.run(['node',str(HELPER)],input=json.dumps({'source':source,'path':'/tmp/App.tsx'}),capture_output=True,text=True)
        if p.returncode==0:self.assertEqual(json.loads(p.stdout)['source'],source)

    def test_runner_rechecks_actual_result_and_rollback_covers_normalization(self):
        from autonomy_runtime import Runner
        from import_reflex import repair_imports
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td);rel='frontend/src/App.tsx';p=root/rel;p.parent.mkdir(parents=True)
            original="import {useState} from 'react';\r\nexport default function App(){return useState(0)[0];}\r\n"
            p.write_bytes(original.encode())
            args=SimpleNamespace(task='fixture',workspace=str(root),check='frontend',max_rounds=0,ponytail='off',llm_url='http://127.0.0.1:8099/v1',model='fixture')
            runner=Runner(args,native.Harness);runner.h.evidence_path=root/'events.jsonl'
            runner.cp.stage(rel);candidate=original.replace("import {useState}","import {Box} from 'unused';\r\nimport {useState}")
            p.write_bytes(candidate.encode());runner.cp.record(rel)
            calls=[]
            def check(mode):
                calls.append(mode);bad='Box' in p.read_text()
                return {'success':not bad,'stdout':"error @typescript-eslint/no-unused-vars 'Box' unused" if bad else 'passed','stderr':'','exit_code':int(bad)}
            runner.h.checker.run_check=check
            ok,feedback=runner.verify();self.assertTrue(ok,feedback);self.assertEqual(calls,['frontend','frontend'])
            self.assertNotIn('Box',p.read_text());self.assertEqual(runner.cp._records[rel]['expected'],p.read_bytes())
            runner.cp.rollback();self.assertEqual(p.read_bytes(),original.encode())
            runner.cp.stage(rel);p.write_text(candidate);runner.cp.record(rel);p.write_text('user concurrent edit')
            with self.assertRaisesRegex(RuntimeError,'(?i)concurrent|changed'):
                repair_imports(runner,{'stdout':'TS2300: Duplicate identifier','stderr':''})
            self.assertEqual(p.read_text(),'user concurrent edit')

if __name__=='__main__':unittest.main()
