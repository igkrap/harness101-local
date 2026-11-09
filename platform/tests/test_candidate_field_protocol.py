import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
from candidate_field_protocol import normalize_field_fences


class FieldProtocolTests(unittest.TestCase):
    def test_old_and_new_are_separate_code_blocks(self):
        text = 'NODE_ID: n1\nEXACT_OLD_SUBSTRING:\n```tsx\n<Text>OLD</Text>\n```\nREPLACEMENT_SUBSTRING:\n```tsx\n<Text>NEW</Text>\n```\n'
        expected = 'NODE_ID: n1\n```old\n<Text>OLD</Text>\n```\n```new\n<Text>NEW</Text>\n```\n'
        self.assertEqual(normalize_field_fences(text), expected)

    def test_canonical_input_is_unchanged(self):
        text = 'PATCH n1\n```old\na\n```\n```new\nb\n```\n'
        self.assertEqual(normalize_field_fences(text), text)

    def test_labels_inside_source_are_preserved_with_crlf(self):
        text = 'OLD_TEXT:\r\n```tsx\r\nNEW_TEXT:\r\n새 코드 🌊\r\n```\r\nNEW_TEXT:\r\n```tsx\r\n새 값\r\n```\r\n'
        expected = '```old\r\nNEW_TEXT:\r\n새 코드 🌊\r\n```\r\n```new\r\n새 값\r\n```\r\n'
        self.assertEqual(normalize_field_fences(text), expected)

    def test_empty_new_field_and_outer_wrapper_are_preserved(self):
        text = '```patch\nOLD:\n```ts\nconst old=1;\n```\nNEW:\n```ts\n```\n```\n'
        expected = '```patch\n```old\nconst old=1;\n```\n```new\n```\n```\n'
        self.assertEqual(normalize_field_fences(text), expected)

    def test_bad_or_truncated_field_raises_instead_of_silently_reusing_draft(self):
        for text in ['OLD:\n', 'OLD:\nnot a fence\n', 'OLD:\n```tsx\nno closing', 'NEW_TEXT:\n```tsx\nno closing', '```old\nno closing']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                normalize_field_fences(text)

    def test_aliases_and_blank_metadata_lines_are_normalized(self):
        self.assertEqual(normalize_field_fences('before:\n\n```js\na\n```\nafter:\n```js\nb\n```\n'), '```old\na\n```\n```new\nb\n```\n')

    def test_empty_new_field_without_outer_wrapper(self):
        self.assertEqual(normalize_field_fences('OLD_TEXT\n```tsx\na\n```\nNEW_TEXT\n```tsx\n```\n'), '```old\na\n```\n```new\n```\n')

    def test_inline_backticks_do_not_end_a_field(self):
        body = '<pre>\nliteral```\nNEW_TEXT:\ncontent\n</pre>\n'
        text = 'OLD_TEXT:\n```tsx\n' + body + '```\nNEW_TEXT:\n```tsx\nnew\n```\n'
        self.assertEqual(normalize_field_fences(text), '```old\n' + body + '```\n```new\nnew\n```\n')

    def test_generic_fence_inside_canonical_source_is_not_a_closing_fence(self):
        text = 'PATCH n1\n```old\n<pre>\n```tsx\nNEW_TEXT:\ncontent\n</pre>\n```\n```new\nnew\n```\n'
        self.assertEqual(normalize_field_fences(text), text)
