import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verification_report import verification_report, completion_evidence
from failure import diagnostic


class ReportTests(unittest.TestCase):
    def test_adapter_rejects_unproven_or_stale_completion(self):
        events={
            'requirement.contract':{'seq':1,'data':{'contract_hash':'h','contract':{'task':'task','criteria':[{'id':'C1'}]}}},
            'autonomy.accepted':{'seq':2,'data':{}},
            'verification.finished':{'seq':3,'data':{'success':True,'contract_hash':'h','results':[{'id':'C1','status':'passed'}]}},
        }
        self.assertTrue(completion_evidence(events,'task')[0])
        self.assertFalse(completion_evidence(events,'another task')[0])
        events['verification.finished']['data']['results'][0]['status']='unverified'
        self.assertFalse(completion_evidence(events,'task')[0])
        events['verification.finished']['data']['results'][0]['status']='passed'
        events['autonomy.accepted']['seq']=4
        self.assertFalse(completion_evidence(events,'task')[0])

    def test_old_success_is_not_presented_as_goal_verified(self):
        history=Mock()
        history.last_event.return_value=None
        report=verification_report(history, {'id':'old', 'status':'succeeded'})
        self.assertFalse(report['recorded'])
        self.assertIsNone(report['result'])

    def test_only_same_contract_hash_can_supply_result(self):
        history=Mock()
        events={
            'requirement.contract': {'data':{'contract_hash':'original','contract':{'criteria':[]}}},
            'verification.finished': {'time':'now','data':{'contract_hash':'different','success':True}},
        }
        history.last_event.side_effect=lambda job, kind: events[kind]
        report=verification_report(history, {'id':'job','status':'running'})
        self.assertIsNone(report['result'])
        self.assertTrue(report['warning'])
        events['verification.finished']['data']['contract_hash']='original'
        self.assertTrue(verification_report(history, {'id':'job','status':'running'})['result']['success'])

    def test_failure_reason_contains_unmet_conditions(self):
        report=diagnostic({'type':'verification.finished','data':{'success':False,'results':[
            {'id':'C1','status':'failed','reason':'right panel missing'},
            {'id':'C2','status':'unverified','reason':'isolated API unavailable'},
            {'id':'C3','status':'passed','reason':'must not show'},
        ]}})
        self.assertIn('right panel missing',report['message'])
        self.assertIn('isolated API unavailable',report['message'])
        self.assertNotIn('must not show',report['message'])


if __name__=='__main__': unittest.main()
