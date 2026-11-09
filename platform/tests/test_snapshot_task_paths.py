import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
from call_budget import snapshot


class SnapshotTaskPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def put(self, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def runner(self, task):
        def safe_path(path):
            target = (self.root / path).resolve()
            if self.root not in target.parents:
                raise ValueError('Outside workspace')
            return target
        return SimpleNamespace(args=SimpleNamespace(task=task), steps=[], step=0,
            messages=[], read={'frontend/src/App.tsx'},
            h=SimpleNamespace(workspace=SimpleNamespace(safe_path=safe_path)))

    def test_real_korean_task_selects_created_screen_and_workspace_before_shell(self):
        task = json.loads((Path(__file__).resolve().parents[1] / 'acceptance/equipment-loans-v1.json').read_text())['task']
        self.put('frontend/src/screens/EquipmentLoans.tsx', 'generated candidate sentinel')
        self.put('frontend/src/workspace.json', '{"sentinel":true}')
        self.put('frontend/src/App.tsx', 'unrelated shell sentinel')
        text, paths = snapshot(self.runner(task))
        self.assertEqual(paths, {'frontend/src/screens/EquipmentLoans.tsx', 'frontend/src/workspace.json'})
        self.assertIn('generated candidate sentinel', text)
        self.assertNotIn('unrelated shell sentinel', text)

    def test_korean_particles_quotes_and_unicode_filenames(self):
        path = 'frontend/src/screens/조회.tsx'
        self.put(path, 'exact source')
        for suffix in ('에', '를', '에서', '`', "'", ','):
            with self.subTest(suffix=suffix):
                self.assertIn(path, snapshot(self.runner(path + suffix + ' 수정'))[1])

    def test_filename_continuations_are_not_misread_as_shorter_file(self):
        path = 'frontend/src/A.tsx'
        self.put(path, 'wrong source')
        for suffix in ('.bak', 'Other', '_backup', '-backup', '/child'):
            with self.subTest(suffix=suffix):
                self.assertNotIn(path, snapshot(self.runner(path + suffix))[1])

    def test_unknown_extensions_and_exact_read_paths_keep_legacy_behavior(self):
        self.put('backend/custom.conf', 'config')
        self.assertIn('backend/custom.conf', snapshot(self.runner('Change backend/custom.conf'))[1])
