"""Server-side chat storage survives browser changes and rejects unsafe ids."""
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chat_store


class ChatStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = SimpleNamespace(state=Path(self.tmp.name))

    def conv(self, title='대화', updated=1):
        return {'title': title, 'mode': 'chat', 'updatedAt': updated,
                'turns': [{'id': 'a', 'role': 'user', 'content': '안녕'}, {'id': 'b', 'role': 'assistant', 'content': '네'}]}

    def test_save_list_get_delete_roundtrip(self):
        chat_store.save_chat(self.app, 'abc123', self.conv('첫', 1))
        chat_store.save_chat(self.app, 'def456', self.conv('둘', 2))
        listed = chat_store.list_chats(self.app)['conversations']
        self.assertEqual([c['id'] for c in listed], ['def456', 'abc123'])
        self.assertEqual(listed[0]['count'], 2)
        self.assertEqual(chat_store.get_chat(self.app, 'abc123')['turns'][0]['content'], '안녕')
        chat_store.delete_chat(self.app, 'abc123')
        self.assertEqual([c['id'] for c in chat_store.list_chats(self.app)['conversations']], ['def456'])

    def test_rejects_traversal_ids_and_bad_shapes(self):
        for bad in ('../x', 'ABCDEF', 'a/b/c1', '', 'x' * 60):
            with self.assertRaises(ValueError):
                chat_store.save_chat(self.app, bad, self.conv())
        for body in ({}, {**self.conv(), 'mode': 'edit'}, {**self.conv(), 'turns': [{'role': 'system', 'content': 'x'}]}):
            with self.assertRaises(ValueError):
                chat_store.save_chat(self.app, 'abc123', body)
        self.assertEqual(list((self.app.state / 'chats').glob('*')), [])


if __name__ == '__main__':
    unittest.main()
