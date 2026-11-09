"""Reject unsafe or incomplete decompositions before any stage edits sources."""
import copy
import sys
import unittest
import json
import tempfile
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
from divide_plan import validate


class DividePlanTests(unittest.TestCase):
    def setUp(self):
        self.contract = {'requirements': [{'id': 'R1'}, {'id': 'R2'}], 'criteria': [
            {'id': 'C1', 'requirement_id': 'R1', 'check': {'op': 'api'}},
            {'id': 'C2', 'requirement_id': 'R2', 'check': {'op': 'visible'}}]}
        self.raw = {'stages': [
            {'id': 'api', 'title': '조회 API', 'instructions': '조회 기능 구현', 'domain': 'backend',
             'criterion_ids': ['C1'], 'paths': ['backend/src/main/java/Query.java'], 'depends_on': []},
            {'id': 'screen', 'title': '조회 화면', 'instructions': 'API 결과 표시', 'domain': 'frontend',
             'criterion_ids': ['C2'], 'paths': ['frontend/src/screens/Query.tsx'], 'depends_on': ['api']}]}

    def test_validates_domains_without_mutating_plan(self):
        before = copy.deepcopy(self.raw)
        result = validate(self.contract, self.raw, ['backend', 'frontend'])
        self.assertEqual([s['id'] for s in result], ['api', 'screen'])
        self.assertEqual(self.raw, before)

    def test_topological_order(self):
        self.raw['stages'].reverse()
        result = validate(self.contract, self.raw, ['backend', 'frontend'])
        self.assertEqual([s['id'] for s in result], ['api', 'screen'])

    def test_missing_or_duplicate_criteria_rejected(self):
        for ids in ([], ['C1'], ['C2', 'C2'], ['unknown']):
            with self.subTest(ids=ids):
                plan = copy.deepcopy(self.raw)
                plan['stages'][1]['criterion_ids'] = ids
                with self.assertRaises(ValueError): validate(self.contract, plan, ['backend', 'frontend'])

    def test_disallowed_domain(self):
        with self.assertRaises(ValueError): validate(self.contract, self.raw, ['frontend'])

    def test_dependencies_rejected(self):
        for deps in (['unknown'], ['screen'], ['api', 'api']):
            with self.subTest(deps=deps):
                plan = copy.deepcopy(self.raw)
                plan['stages'][1]['depends_on'] = deps
                with self.assertRaises(ValueError): validate(self.contract, plan, ['backend', 'frontend'])
        self.raw['stages'][0]['depends_on'] = ['screen']
        with self.assertRaises(ValueError): validate(self.contract, self.raw, ['backend', 'frontend'])

    def test_unsafe_paths_rejected(self):
        for path in ('frontend/src/..', 'frontend/src/a/../../secret', '/tmp/a',
                     'frontend/src/a\\b', 'backend/src/main/A.java', 'frontend/src/./A.tsx'):
            with self.subTest(path=path):
                plan = copy.deepcopy(self.raw)
                plan['stages'][1]['paths'] = [path]
                with self.assertRaises(ValueError): validate(self.contract, plan, ['backend', 'frontend'])

    def test_reserved_integration_and_type_validation(self):
        for bad in ('integration', '', None, 1):
            with self.subTest(id=bad):
                plan = copy.deepcopy(self.raw)
                plan['stages'][1]['id'] = bad
                with self.assertRaises(ValueError): validate(self.contract, plan, ['backend', 'frontend'])

    def test_invalid_stage_and_dependency_types_are_validation_errors(self):
        for stage in (None, 'stage', [], 3):
            with self.subTest(stage=stage):
                with self.assertRaises(ValueError): validate(self.contract, {'stages':[stage,self.raw['stages'][1]]}, ['backend','frontend'])
        for deps in ([[]], [1], ['']):
            with self.subTest(deps=deps):
                plan=copy.deepcopy(self.raw);plan['stages'][1]['depends_on']=deps
                with self.assertRaises(ValueError):validate(self.contract,plan,['backend','frontend'])

    def test_duplicate_json_fields_rejected(self):
        from divide_plan import duplicate_hook
        with self.assertRaises(ValueError):json.loads('{"stages":[],"stages":[]}',object_pairs_hook=duplicate_hook)

    def test_stable_ready_order_and_normalized_lists_are_independent(self):
        plan=copy.deepcopy(self.raw)
        third=copy.deepcopy(plan['stages'][0]);third.update(id='aux',criterion_ids=['C3'],depends_on=[])
        self.contract['criteria'].append({'id':'C3','requirement_id':'R1','check':{'op':'api'}})
        plan['stages'].append(third)
        result=validate(self.contract,plan,['backend','frontend'])
        self.assertEqual([s['id'] for s in result],['api','screen','aux'])
        result[0]['paths'].append('backend/src/main/java/Another.java')
        self.assertEqual(len(plan['stages'][0]['paths']),1)

    def test_layout_only_request_has_no_backend_planner_domain(self):
        from divide_plan import create
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);messages_seen=[]
            contract=copy.deepcopy(self.contract)
            contract['criteria'][0]['check']={'op':'layout'}
            plan=copy.deepcopy(self.raw)
            plan['stages'][0].update(domain='frontend',paths=['frontend/src/screens/Query.tsx'])
            def ask(messages,tools):
                messages_seen.extend(messages)
                return {'content':json.dumps(plan)}
            runner=SimpleNamespace(requirement_gate=SimpleNamespace(frozen_contract=json.dumps(contract),
                contract_hash='frozen',artifact_dir=root),modes=['frontend','framework','backend'],ask=ask,
                h=SimpleNamespace(workspace=SimpleNamespace(root=root),log_event=lambda *args:None))
            create(runner)
            payload=json.loads(messages_seen[1]['content'])
            self.assertEqual(payload['allowed_domains'],['frontend'])
            self.assertNotIn('backend',payload['checks'])
            self.assertEqual(payload['criterion_domains'],{'C1':'frontend','C2':'frontend'})
            self.assertEqual(runner.modes,['frontend','framework','backend'])

    def test_empty_backend_setup_gets_explicit_remove_instruction(self):
        plan=copy.deepcopy(self.raw)
        plan['stages'][0]['criterion_ids']=[]
        with self.assertRaisesRegex(ValueError,'remove this stage entirely'):
            validate(self.contract,plan,['frontend','backend'])

    def test_model_stage_array_normalized_once_but_invalid_coverage_still_rejected(self):
        from divide_plan import create
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            runner=SimpleNamespace(requirement_gate=SimpleNamespace(frozen_contract=json.dumps(self.contract),artifact_dir=root,contract_hash='immutable'),h=SimpleNamespace(workspace=SimpleNamespace(root=root),log_event=Mock()),modes=['frontend','backend'],ask=Mock(return_value={'content':json.dumps(self.raw['stages'])}))
            self.assertEqual([s['id']for s in create(runner)],['api','screen']);runner.ask.assert_called_once()
            bad=copy.deepcopy(self.raw['stages']);bad[1]['criterion_ids']=['C1']
            runner.ask=Mock(return_value={'content':json.dumps(bad)})
            with self.assertRaises(RuntimeError):create(runner)
            self.assertEqual(runner.ask.call_count,4)

    def test_create_validates_before_persisting_and_logs_global_integration(self):
        from divide_plan import create
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            events, calls = [], []
            responses = [{'stages': []}, self.raw]
            def ask(messages, tools):
                calls.append(messages)
                return {'content': json.dumps(responses.pop(0))}
            runner = SimpleNamespace(
                requirement_gate=SimpleNamespace(frozen_contract=json.dumps(self.contract),
                    artifact_dir=root/'proof', contract_hash='immutable'),
                h=SimpleNamespace(workspace=SimpleNamespace(root=root),log_event=lambda k,d:events.append((k,d))),
                modes=['backend','frontend'],ask=ask)
            result=create(runner)
            self.assertEqual(len(result),2)
            self.assertEqual(len(calls),2)
            self.assertTrue((root/'proof/division-plan.json').is_file())
            self.assertEqual(events[-1][0],'autonomy.plan')
            self.assertEqual(events[-1][1]['source'],'divide-and-conquer')
            self.assertEqual(events[-1][1]['steps'][-1]['id'],'integration')


if __name__ == '__main__': unittest.main()
