import copy
import sys
from pathlib import Path
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-only/harness'))


class ApiErrorPayloadTests(unittest.TestCase):
    def checks(self):
        return [{'id':'positive','check':{'op':'api','method':'PUT','path':'/api/items/1','status':200,'body':{'name':'valid','quantity':1}}},{'id':'missing','check':{'op':'api','method':'PUT','path':'/api/items/9999','status':404}}]

    def test_missing_id_test_requires_otherwise_valid_peer_fields(self):
        from api_error_payloads import validate_error_payloads
        for body in (None,{}, {'name':'valid'}):
            checks=self.checks()
            if body is not None:checks[1]['check']['body']=body
            original=copy.deepcopy(checks)
            with self.assertRaises(ValueError)as caught:validate_error_payloads(checks)
            for value in ('404','400','missing','name','quantity'):self.assertIn(value,str(caught.exception))
            self.assertEqual(checks,original)

    def test_complete_404_payload_and_patch_peers_are_accepted(self):
        from api_error_payloads import validate_error_payloads
        for method in ('PUT','PATCH'):
            checks=self.checks()
            for c in checks:c['check']['method']=method
            checks[1]['check']['body']={'name':'valid','quantity':1}
            before=copy.deepcopy(checks)
            validate_error_payloads(checks)
            self.assertEqual(checks,before)

    def test_other_routes_methods_and_explicit_missing_body_validation_are_unchanged(self):
        from api_error_payloads import validate_error_payloads
        for change in ({'path':'/api/other/9999'},{'method':'GET'},{'method':'DELETE'},{'status':400}):
            checks=self.checks();checks[1]['check'].update(change)
            validate_error_payloads(checks)
        validate_error_payloads([self.checks()[1]])

    def test_real_contract_validator_rejects_404_that_only_tests_missing_body(self):
        import requirement_contract as contract
        criteria=self.checks()
        for c in criteria:c.update(requirement_id='R1',description=c['id'])
        criteria[0]['check'].update(json_path=['name'],equals='valid')
        with self.assertRaisesRegex(ValueError,'404'):contract.validate('update API',{'criteria':criteria})
        criteria[1]['check']['body']={'name':'valid','quantity':1}
        contract.validate('update API',{'criteria':criteria})
