import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
from final_edit_group import select_final_edit_blocks
from candidate_blocks import parse_blocks


def edit(node, code):
    return f'EDIT {node}\n```tsx\n{code}\n```\n'


class FinalEditGroupTests(unittest.TestCase):
    def test_selects_final_draft_with_all_companions(self):
        response = edit('n1', '<Text>bad</Text>') + '\nWait, correct the handler too.\n' + edit('n2', 'const save=()=>1;') + '\n' + edit('n1', '<Text>fixed</Text>')
        parsed = parse_blocks(select_final_edit_blocks(response))
        self.assertEqual(parsed['changes'], [dict(node_id='n2', code='const save=()=>1;'), dict(node_id='n1', code='<Text>fixed</Text>')])

    def test_keeps_exact_unicode_and_crlf_source(self):
        block = 'EDIT n1 line 12\r\n```tsx\r\n<Text>한글 🌊</Text>\r\n```\r\n'
        self.assertEqual(parse_blocks(select_final_edit_blocks('Draft:\r\n' + block))['changes'][0]['code'], '<Text>한글 🌊</Text>')

    def test_never_falls_back_to_old_draft_if_final_block_is_truncated(self):
        for tail in ['EDIT n2\n```tsx\n<Text>', 'EDIT n2\n', 'EDIT n2\ninvalid fence']:
            with self.subTest(tail=tail), self.assertRaises(ValueError):
                select_final_edit_blocks(edit('n1', '<Text>stale</Text>') + '\nWait.\n' + tail)

    def test_does_not_extract_headers_from_opaque_prose_fences(self):
        response = '```text\nEDIT n99\nnot a real edit\n```\n' + edit('n1', '<Text>final</Text>')
        self.assertEqual([c['node_id'] for c in parse_blocks(select_final_edit_blocks(response))['changes']], ['n1'])

    def test_duplicate_ids_within_final_group_and_invalid_headers_still_fail(self):
        for text in [edit('n1', '<Text>A</Text>') + edit('n1', '<Text>B</Text>'), edit('n1', '<Text>A</Text>') + 'EDIT n2 garbage\n', 'No actual edit']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                select_final_edit_blocks(text)
