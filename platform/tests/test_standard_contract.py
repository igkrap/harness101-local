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
        every = dict(SHEET, fields=[dict(field, required=True) for field in SHEET['fields']] + [{'name': 'fax', 'label': '팩스', 'required': True, 'sample': '02'}])
        with self.assertRaisesRegex(ValueError, 'the rest are optional'):
            sc.validate_sheet(every, few_required=True)   # a sheet the model invents keeps required fields few
        self.assertEqual(len(sc.validate_sheet(every)['fields']), 3)  # a user's explicit change may require more
        with self.assertRaisesRegex(ValueError, 'already exists'):
            sc.validate_sheet(SHEET, {'/api/companies'})

    def test_api_and_screen_criteria_are_valid_contracts(self):
        sheet = sc.validate_sheet(SHEET)
        for task, criteria in (('회사 등록 API', sc.api_criteria(sheet)), ('회사 등록 화면', sc.screen_criteria(sheet))):
            parsed = requirement_contract.validate(task, {'version': 1, 'task': task, 'requirements': requirement_contract.requirements(task), 'criteria': criteria})
            self.assertEqual(len(parsed['criteria']), len(criteria))
        api = sc.api_criteria(sheet)
        self.assertEqual([(c['id'], c['check']['method'], c['check']['status']) for c in api],
                         [('C1', 'POST', 201), ('C2', 'GET', 200), ('C2_2', 'GET', 200), ('C3', 'PUT', 200), ('C4', 'POST', 400), ('C4b', 'POST', 201),
                          ('C5', 'DELETE', 204), ('C6', 'PUT', 404)])
        self.assertEqual(api[2]['check']['json_path'], [0, 'phone'])   # every field is read back, not only the key
        self.assertEqual(api[5]['check']['body'], {'companyName': '한빛상사 2'})  # optional fields may be left out
        self.assertEqual(api[4]['check']['body']['companyName'], '')  # the refusal is unmistakable: the required field is blank
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
        self.assertFalse(sc._is_new_api(runner('회사 API에 팩스번호 필드 추가', ['backend'])))  # this once created a separate fax API
        self.assertFalse(sc._is_new_api(runner('회사 등록 화면', ['frontend', 'framework'])))
        with patch.dict('os.environ', {'HARNESS_STANDARD_CONTRACT': '0'}):
            self.assertIsNone(sc.build(runner('회사 등록 API', ['backend'])))
        self.assertIsNone(sc.build(runner('품목 화면 규격을 필수로\n그리고 색도 바꿔줘', ['frontend'])))


if __name__ == '__main__':
    unittest.main()


class StandardChangeTests(unittest.TestCase):
    """A change to an existing API uses the standard checks only when one of them fails on the current code."""
    def run_build(self, failing):
        import json, tempfile
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        root = Path(folder.name) / 'proj'
        controller = root / 'backend/src/main/java/app/CompanyController.java'
        controller.parent.mkdir(parents=True); controller.write_text('@RequestMapping("/api/companies")\nclass CompanyController {}')
        runner = SimpleNamespace(args=SimpleNamespace(task='회사 등록에서 회사명만 입력해도 저장되게 해줘'), modes=['backend'],
                                 h=SimpleNamespace(workspace=SimpleNamespace(root=root), log_event=Mock(), checker=None),
                                 ask=lambda messages, tools: {'content': json.dumps(SHEET, ensure_ascii=False)})
        with patch.object(sc, 'SHEETS', Path(folder.name) / 'sheets'), patch.object(sc, '_baseline', return_value=failing):
            file = sc._sheet_file(root, '/api/companies'); file.parent.mkdir(parents=True)
            file.write_text(json.dumps(dict(SHEET, task='회사 등록 API'), ensure_ascii=False))
            return sc.build(runner), runner

    def test_failing_baseline_becomes_the_contract_and_the_cause_reaches_the_author(self):
        built, runner = self.run_build([{'id': 'C4b', 'status': 'failed', 'reason': 'returned 409 | root cause: null value in column "business_number"'}])
        self.assertEqual(built[1], 'standard-api-change')
        self.assertIn('business_number', runner._field_sheet_note)
        self.assertIn('새 V1__ 마이그레이션', runner._field_sheet_note)  # the next free migration number is named

    def test_passing_baseline_leaves_the_task_to_the_model_written_contract(self):
        built, runner = self.run_build([])
        self.assertIsNone(built)
        self.assertFalse(hasattr(runner, '_field_sheet_note'))


class ReferenceFieldTests(unittest.TestCase):
    """A field that points to another record: its target is created first and the field carries the id."""
    REFS = {'/api/departments': sc.validate_sheet({'path': '/api/departments', 'fields': [
        {'name': 'name', 'label': '부서명', 'required': True, 'sample': '개발팀'}, {'name': 'sortOrder', 'label': '순서', 'required': False, 'sample': '1'}]})}
    EMPLOYEE = {'path': '/api/employees', 'fields': [
        {'name': 'name', 'label': '이름', 'required': True, 'sample': '홍길동'},
        {'name': 'departmentId', 'label': '부서', 'required': False, 'ref': {'path': '/api/departments', 'label': 'name'}}]}

    def test_target_is_prepared_and_the_reference_is_an_id(self):
        sheet = sc.validate_sheet(self.EMPLOYEE, set(self.REFS), self.REFS)
        criteria = sc.api_criteria(sheet, self.REFS)
        self.assertEqual(criteria[0]['id'], 'P1')
        self.assertEqual(criteria[0]['check']['body'], {'name': '개발팀'})
        self.assertEqual(criteria[1]['check']['body'], {'name': '홍길동', 'departmentId': 1})
        task = '사원 등록 API'
        requirement_contract.validate(task, {'version': 1, 'task': task, 'requirements': requirement_contract.requirements(task), 'criteria': criteria})
        self.assertIn('department_id BIGINT', sc.sheet_note(sheet))
        self.assertIn("lookup:{api:'/api/departments',label:'name'}", sc.sheet_note(sheet, screen=True))

    def test_bad_references_are_refused_with_the_choices(self):
        for field, message in [
                ({'name': 'departmentId', 'label': '부서', 'ref': {'path': '/api/teams', 'label': 'name'}}, 'not an existing registration API'),
                ({'name': 'departmentId', 'label': '부서', 'ref': {'path': '/api/departments', 'label': 'title'}}, 'ref label must be a field'),
                ({'name': 'department', 'label': '부서', 'ref': {'path': '/api/departments', 'label': 'name'}}, 'name it <target>Id')]:
            with self.assertRaisesRegex(ValueError, message):
                sc.validate_sheet(dict(self.EMPLOYEE, fields=[self.EMPLOYEE['fields'][0], field]), set(self.REFS), self.REFS)


class TypedFieldTests(unittest.TestCase):
    def test_numbers_and_dates_are_sent_and_compared_in_their_own_form(self):
        sheet = sc.validate_sheet({'path': '/api/orders', 'fields': [
            {'name': 'orderNo', 'label': '주문번호', 'required': True, 'sample': 'A-1'},
            {'name': 'quantity', 'label': '수량', 'required': False, 'type': 'number', 'sample': '10'},
            {'name': 'orderDate', 'label': '주문일', 'required': False, 'type': 'date', 'sample': '2026-01-15'}]})
        body = sc.api_criteria(sheet)[0]['check']['body']
        self.assertEqual(body, {'orderNo': 'A-1', 'quantity': 10, 'orderDate': '2026-01-15'})
        self.assertIn('quantity(수량, 숫자)', sc.sheet_note(sheet))
        for field, message in [({'name': 'quantity', 'label': '수량', 'type': 'number', 'sample': '열 개'}, 'whole number'),
                               ({'name': 'orderDate', 'label': '주문일', 'type': 'date', 'sample': '1월 15일'}, 'must look like')]:
            with self.assertRaisesRegex(ValueError, message):
                sc.validate_sheet({'path': '/api/orders', 'fields': [{'name': 'orderNo', 'label': '주문번호', 'required': True, 'sample': 'A-1'}, field]})


class ScreenChangeTests(unittest.TestCase):
    def test_existing_screen_change_uses_failing_screen_checks(self):
        import json, tempfile
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        root = Path(folder.name) / 'proj'
        (root / 'frontend/src/screens').mkdir(parents=True)
        (root / 'frontend/src/screens/Company.tsx').write_text("export const meta = { code: 'MST0002', title: '회사 등록' };\nawait apiFetch(`/api/companies?x`);")
        controller = root / 'backend/src/main/java/app/CompanyController.java'
        controller.parent.mkdir(parents=True); controller.write_text('@RequestMapping("/api/companies")')
        wanted = dict(SHEET, fields=[dict(SHEET['fields'][0]), dict(SHEET['fields'][1], required=True)])
        runner = SimpleNamespace(args=SimpleNamespace(task='회사 등록 화면에서 전화번호를 필수로 바꿔줘'), modes=['frontend', 'framework'], read=set(),
                                 h=SimpleNamespace(workspace=SimpleNamespace(root=root), log_event=Mock()),
                                 ask=lambda messages, tools: {'content': json.dumps(wanted, ensure_ascii=False)})
        with patch.object(sc, 'SHEETS', Path(folder.name) / 'sheets'), \
                patch.object(sc, '_screen_baseline', return_value=[{'id': 'C12', 'status': 'failed', 'reason': 'not visible'}]) as baseline:
            file = sc._sheet_file(root, '/api/companies'); file.parent.mkdir(parents=True)
            file.write_text(json.dumps(dict(SHEET, task='회사 등록 API'), ensure_ascii=False))
            built = sc.build(runner)
        self.assertEqual(built[1], 'standard-screen-change')
        self.assertEqual(baseline.call_args.args[1], '회사 등록')
        self.assertEqual(runner.read, {'frontend/src/screens/Company.tsx'})
        self.assertIn('전화번호', runner._field_sheet_note)
