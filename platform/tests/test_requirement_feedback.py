import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-only/harness'))
from divide_gate import StageGate

class RequirementFeedbackTests(unittest.TestCase):
    def test_native_failures_survive_unrelated_feedback_until_reverification(self):
        with tempfile.TemporaryDirectory() as folder:
            contract={'task':'조회와 결과 영역 구성','criteria':[{'id':'C1','requirement_id':'R1','check':{'op':'visible','selector':'form'}}]}
            parent=SimpleNamespace(frozen_contract=json.dumps(contract),contract_hash='hash',artifact_dir=Path(folder),_probe=Mock(return_value={'success':False,'results':[{'id':'C1','status':'failed','reason':'POST 조회 버튼','evidence':{'height':265}}]}))
            child=SimpleNamespace(feedback='',h=SimpleNamespace(log_event=Mock()))
            gate=StageGate(parent,child,{'id':'query','criterion_ids':['C1']},[],[])
            self.assertEqual(json.loads(gate.context())['unresolved_checks'],[])
            gate.verify();report=copy.deepcopy(gate.last_report)
            for feedback in ['No-op edit','Patch passed selected checks','AST snapshot unchanged']:
                child.feedback=feedback
                ctx=json.loads(gate.context());self.assertEqual(ctx['unresolved_checks'][0]['reason'],'POST 조회 버튼');self.assertEqual(gate.last_report,report)
            parent._probe.return_value={'success':True,'results':[{'id':'C1','status':'passed'}]}
            gate.verify();self.assertEqual(json.loads(gate.context())['unresolved_checks'],[])
