import sys
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from checker_fingerprint import check_signature


class CheckerFingerprintTests(unittest.TestCase):
    def test_task_checker_and_typescript_rules_invalidate_failure_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / 'runtime'
            check = runtime / 'tests/framework_cases/flow.cjs'
            check.parent.mkdir(parents=True)
            check.write_text('old check')
            first = check_signature(root, runtime, 'task')
            self.assertEqual(first, check_signature(root, runtime, 'task'))
            self.assertNotEqual(first, check_signature(root, runtime, 'other task'))
            check.write_text('new check with more precise feedback')
            second = check_signature(root, runtime, 'task')
            self.assertNotEqual(first, second)
            config = root / 'frontend/tsconfig.json'
            config.parent.mkdir()
            config.write_text('{"strict":true}')
            self.assertNotEqual(second, check_signature(root, runtime, 'task'))
