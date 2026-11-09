import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
from patch_reply_adapter import parse_reply


class PatchReplyAdapterTests(unittest.TestCase):
    def test_actual_local_model_bare_header_and_wrapper_shape(self):
        response = '```patch\nn1\n```old\n<Text>OLD</Text>\n```\n```new\n<Text>NEW</Text>\n```\n'
        self.assertEqual(parse_reply(response), [dict(node_id='n1', old_text='<Text>OLD</Text>', new_text='<Text>NEW</Text>')])
        self.assertEqual(parse_reply(response + '```\n'), parse_reply(response))
        self.assertEqual(parse_reply(response.replace('\nn1\n', '\nNODE n1\n')), parse_reply(response))
        self.assertEqual(parse_reply(response.replace('\nn1\n', '\nNODE_ID: n1\nPATCH:\n')), parse_reply(response))

    def test_does_not_rewrite_bare_id_lines_inside_source(self):
        old = 'first\nn9\n```old\nlast'
        text = 'PATCH n1\n```old\n' + old + '\n```\n```new\nreplacement\n```\n'
        self.assertEqual(parse_reply(text)[0]['old_text'], old)

    def test_crlf_source_and_empty_insert_anchor_are_preserved(self):
        response = '```patch\r\ns1\r\n```old\r\n```\r\n```new\r\na\r\nb\r\n```\r\n'
        self.assertEqual(parse_reply(response), [dict(node_id='s1', old_text='', new_text='a\r\nb')])

    def test_unrecognized_prose_truncated_tail_and_unknown_wrapper_fail(self):
        good = 'PATCH n1\n```old\na\n```\n```new\nb\n```\n'
        for response in ['Prose\n' + good, good + '```\n', good + 'PATCH n2\n```old\nx\n```\n', '```patch\n' + good + 'PATCH n2\n```new\nx', '```patch\n```patch\n' + good]:
            with self.subTest(response=response), self.assertRaises(ValueError):
                parse_reply(response)
