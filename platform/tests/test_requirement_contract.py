import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
import requirement_contract as contract


class ContractTests(unittest.TestCase):
    task = '좌측 넓게, 우측 좁게\n조회 버튼으로 결과 필터링\n수정 후 다시 조회해도 값 유지'

    def test_literal_layout_compiles_without_changing_spatial_meaning(self):
        for relation, canonical, reverse in [('below', 'above', True),
                ('right_of', 'left_of', True), ('narrower_than', 'wider_than', True),
                ('above', 'above', False), ('left_of', 'left_of', False)]:
            raw = self.valid()
            raw['criteria'][0]['check'] = {'op': 'layout', 'subject': '#subject',
                'reference': '#reference', 'relation': relation}
            result = contract.validate(self.task, raw)
            check = result['criteria'][0]['check']
            self.assertEqual(check['relation'], canonical)
            self.assertEqual(check['left'], '#reference' if reverse else '#subject')
            self.assertEqual(check['right'], '#subject' if reverse else '#reference')
            self.assertEqual(contract.digest(result), contract.digest(contract.validate(self.task, result)))

    def test_ambiguous_or_incomplete_literal_layout_is_rejected(self):
        for extra in [{'left': '#other'}, {'right': '#other'}]:
            raw = self.valid()
            raw['criteria'][0]['check'] = dict(op='layout', subject='#a', reference='#b', relation='below', **extra)
            with self.assertRaises(ValueError): contract.validate(self.task, raw)
        raw['criteria'][0]['check'] = dict(op='layout', subject='#a', relation='below')
        with self.assertRaises(ValueError): contract.validate(self.task, raw)

    def valid(self):
        return {'criteria': [
            {'id': 'C1', 'requirement_id': 'R1', 'description': 'left wider',
             'check': {'op': 'layout', 'left': '#left', 'right': '#right', 'relation': 'wider_than', 'ratio': 1.5}},
            {'id': 'C2', 'requirement_id': 'R2', 'description': 'query filters rows',
             'check': {'op': 'scenario', 'steps': [
                 {'action': 'fill', 'selector': '#query', 'value': 'bolt'},
                 {'action': 'click', 'selector': '#search'},
                 {'action': 'expect_text', 'selector': '#rows', 'value': 'bolt'}]}},
            {'id': 'C3', 'requirement_id': 'R3', 'description': 'read stored value',
             'check': {'op': 'api', 'method': 'GET', 'path': '/api/items/1', 'status': 200,
                       'json_path': ['name'], 'equals': 'bolt'}}]}

    def test_exact_request_and_every_clause_are_retained(self):
        result = contract.validate(self.task, self.valid())
        self.assertEqual(result['task'], self.task)
        self.assertEqual([r['description'] for r in result['requirements']], self.task.splitlines())
        self.assertEqual(result['version'], 1)

    def test_omitted_requirement_cannot_pass(self):
        raw = self.valid()
        raw['criteria'].pop()
        with self.assertRaises(ValueError): contract.validate(self.task, raw)

    def test_duplicate_ids_and_unknown_requirements_rejected(self):
        for key, value in [('id', 'C1'), ('requirement_id', 'R99')]:
            raw = self.valid()
            raw['criteria'][1][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): contract.validate(self.task, raw)

    def test_contract_is_independent_of_model_response_object(self):
        raw = self.valid()
        result = contract.validate(self.task, raw)
        before = contract.digest(result)
        raw['criteria'][0]['check']['ratio'] = 0.01
        self.assertEqual(contract.digest(result), before)

    def test_untrusted_execution_and_external_api_paths_rejected(self):
        for check in [
            {'op': 'javascript', 'code': 'return true'},
            {'op': 'visible', 'selector': 'body', 'script': 'return true'},
            {'op': 'api', 'method': 'GET', 'path': '//example.org', 'status': 200},
            {'op': 'api', 'method': 'GET', 'path': 'https://example.org', 'status': 200},
            {'op': 'api', 'method': 'GET', 'path': '/api/a#fragment', 'status': 200},
            {'op': 'scenario', 'steps': [{'action': 'evaluate', 'selector': 'body'}]},
        ]:
            raw = self.valid()
            raw['criteria'][0]['check'] = check
            with self.subTest(check=check), self.assertRaises(ValueError): contract.validate(self.task, raw)

    def test_numbers_cannot_be_boolean_nan_or_negative(self):
        for ratio in [True, 0, 0.7, -1, float('nan'), float('inf')]:
            raw = self.valid()
            raw['criteria'][0]['check']['ratio'] = ratio
            with self.subTest(ratio=ratio), self.assertRaises(ValueError): contract.validate(self.task, raw)

    def test_mutation_status_alone_is_not_completion_evidence(self):
        raw = self.valid()
        raw['criteria'][2]['check'] = {'op': 'api', 'method': 'PUT', 'path': '/api/items/1', 'status': 200}
        with self.assertRaises(ValueError): contract.validate(self.task, raw)

    def test_expected_client_errors_can_have_empty_response_bodies(self):
        for method, status in [('PUT',400),('PUT',404),('POST',422),('DELETE',409)]:
            raw=self.valid()
            check={'op':'api','method':method,'path':'/api/items/1','status':status,'body':{'name':'valid'}}
            raw['criteria'][2]['check']=check
            result=contract.validate(self.task,raw)
            self.assertEqual(result['criteria'][2]['check'],check)

    def test_error_exception_does_not_allow_partial_json_assertions_or_status_only_success(self):
        for check in [
            {'op':'api','method':'PUT','path':'/api/items/1','status':404,'json_path':['name']},
            {'op':'api','method':'PUT','path':'/api/items/1','status':400,'equals':None},
            {'op':'api','method':'PUT','path':'/api/items/1','status':201},
            {'op':'api','method':'PUT','path':'/api/items/1','status':500},
        ]:
            raw=self.valid();raw['criteria'][2]['check']=check
            with self.subTest(check=check),self.assertRaises(ValueError):contract.validate(self.task,raw)

    def test_parser_rejects_duplicate_keys_and_prose(self):
        duplicated = json.dumps(self.valid()).replace('"id": "C1"', '"id": "BAD", "id": "C1"', 1)
        for text in ['{"criteria":[],"criteria":[]}', duplicated, 'DONE ' + json.dumps(self.valid())]:
            with self.subTest(text=text[:60]), self.assertRaises(ValueError): contract.parse(self.task, text)
        self.assertEqual(contract.parse(self.task, '```json\n' + json.dumps(self.valid()) + '\n```')['task'], self.task)

    def test_null_api_result_and_whole_body_assertion_are_valid(self):
        raw = self.valid()
        raw['criteria'][2]['check'].update(json_path=[], equals=None)
        self.assertEqual(contract.validate(self.task, raw)['criteria'][2]['check']['equals'], None)

    def test_scenario_no_assertion_or_unknown_step_fields_rejected(self):
        for steps in [[{'action':'click','selector':'#save'}],
                      [{'action':'expect_visible','selector':'body','script':'return true'}]]:
            raw = self.valid()
            raw['criteria'][1]['check']['steps'] = steps
            with self.subTest(steps=steps), self.assertRaises(ValueError): contract.validate(self.task, raw)

    def test_input_values_are_strings_and_empty_clear_is_valid(self):
        raw=self.valid()
        raw['criteria'][1]['check']['steps'][0]['value']=12
        with self.assertRaises(ValueError):contract.validate(self.task,raw)
        raw['criteria'][1]['check']['steps'][0]['value']=''
        contract.validate(self.task,raw)

    def test_empty_contract_or_task_rejected(self):
        for raw in [{}, {'criteria': []}]:
            with self.assertRaises(ValueError): contract.validate(self.task, raw)
        with self.assertRaises(ValueError): contract.requirements(' \n ')


if __name__ == '__main__': unittest.main()


class ExpectHiddenTests(unittest.TestCase):
    def contract(self, steps):
        import requirement_contract
        return requirement_contract.validate('패널을 버튼으로 접기', {'criteria': [
            {'id': 'C1', 'requirement_id': 'R1', 'description': '토글', 'check': {'op': 'scenario', 'steps': steps}}]})

    def test_toggle_scenario_with_hidden_and_visible_is_valid(self):
        parsed = self.contract([{'action': 'click', 'selector': 'button[data-ui="t"]'},
                                {'action': 'expect_hidden', 'selector': '[data-ui="p"]'},
                                {'action': 'click', 'selector': 'button[data-ui="t"]'},
                                {'action': 'expect_visible', 'selector': '[data-ui="p"]'}])
        self.assertEqual(parsed['criteria'][0]['check']['steps'][1]['action'], 'expect_hidden')

    def test_hidden_without_visible_proof_of_same_selector_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'expect_visible'):
            self.contract([{'action': 'click', 'selector': 'button'}, {'action': 'expect_hidden', 'selector': '#typo'}])


class HiddenDescriptionTests(unittest.TestCase):
    def test_description_says_hidden_but_check_proves_visible_is_rejected(self):
        import requirement_contract
        with self.assertRaisesRegex(ValueError, 'expect_hidden'):
            requirement_contract.validate('패널 토글', {'criteria': [{'id': 'C1', 'requirement_id': 'R1',
                'description': '편집 패널 초기 로드 시 숨김 상태 확인', 'check': {'op': 'visible', 'selector': '#p'}}]})
