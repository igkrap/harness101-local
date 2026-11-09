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


    def test_history_lists_every_commit_and_undo_restores_the_file(self):
        project_git.ensure_repo(self.root)
        (self.root / 'frontend/src/a.ts').write_text('changed')
        sha = project_git.commit_now(self.root, '안내 문구 수정')
        commits = project_git.history(self.root)
        self.assertEqual([c['subject'] for c in commits], ['안내 문구 수정', '프로젝트 기준점'])
        self.assertEqual([c['kind'] for c in commits][1], 'platform')
        self.assertEqual(project_git.commit_files(self.root, sha)[0]['path'], 'frontend/src/a.ts')
        self.assertEqual(project_git.commit_file(self.root, sha, 'frontend/src/a.ts')['before'], 'a')
        project_git.revert(self.root, sha)
        self.assertEqual((self.root / 'frontend/src/a.ts').read_text(), 'a')
        self.assertEqual(project_git.history(self.root)[0]['subject'], '취소: 안내 문구 수정')

    def test_undo_refuses_with_unrecorded_edits_and_bad_paths(self):
        project_git.ensure_repo(self.root)
        sha = project_git.head(self.root)
        (self.root / 'frontend/src/a.ts').write_text('dirty')
        with self.assertRaises(RuntimeError):
            project_git.revert(self.root, sha)
        with self.assertRaises(ValueError):
            project_git.commit_file(self.root, sha, '../secret')
        with self.assertRaises(ValueError):
            project_git.switch(self.root, '-bad name')

if __name__ == '__main__':
    unittest.main()
