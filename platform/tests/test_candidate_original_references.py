import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
from candidate_original_references import reference_fragments


class CandidateOriginalReferencesTests(unittest.TestCase):
    def test_hidden_original_handler_and_form_remain_read_only_references(self):
        original = [dict(id='n1', kind='VariableStatement', source='const save=()=>post();'), dict(id='n2', kind='JsxElement', source='<form><input aria-label="이름"/></form>'), dict(id='n3', kind='JsxElement', source='<VStack>obsolete placeholder</VStack>')]
        result = reference_fragments(original, [], dict(edits=[]))
        self.assertIn('const save=()=>post();', result)
        self.assertIn('이름', result)
        self.assertIn('NOT an active edit target', result)
        self.assertNotIn('obsolete placeholder', result)
        self.assertNotIn('n1', result)

    def test_skips_large_complete_fragment_and_includes_later_small_one(self):
        original = [dict(id='large', kind='VariableStatement', source='x' * 1000), dict(id='small', kind='VariableStatement', source='const ready=1;')]
        result = reference_fragments(original, [], dict(edits=[]), limit=150)
        self.assertLessEqual(len(result), 150)
        self.assertIn('const ready=1;', result)
        self.assertNotIn('x' * 100, result)

    def test_unchanged_active_code_does_not_duplicate_reference(self):
        node = dict(id='n1', kind='VariableStatement', source='const ready=1;')
        self.assertEqual(reference_fragments([node], [node], dict(edits=[])), '')
