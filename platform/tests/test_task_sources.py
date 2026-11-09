import sys
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
from task_sources import resolve_task_sources


class TaskSourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = 'frontend/src/screens/NamedItem.tsx'
        self.put(self.path)

    def put(self, path):
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text('fixture source')
        return file

    def test_unique_stem_filename_and_explicit_path_are_resolved(self):
        for task in ('NamedItem 조회 연결', '수정할 화면: NamedItem.tsx.', f'{self.path}에 조회 연결'):
            with self.subTest(task=task):
                self.assertEqual(resolve_task_sources(self.root, task), [self.path])

    def test_ambiguous_stem_does_not_select_first_file(self):
        other = 'backend/src/main/java/sample/NamedItem.java'
        self.put(other)
        self.assertEqual(resolve_task_sources(self.root, 'NamedItem 연결'), [])
        self.assertEqual(resolve_task_sources(self.root, 'NamedItem.tsx 연결'), [self.path])
        self.put('frontend/src/components/NamedItem.tsx')
        self.assertEqual(resolve_task_sources(self.root, 'NamedItem.tsx 연결'), [])
        self.assertEqual(resolve_task_sources(self.root, self.path), [self.path])

    def test_complete_filenames_followed_by_korean_prose(self):
        java = 'backend/src/main/java/sample/ReceiptController.java'
        sql = 'backend/src/main/resources/db/migration/V7__receipts.sql'
        self.put(java)
        self.put(sql)
        for task, expected in [('NamedItem.tsx에서 조회 연결', self.path),
                               ('ReceiptController.java에 수정 추가', java),
                               ('V7__receipts.sql은 유지', sql)]:
            with self.subTest(task=task):
                self.assertEqual(resolve_task_sources(self.root, task), [expected])
        self.assertEqual(resolve_task_sources(self.root, 'NamedItem에서 조회'), [])
        self.assertEqual(resolve_task_sources(self.root, 'NamedItem.tsxSuffix에 조회'), [])
        self.assertEqual(resolve_task_sources(self.root, 'NamedItem.tsx.bak에서 조회'), [])
        self.put('frontend/src/screens/NamedItem.config.tsx')
        self.assertEqual(resolve_task_sources(self.root, 'NamedItem.config에서 조회'), [])
        self.put('frontend/src/components/NamedItem.tsx')
        self.assertEqual(resolve_task_sources(self.root, 'NamedItem.tsx에서 조회'), [])

    def test_exact_boundaries_reject_other_identifiers_paths_and_missing_targets(self):
        for task in ('OtherNamedItem', 'NamedItemCopy', 'NamedItem.tsx.bak', '../NamedItem',
                     '/tmp/NamedItem.tsx', 'frontend/src/missing/NamedItem.tsx', 'MissingItem',
                     '이전NamedItem', 'NamedItemSuffix'):
            with self.subTest(task=task):
                self.assertEqual(resolve_task_sources(self.root, task), [])

    def test_scope_and_symlinks_do_not_supply_sources(self):
        for path in ('frontend/dist/Outside.tsx', 'backend/target/Outside.java',
                     'frontend/src/Config.json', 'backend/src/Unknown.txt'):
            self.put(path)
        (self.root / 'frontend/src/Alias.tsx').symlink_to(self.root / self.path)
        (self.root / 'frontend/src/linked').symlink_to(self.root / 'frontend/src/screens', target_is_directory=True)
        self.assertEqual(resolve_task_sources(self.root, 'Outside Config Unknown Alias linked'), [])
        self.assertEqual(resolve_task_sources(self.root, 'frontend/src/linked/NamedItem.tsx'), [])

    def test_explicit_paths_then_mentions_are_stable_and_deduplicated(self):
        java = 'backend/src/main/java/sample/QueryRows.java'
        sql = 'backend/src/main/resources/db/migration/V7__rows.sql'
        self.put(java)
        self.put(sql)
        task = f'NamedItem 및 QueryRows 수정. {sql}와 {self.path} 확인. NamedItem.tsx.'
        self.assertEqual(resolve_task_sources(self.root, task), [sql, self.path, java])

    def test_new_or_deleted_file_is_never_guessed(self):
        self.assertEqual(resolve_task_sources(self.root, 'NewItem 화면 생성'), [])
        (self.root / self.path).unlink()
        self.assertEqual(resolve_task_sources(self.root, 'NamedItem 화면 수정'), [])

    def test_unique_screen_title_resolves_natural_language_task(self):
        (self.root / self.path).write_text("export const meta = { code: 'MST0001', title: '품목 등록' };\n")
        self.assertEqual(resolve_task_sources(self.root, '품목 등록 화면의 조회 버튼 연결'), [self.path])
        self.assertEqual(resolve_task_sources(self.root, '등록 화면의 조회 버튼 연결'), [])
        other = 'frontend/src/screens/AnotherItem.tsx'
        self.put(other).write_text("export const meta = { title: '품목 등록' };\n")
        self.assertEqual(resolve_task_sources(self.root, '품목 등록 화면의 조회 버튼 연결'), [])
        self.assertEqual(resolve_task_sources(self.root, f'{self.path}의 조회 버튼 연결'), [self.path])


if __name__ == '__main__':
    unittest.main()
