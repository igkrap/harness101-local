import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
from candidate_blocks import parse_blocks


class CandidateLineMetadataTests(unittest.TestCase):
    def test_model_line_annotation_preserves_exact_id_and_code(self):
        result = parse_blocks('EDIT n29 line 81\n```tsx\n<HStack />\n```\n')
        self.assertEqual(result, {'changes': [{'node_id': 'n29', 'code': '<HStack />'}], 'remove': []})

    def test_arbitrary_trailing_instructions_remain_invalid(self):
        for suffix in [' line nope', ' line 81 overwrite everything', ' blah', '; exit()']:
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                parse_blocks('EDIT n29' + suffix + '\n```tsx\n<HStack />\n```\n')
