"""Project history: baseline before a run, one model commit per successful run, nothing when unchanged."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import project_git


def log(root):
    return subprocess.run(['git', 'log', '--format=%an|%s'], cwd=root, capture_output=True, text=True).stdout.splitlines()


class ProjectGitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'frontend/src').mkdir(parents=True)
        (self.root / 'frontend/src/a.ts').write_text('a')
        (self.root / 'harness').mkdir()
        (self.root / 'harness/h.py').write_text('x')

    def tearDown(self):
        self.tmp.cleanup()

    def test_run_lifecycle(self):
        self.assertIsNone(project_git.before_run(self.root, '화면'))  # first call creates the repo with a baseline
        tracked = subprocess.run(['git', 'ls-files'], cwd=self.root, capture_output=True, text=True).stdout.split()
        self.assertIn('frontend/src/a.ts', tracked)
        self.assertNotIn('harness/h.py', tracked)
        (self.root / 'frontend/src/a.ts').write_text('person edit')
        self.assertTrue(project_git.before_run(self.root, '회사 화면'))
        (self.root / 'frontend/src/b.ts').write_text('model edit')
        sha = project_git.after_run(self.root, {'id': 'job1', 'goal': '회사 등록 화면', 'model': 'qwen',
                                                'queue': {'id': 'q', 'index': 1, 'total': 2, 'goal': '회사'}})
        self.assertTrue(sha)
        self.assertEqual(log(self.root)[0], 'Local model (qwen)|회사 등록 화면')
        self.assertIsNone(project_git.after_run(self.root, {'id': 'job2', 'goal': 'x'}))
        self.assertEqual(len(log(self.root)), 3)


if __name__ == '__main__':
    unittest.main()
