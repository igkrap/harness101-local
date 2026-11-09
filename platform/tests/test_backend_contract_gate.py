import base64
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-only/harness'))
from backend_contract_gate import verify


class BackendGateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        app=self.root/'backend/src/main/java/example/App.java'
        app.parent.mkdir(parents=True)
        app.write_text('package example; @SpringBootApplication public class App {}')
        (self.root/'backend/pom.xml').write_text('<project><version>4.1.2</version></project>')
        self.criteria=[{'id':key,'check':{'op':'api','method':'GET','path':'/api/items','status':200}} for key in ['C1','C2']]
        self.checker=SimpleNamespace(workspace=SimpleNamespace(root=self.root))
        self.output=self.root/'proof'
    def tearDown(self):self.temp.cleanup()

    def execute(self,mode):
        def command(cmd,cwd):
            envelope=json.loads((Path(cwd)/'verification-contract.json').read_text())
            markers=[]
            for c in envelope['criteria']:
                marker='|'.join([envelope['nonce'],base64.b64encode(c['id'].encode()).decode(),'passed',base64.b64encode(b'status=200 body=[]').decode()])
                if mode!='missing':markers.append(marker)
                if mode=='duplicate':markers.append(marker)
            return {'success':True,'stdout':'\n'.join(markers),'stderr':''}
        self.checker._exec=command
        with patch.dict(os.environ,{'HARNESS_TEST_DB_URL':'jdbc:postgresql://mdi-db:5432/fixture'}), patch('isolated_backend.run_backend',side_effect=lambda checker,callback:callback()):
            return verify(self.checker,self.criteria,self.output)

    def test_maven_success_without_assertion_markers_cannot_pass(self):
        result=self.execute('missing')
        self.assertFalse(result['success'])
        self.assertEqual([r['id'] for r in result['results']],['C1','C2'])
        self.assertTrue(all(r['status']=='unverified' for r in result['results']))

    def test_duplicate_results_cannot_pass(self):
        result=self.execute('duplicate')
        self.assertFalse(result['success'])
        self.assertTrue(all(r['status']=='failed' for r in result['results']))

    def test_each_criterion_needs_exactly_one_observation(self):
        result=self.execute('valid')
        self.assertTrue(result['success'])
        self.assertEqual([r['id'] for r in result['results']],['C1','C2'])
        self.assertFalse((self.root/'backend/src/test').exists(),'verification changed original source')

    def test_cleanup_error_retains_exact_reason_and_criterion_ids(self):
        with patch('isolated_backend.run_backend',return_value={'success':False,'error':'Cleanup failed: database locked'}):
            result=verify(self.checker,self.criteria,self.output)
        self.assertFalse(result['success'])
        self.assertEqual([r['id'] for r in result['results']],['C1','C2'])
        self.assertTrue(all('database locked' in r['reason'] for r in result['results']))


if __name__=='__main__':unittest.main()
