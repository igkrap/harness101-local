import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
from server import Platform
from verification_gate import Gate
from requirement_contract import validate, digest

class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.task = '로고 표시'
        self.contract = validate(self.task, {'criteria': [{'id':'C1','requirement_id':'R1','description':'로고','check':{'op':'visible','selector':'nav'}}]})
        self.rc = {'source_job':'a'*32,'contract':self.contract,'contract_hash':digest(self.contract)}
    def tearDown(self): self.tmp.cleanup()
    def gate(self, rc):
        runner = SimpleNamespace(args=SimpleNamespace(task=self.task,resume_contract=rc),modes=['frontend'],h=SimpleNamespace(workspace=SimpleNamespace(root=self.root),log_event=Mock()),ask=Mock(side_effect=AssertionError('no generation on reuse')),current_context=Mock(side_effect=AssertionError('no source regeneration')))
        gate = Gate(runner); gate.artifact_dir = self.root/'artifacts'; return gate, runner
    def test_valid_reuse_freezes_without_model_calls_and_keeps_mutation_gate(self):
        gate,runner=self.gate(self.rc); gate.prepare()
        self.assertEqual(json.loads(gate.frozen_contract),self.contract)
        self.assertEqual(gate.contract_hash,digest(self.contract))
        self.assertTrue((gate.artifact_dir/'contract.json').exists())
        runner.ask.assert_not_called()
        runner.accepted = True
        gate._probe = Mock(return_value={'success':True,'results':[{'id':'C1','status':'passed'}]})
        self.assertFalse(gate.verify()['success'])
    def test_bad_hash_task_requirements_schema_or_manual_rejected(self):
        cases=[{}, {**self.rc,'contract_hash':'wrong'}]
        for field,value in [('task','다른 요청'),('requirements',[]),('criteria',[])]:
            rc=copy.deepcopy(self.rc); rc['contract'][field]=value; rc['contract_hash']=digest(rc['contract']);cases.append(rc)
        rc=copy.deepcopy(self.rc);rc['contract']['criteria'][0]['check']={'op':'manual','reason':'사람 확인'};rc['contract_hash']=digest(rc['contract']);cases.append(rc)
        for rc in cases:
            with self.subTest(rc=rc),self.assertRaises(ValueError):self.gate(rc)[0].prepare()
    def test_platform_scope_and_completed_definition(self):
        app=Platform(self.root,self.root/'state',0);app.metadata={'id':'one'}
        key=self.rc['source_job'];folder=app.state/key;folder.mkdir()
        old={'id':key,'goal':self.task,'checks':['frontend'],'project_id':'one','status':'stopped','started_at':'2026-11-01T00:00:00Z'}
        app.jobs[key]=old
        (folder/'events.jsonl').write_text(json.dumps({'seq':1,'type':'requirement.contract','data':{'contract':self.contract,'contract_hash':digest(self.contract)}})+'\n')
        body={'contract_from_job':key}
        self.assertEqual(app.resumed_contract(body,self.task,['frontend']),self.rc)
        for goal,checks in [('다른 요청',['frontend']),(self.task,['backend'])]:
            with self.assertRaises(ValueError):app.resumed_contract(body,goal,checks)
        old['project_id']='two'
        with self.assertRaises(ValueError):app.resumed_contract(body,self.task,['frontend'])
        with self.assertRaises(ValueError):app.resumed_contract({'contract_from_job':'../x'},self.task,['frontend'])
        self.assertIsNone(app.resumed_contract({},self.task,['frontend']))
        app.history.db.close()
