import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from unittest.mock import patch
import subprocess
import xml.etree.ElementTree as ET

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-only/harness'))


class JunitAddedGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.suite='demo.InventoryTest'
        self.source=self.root/'backend/src/test/java/demo/InventoryTest.java'
        self.source.parent.mkdir(parents=True)
        self.source.write_text('package demo; class InventoryTest { /* original five tests */ }')
        self.main=self.root/'backend/src/main/java/demo/Inventory.java'
        self.main.parent.mkdir(parents=True);self.main.write_text('package demo; class Inventory {}')
        self.report=self.root/'backend/target/surefire-reports/TEST-demo.InventoryTest.xml'
        self.report.parent.mkdir(parents=True)
        self.write_report(5)
        from junit_added_gate import capture_baseline
        self.baseline=capture_baseline(self.root)
        self.criteria=[dict(id='C1',check=dict(op='junit_added',suite=self.suite,count=3,preserve_main=True))]
        self.output=self.root/'evidence'
        self.checker=SimpleNamespace(workspace=SimpleNamespace(root=self.root),run_check=Mock(side_effect=self.run_tests))

    def write_report(self,count,suite=None,skipped=0,failures=0,errors=0,declared=999):
        suite=suite or self.suite
        report=self.report.parent/f'TEST-{suite}.xml'
        xml=ET.Element('testsuite',name=suite,tests=str(declared))
        for i in range(count):
            tc=ET.SubElement(xml,'testcase',name=f'test{i}',classname=suite)
            if i<skipped:ET.SubElement(tc,'skipped')
            if i<failures:ET.SubElement(tc,'failure')
            if i<errors:ET.SubElement(tc,'error')
        ET.ElementTree(xml).write(report,encoding='utf-8')
        return report

    def run_tests(self,mode):
        self.assertEqual(mode,'backend');self.write_report(8)
        return dict(success=True,stdout='',stderr='')

    def add_source(self):
        self.source.write_text(self.source.read_text()+'\n// additional test implementation\n')

    def verify(self):
        from junit_added_gate import verify
        return verify(self.checker,self.criteria,self.baseline,self.output)

    def test_real_report_counts_and_changed_source_pass_without_mutating_inputs(self):
        self.add_source();before=copy.deepcopy(self.baseline);source=self.source.read_bytes()
        result=self.verify()
        self.assertTrue(result['success'],result)
        self.checker.run_check.assert_called_once_with('backend')
        evidence=result['results'][0]['evidence']
        self.assertEqual(evidence['baseline_tests'],5)
        self.assertEqual(evidence['executed'],8)
        self.assertEqual(evidence['added_tests'],3)
        self.assertTrue(Path(evidence['report']).is_file())
        self.assertEqual(self.baseline,before)
        self.assertEqual(self.source.read_bytes(),source)

    def test_source_unchanged_cannot_claim_test_addition(self):
        result=self.verify()
        self.assertFalse(result['success']);self.assertIn('source',result['results'][0]['reason'].lower())

    def test_declared_test_attribute_cannot_fake_additional_executed_cases(self):
        self.add_source()
        def run(mode):self.write_report(5,declared=1000);return dict(success=True)
        self.checker.run_check.side_effect=run
        result=self.verify();self.assertFalse(result['success'])
        self.assertIn('5',result['results'][0]['reason'])

    def test_skipped_tests_do_not_count_as_added_execution(self):
        self.add_source()
        def run(mode):self.write_report(8,skipped=3);return dict(success=True)
        self.checker.run_check.side_effect=run
        self.assertFalse(self.verify()['success'])

    def test_empty_failure_or_error_elements_cannot_be_lost_to_element_truthiness(self):
        self.add_source()
        for kwargs in ({'failures':1},{'errors':1}):
            def run(mode):self.write_report(8,**kwargs);return dict(success=True)
            self.checker.run_check.side_effect=run
            self.assertFalse(self.verify()['success'],kwargs)

    def test_stale_and_wrong_suite_reports_are_unverified(self):
        self.add_source()
        def stale(mode):
            self.write_report(8);os.utime(self.report,(1,1));return dict(success=True)
        self.checker.run_check.side_effect=stale
        self.assertEqual(self.verify()['results'][0]['status'],'unverified')
        def wrong(mode):
            self.write_report(8);tree=ET.parse(self.report);tree.getroot().set('name','wrong.Suite');tree.write(self.report);return dict(success=True)
        self.checker.run_check.side_effect=wrong
        self.assertEqual(self.verify()['results'][0]['status'],'unverified')

    def test_production_changes_are_rejected_for_test_only_requirement(self):
        self.add_source();self.main.write_text('package demo; class Inventory { int changed; }')
        self.assertFalse(self.verify()['success'])
        self.criteria[0]['check']['preserve_main']=False
        self.assertTrue(self.verify()['success'])

    def test_failed_registered_check_cannot_pass_with_good_looking_report(self):
        self.add_source();self.write_report(8)
        self.checker.run_check.side_effect=None;self.checker.run_check.return_value=dict(success=False,stdout='COMPILATION ERROR',stderr='')
        self.assertFalse(self.verify()['success'])

    def test_unknown_existing_suite_baseline_is_not_guessed_as_zero(self):
        self.add_source();self.baseline['suites'][self.suite]['executed']=None
        self.assertEqual(self.verify()['results'][0]['status'],'unverified')

    def test_new_suite_starts_at_zero_and_multiple_criteria_run_maven_once(self):
        self.add_source();self.baseline['suites'].pop(self.suite)
        self.criteria.append(dict(id='C2',check=dict(op='junit_added',suite=self.suite,count=1)))
        result=self.verify();self.assertTrue(result['success'],result)
        self.checker.run_check.assert_called_once()

    def test_spec_rejects_boolean_count_unknown_fields_and_path_shaped_suite(self):
        from junit_added_gate import validate_spec
        for bad in ({'count':True},{'count':0},{'suite':'../outside'},{'suite':'demo..Test'},{'suite':''},{'suite':'/private/Secret'},{'extra':'x'},{'preserve_main':'true'}):
            check=dict(self.criteria[0]['check']);check.update(bad)
            with self.subTest(bad=bad),self.assertRaises(ValueError):validate_spec(check)

    def test_source_symlink_is_not_followed(self):
        self.add_source();outside=self.root.parent/(self.root.name+'-outside.java');outside.write_text('outside')
        self.addCleanup(lambda:outside.unlink(missing_ok=True))
        self.source.unlink();self.source.symlink_to(outside)
        self.assertFalse(self.verify()['success'])

    def test_contract_supports_executable_junit_addition_instead_of_manual(self):
        import requirement_contract
        criterion=dict(id='C1',requirement_id='R1',description='add tests',check=self.criteria[0]['check'])
        result=requirement_contract.validate('Add JUnit tests',{'criteria':[criterion]})
        self.assertEqual(result['criteria'][0]['check']['op'],'junit_added')
        self.assertIn('junit_added',requirement_contract.prompt('Add JUnit tests'))

    def make_gate(self):
        import requirement_contract
        from verification_gate import Gate
        runner=SimpleNamespace(modes=['backend'],args=SimpleNamespace(task='Add tests'),accepted=True,h=SimpleNamespace(workspace=SimpleNamespace(root=self.root),checker=self.checker,log_event=Mock()))
        gate=Gate(runner)
        criteria=[dict(self.criteria[0],requirement_id='R1',description='additional executed tests')]
        contract=requirement_contract.validate(runner.args.task,{'criteria':criteria})
        gate.frozen_contract=json.dumps(contract)
        gate.contract_hash=requirement_contract.digest(contract)
        gate._junit_baseline=self.baseline
        gate.artifact_dir=self.root/'gate-evidence'
        return gate

    def test_completion_gate_routes_native_junit_without_browser_and_keeps_source_mutation_check(self):
        gate=self.make_gate();self.add_source()
        with patch('verification_gate.subprocess.run',wraps=subprocess.run)as calls:
            result=gate.verify()
        self.assertTrue(result['success'],result)
        self.assertTrue(any(r['id']=='system:mutation'and r['status']=='passed'for r in result['results']))
        self.assertFalse(any('react_layout_inspector.cjs'in str(c.args)for c in calls.call_args_list))

    def test_completion_gate_rejects_failed_executor_even_if_result_items_claim_passed(self):
        gate=self.make_gate()
        with patch('junit_added_gate.verify',return_value={'success':False,'results':[dict(id='C1',status='passed',reason='misleading')]}):
            result=gate._probe([dict(self.criteria[0],requirement_id='R1',description='tests')])
        self.assertFalse(result['success'])
