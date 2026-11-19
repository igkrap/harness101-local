import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from workspaces import Workspaces
from changes import Changes, read_changes


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        self.one=self.project('one');self.two=self.project('two')
        self.hub=Workspaces(self.one,self.base/'state',0)
        self.addCleanup(lambda:[app.history.close() for app in self.hub.apps.values()])
    def project(self,name):
        root=self.base/name;(root/'frontend/src').mkdir(parents=True)
        (root/'frontend/package.json').write_text('{}');(root/'frontend/src/App.tsx').write_text(name)
        return root
    def add(self):return self.hub.add({'name':'Two','root':str(self.two)})
    def test_project_sources_and_journals_are_isolated_and_persist(self):
        record=self.add();a=self.hub.resolve();b=self.hub.resolve(record['id'])
        self.assertNotEqual(a.state,b.state);self.assertEqual(a.source('frontend/src/App.tsx')['content'],'one');self.assertEqual(b.source('frontend/src/App.tsx')['content'],'two')
        key='a'*32;a.jobs[key]={'id':key,'status':'succeeded','started_at':'2026-01-01'};a.save(a.jobs[key])
        self.assertEqual(b.job_page()['total'],0)
        restored=Workspaces(self.one,self.base/'state',0)
        try:self.assertEqual(len(restored.catalog()['projects']),2);self.assertIn(key,restored.resolve().jobs)
        finally:[app.history.close() for app in restored.apps.values()]
    def test_duplicate_nested_and_unknown_roots_rejected(self):
        for root in (self.one,self.one/'frontend',self.base):
            with self.assertRaises(ValueError):self.hub.add({'name':'bad','root':str(root)})
        with self.assertRaises(ValueError):self.hub.resolve('other')
        with self.assertRaises(ValueError):self.hub.add({'name':'remote','root':str(self.two),'model_url':'https://external.example/v1'})
    def test_backend_requires_separate_database_and_checks_are_project_specific(self):
        (self.two/'backend').mkdir();(self.two/'backend/pom.xml').write_text('<project/>')
        record=self.add();app=self.hub.resolve(record['id'])
        self.assertEqual(app.available_checks(),['frontend'])
        with self.assertRaises(ValueError):app.start({'kind':'checks','checks':['backend']})
        app.metadata['test_db_url']='jdbc:postgresql://mdi-db:5432/two_test'
        self.assertEqual(app.available_checks(),['frontend','backend'])
    def models(self):
        stream=io.BytesIO(json.dumps({'data':[{'id':'local-a'},{'id':'local-b'}]}).encode());stream.status=200
        return stream
    def test_model_selection_is_validated_and_forwarded_to_request(self):
        app=self.hub.resolve();child=subprocess.Popen([sys.executable,'-c','pass'],start_new_session=True)
        with patch('server.urllib.request.urlopen',return_value=self.models()),patch.object(self.hub,'busy',return_value=False),patch('server.subprocess.Popen',return_value=child):
            with self.assertRaises(ValueError):app.start({'kind':'agent','goal':'test','checks':['frontend'],'model':'unknown'})
            job=app.start({'kind':'agent','goal':'test','checks':['frontend'],'model':'local-b'})
        child.wait(timeout=3)
        for _ in range(100):
            if job['id'] not in app.processes:break
            time.sleep(.01)
        request=json.loads((app.state/job['id']/'request.json').read_text())
        self.assertEqual(request['model'],'local-b');self.assertEqual(request['llm_url'],'http://127.0.0.1:8099/v1');self.assertEqual(request['project_id'],'default')
    def test_other_project_cannot_start_while_model_job_runs(self):
        a=self.hub.resolve();b=self.hub.resolve(self.add()['id'])
        child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(0.3)'],start_new_session=True)
        try:
            with patch('workspaces.subprocess.run',return_value=subprocess.CompletedProcess([],0,'','')),patch('server.subprocess.Popen',return_value=child):
                a.start({'kind':'checks','checks':['frontend']})
                with self.assertRaises(RuntimeError):b.start({'kind':'checks','checks':['frontend']})
        finally:child.wait(timeout=3);time.sleep(.02)

    def test_registered_settings_are_frozen_in_run_and_project_default(self):
        app=self.hub.resolve()
        config=self.hub.configure_model({'name':'configured','model':'custom/model','url':'http://127.0.0.1:8101/v1','temperature':.2,'timeout':90,'max_tokens':1024},app)
        self.hub.configure_model({'action':'default','id':config['id']},app)
        child=subprocess.Popen([sys.executable,'-c','pass'],start_new_session=True)
        with patch.object(self.hub,'busy',return_value=False),patch('server.subprocess.Popen',return_value=child):
            job=app.start({'kind':'agent','goal':'test registered model','checks':['frontend']})
        child.wait(timeout=3)
        request=json.loads((app.state/job['id']/'request.json').read_text())
        self.assertEqual(request['model'],'custom/model');self.assertEqual(request['llm_url'],'http://127.0.0.1:8101/v1')
        self.assertEqual(request['model_config']['temperature'],.2)
        self.hub.configure_model({**config,'temperature':.7},app)
        self.assertEqual(job['model_config']['temperature'],.2)
        self.hub.configure_model({'action':'remove','id':config['id']},app)
        self.assertNotIn('model_config',app.metadata)

    def test_known_unsupported_models_cannot_be_selected(self):
        app=self.hub.resolve();health={'http://127.0.0.1:8099/v1':{'local-b':{'supported':False,'error':'unsupported type'}}}
        (self.hub.state/'model-health.json').write_text(json.dumps(health))
        with patch('server.urllib.request.urlopen',return_value=self.models()):
            result=app.models()
        self.assertEqual(result['available'],['local-a']);self.assertIn('local-b',result['unavailable'])
        with self.assertRaises(ValueError):app.start({'kind':'agent','goal':'test','checks':['frontend'],'model':'local-b'})

    def test_native_backend_uses_project_database(self):
        import importlib.util
        runtime=Path(__file__).resolve().parents[2]/'local-only/harness/harness.py'
        spec=importlib.util.spec_from_file_location('database_config_check',runtime);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        checker=module.Checker(module.WorkspaceManager(self.two));calls=[]
        checker._exec=lambda command:(calls.append(command) or {'success':True,'exit_code':0,'stdout':'','stderr':''})
        with patch.dict('os.environ',{'HARNESS_TEST_DB_URL':'jdbc:postgresql://mdi-db:5432/two_test'}):checker._check_backend()
        self.assertTrue(calls[0][-1].startswith('CREATE DATABASE mdi_gate_'))
        self.assertTrue(any(v.startswith('DB_URL=jdbc:postgresql://mdi-db:5432/mdi_gate_') for v in calls[1]))
        self.assertIn('clean',calls[1]);self.assertIn(calls[0][-1].split()[-1],calls[2][-1])

    def test_worker_in_unopened_registered_project_is_detected(self):
        record=self.add();self.assertNotIn(record['id'],self.hub.apps)
        command=f"99999 python3 /tmp/platform/adapter.py --project {record['root']} --job-dir /tmp/run\n"
        with patch('workspaces.subprocess.run',return_value=subprocess.CompletedProcess([],0,command,'')):
            self.assertTrue(self.hub.busy())
        macos_command=f"99999 /Library/Frameworks/Python3.framework/Python /tmp/platform/adapter.py --project {record['root']} --job-dir /tmp/run\n"
        with patch('workspaces.subprocess.run',return_value=subprocess.CompletedProcess([],0,macos_command,'')):
            self.assertTrue(self.hub.busy())


class ChangeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        (self.root/'frontend/src').mkdir(parents=True);self.job=self.root/'job';self.job.mkdir();self.changes=Changes(self.root,self.job)
    def test_accepted_changes_have_immutable_original_and_final_snapshots(self):
        rel='frontend/src/App.tsx';p=self.root/rel;p.write_text('one\n');self.changes.capture(rel);p.write_text('two\n');self.changes.accept([rel]);p.write_text('three\n');self.changes.accept([rel])
        result=read_changes(self.job);self.assertEqual(result['files'][0]['added'],1);self.assertEqual(result['files'][0]['removed'],1)
        p.write_text('unrelated later edit\n');detail=read_changes(self.job,rel);self.assertEqual(detail['before'],'one\n');self.assertEqual(detail['after'],'three\n')
        self.assertNotIn('before',result['files'][0])
    def test_rejected_edits_are_not_published(self):
        rel='frontend/src/New.tsx';self.changes.capture(rel);p=self.root/rel;p.write_text('broken');p.unlink()
        self.assertEqual(read_changes(self.job)['files'],[])
    def test_add_delete_and_net_revert(self):
        rel='frontend/src/New.tsx';p=self.root/rel;self.changes.capture(rel);p.write_text('new');self.changes.accept([rel]);self.assertEqual(read_changes(self.job)['files'][0]['status'],'added');p.unlink();self.changes.accept([rel]);self.assertEqual(read_changes(self.job)['files'],[])
        p.write_text('old');other=Changes(self.root,self.job);other.capture(rel);p.unlink();other.accept([rel]);self.assertEqual(read_changes(self.job)['files'][0]['status'],'deleted')
    def test_historical_runs_are_not_fabricated_and_paths_are_allowlisted(self):
        self.assertFalse(read_changes(self.root/'old')['recorded'])
        with self.assertRaises(ValueError):read_changes(self.job,'../../secret')
        self.changes.capture('../secret');self.assertTrue(read_changes(self.job)['warnings'])

