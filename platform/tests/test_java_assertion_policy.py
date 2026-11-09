import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-only/harness'))


class JavaAssertionPolicyTests(unittest.TestCase):
    before='@Test\nvoid old(){\n.andExpect(status().isOk())\n.andExpect(jsonPath("$.name").value("original"))\n}\n'

    def test_new_tests_and_assertions_can_be_added_around_existing_assertions(self):
        from java_assertion_policy import preserved
        addition='@Test\nvoid added(){\n.andExpect(status().isNotFound())\n}\n'
        self.assertTrue(preserved(self.before,self.before+addition,'Add PUT API tests'))
        self.assertTrue(preserved(self.before,addition+self.before,'Add PUT API tests'))
        after=self.before.replace('.andExpect(jsonPath', '.andExpect(jsonPath("$.quantity").value(7))\n.andExpect(jsonPath')
        self.assertTrue(preserved(self.before,after,'Add assertions'))

    def test_existing_assertion_or_test_removal_and_changes_remain_blocked(self):
        from java_assertion_policy import preserved
        for after in (self.before.replace('isOk','isBadRequest'),self.before.replace('$.name','$.other'),self.before.replace('original','changed'),self.before.replace('@Test',''),self.before.replace('.andExpect(status().isOk())','')):
            self.assertFalse(preserved(self.before,after,'Add PUT tests'),after)

    def test_java_source_path_and_validation_of_name_do_not_allow_value_changes(self):
        from java_assertion_policy import preserved
        goal='backend/src/test/java/com/example/localinventory/InventoryIntegrationTest.java에 이름 빈 문자열 검증 테스트 추가'
        self.assertFalse(preserved(self.before,self.before.replace('original','changed'),goal))

    def test_explicit_seed_rename_can_change_only_expected_string_values(self):
        from java_assertion_policy import preserved
        for goal in ('제조업체 예시로 변경','예시 변경','sample rename'):
            self.assertTrue(preserved(self.before,self.before.replace('original','changed'),goal))
            self.assertFalse(preserved(self.before,self.before.replace('$.name','$.other'),goal))

    def test_repeated_assertions_must_keep_multiplicity(self):
        from java_assertion_policy import preserved
        before=self.before.replace('.andExpect(status().isOk())','.andExpect(status().isOk())\n.andExpect(status().isOk())')
        self.assertFalse(preserved(before,self.before,'Add tests'))

    def test_actual_runtime_policy_delegates_and_allows_additional_assertions(self):
        from runtime_policy import preserve_java_assertions
        self.assertTrue(preserve_java_assertions(self.before,self.before+'@Test\n.andExpect(status().isNotFound())','Add tests'))
