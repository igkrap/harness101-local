"""A run that does not succeed puts back only the files it wrote itself."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from changes import Changes


class RestoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'project'
        (self.root / 'frontend/src').mkdir(parents=True)
        self.job = Path(self.tmp.name) / 'job'
        self.job.mkdir()

    def test_restores_own_edits_and_new_files(self):
        a = self.root / 'frontend/src/A.tsx'
        a.write_text('original')
        c = Changes(self.root, self.job)
        c.capture('frontend/src/A.tsx'); a.write_text('accepted but unverified'); c.note_written('frontend/src/A.tsx')
        c.capture('frontend/src/New.tsx'); (self.root / 'frontend/src/New.tsx').write_text('new'); c.note_written('frontend/src/New.tsx')
        self.assertEqual(sorted(c.restore_unverified()), ['frontend/src/A.tsx', 'frontend/src/New.tsx'])
        self.assertEqual(a.read_text(), 'original')
        self.assertFalse((self.root / 'frontend/src/New.tsx').exists())

    def test_leaves_files_changed_by_someone_else(self):
        a = self.root / 'frontend/src/A.tsx'
        a.write_text('original')
        c = Changes(self.root, self.job)
        c.capture('frontend/src/A.tsx'); a.write_text('run edit'); c.note_written('frontend/src/A.tsx')
        a.write_text('user edit afterwards')
        self.assertEqual(c.restore_unverified(), [])
        self.assertEqual(a.read_text(), 'user edit afterwards')
        self.assertTrue(any('outside this run' in w for w in c.warnings))


    def test_new_file_rolled_back_to_an_earlier_own_version_is_still_removed(self):
        new = self.root / 'frontend/src/New.tsx'
        c = Changes(self.root, self.job)
        c.capture('frontend/src/New.tsx'); new.write_text('first write'); c.note_written('frontend/src/New.tsx')
        c.capture('frontend/src/New.tsx'); new.write_text('failed edit'); c.note_written('frontend/src/New.tsx')
        new.write_text('first write')  # the harness rolled the failed patch back
        self.assertEqual(c.restore_unverified(), ['frontend/src/New.tsx'])
        self.assertFalse(new.exists())

if __name__ == '__main__':
    unittest.main()
