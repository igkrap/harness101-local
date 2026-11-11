import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'erp-harness'))
import requirement_contract
import standard_contract as sc

SHEET = {'path': '/api/companies', 'fields': [
    {'name': 'companyName', 'label': '회사명', 'required': True, 'sample': '한빛상사'},
    {'name': 'phone', 'label': '전화번호', 'required': False, 'sample': '02-123-4567'}]}


class StandardContractTests(unittest.TestCase):
    def test_sheet_rules(self):
        self.assertEqual(sc.validate_sheet(SHEET)['fields'][0]['required'], True)
        for bad, message in [
                (dict(SHEET, path='/api/Companies/'), 'path must look like'),
                (dict(SHEET, fields=[dict(SHEET['fields'][0], name='company_name')]), 'camelCase'),
                (dict(SHEET, fields=[dict(SHEET['fields'][0], name='createdBy')]), 'managed by the framework'),
                (dict(SHEET, fields=[dict(SHEET['fields'][1])]), 'at least the main name'),
                (dict(SHEET, fields=SHEET['fields'] + [dict(SHEET['fields'][1], name='companyName')]), 'listed twice')]:
            with self.assertRaisesRegex(ValueError, message):
                sc.validate_sheet(bad)
        with self.assertRaisesRegex(ValueError, 'already exists'):
            sc.validate_sheet(SHEET, {'/api/companies'})

    def test_api_and_screen_criteria_are_valid_contracts(self):
        sheet = sc.validate_sheet(SHEET)
        for task, criteria in (('회사 등록 API', sc.api_criteria(sheet)), ('회사 등록 화면', sc.screen_criteria(sheet))):
            parsed = requirement_contract.validate(task, {'version': 1, 'task': task, 'requirements': requirement_contract.requirements(task), 'criteria': criteria})
            self.assertEqual(len(parsed['criteria']), len(criteria))
        api = sc.api_criteria(sheet)
        self.assertEqual([(c['check']['method'], c['check']['status']) for c in api],
                         [('POST', 201), ('GET', 200), ('PUT', 200), ('POST', 400), ('DELETE', 204), ('PUT', 404)])
        self.assertEqual(api[3]['check']['body']['companyName'], '')  # the refusal is unmistakable: the required field is blank
        self.assertIn('companyName(회사명, 필수)', sc.sheet_note(sheet))

    def test_model_gives_only_the_sheet_and_bad_answers_are_retried(self):
        answers = iter(['{"path": "/api/items", "fields": []}', 'here: ' + __import__('json').dumps(SHEET, ensure_ascii=False)])
        runner = SimpleNamespace(args=SimpleNamespace(task='회사 등록 API'), h=SimpleNamespace(log_event=Mock()),
                                 ask=lambda messages, tools: {'content': next(answers)})
        self.assertEqual(sc.ask_sheet(runner, {'/api/items'})['path'], '/api/companies')
        self.assertEqual(runner.h.log_event.call_args_list[0].args[0], 'requirement.sheet_rejected')

    def test_only_plain_new_api_and_new_screen_tasks_are_standard(self):
        def runner(task, modes):
            return SimpleNamespace(args=SimpleNamespace(task=task), modes=modes, h=SimpleNamespace(workspace=SimpleNamespace(root=Path('/nonexistent')), log_event=Mock()))
        self.assertTrue(sc._is_new_api(runner('회사 등록 API', ['backend'])))
        self.assertFalse(sc._is_new_api(runner('회사 API에 팩스번호 추가해줘', ['backend'])))
        self.assertFalse(sc._is_new_api(runner('회사 등록 화면', ['frontend', 'framework'])))
        with patch.dict('os.environ', {'HARNESS_STANDARD_CONTRACT': '0'}):
            self.assertIsNone(sc.build(runner('회사 등록 API', ['backend'])))
        self.assertIsNone(sc.build(runner('품목 화면 규격을 필수로\n그리고 색도 바꿔줘', ['frontend'])))


if __name__ == '__main__':
    unittest.main()
