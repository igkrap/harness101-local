import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fixed_acceptance_registry import load_fixed_acceptance
from server import Platform


class FixedAcceptanceRegistryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / 'local-only'
        self.project.mkdir()
        (self.root / 'platform/acceptance').mkdir(parents=True)
        (self.root / 'platform/tests').mkdir()
        self.script = self.root / 'platform/tests/oracle.cjs'
        self.script.write_text('process.exitCode = 0;')
        self.manifest = self.root / 'platform/acceptance/example-v1.json'
        self.definition = {'id': 'example-v1', 'task': 'Create the screen', 'project': 'local-only',
            'script': 'platform/tests/oracle.cjs', 'script_sha256': hashlib.sha256(self.script.read_bytes()).hexdigest(),
            'cases': ['selection', 'save']}
        self.write()

    def write(self, **changes):
        self.manifest.write_text(json.dumps(dict(self.definition, **changes)))

    def load(self, identifier='example-v1', task='Create the screen', project=None):
        return load_fixed_acceptance(identifier, task, project or self.project, repo_root=self.root)

    def test_registered_definition_freezes_project_script_and_cases(self):
        result = self.load()
        self.assertEqual(result['project_root'], str(self.project))
        self.assertEqual(result['script'], str(self.script))
        self.assertEqual(result['cases'], ['selection', 'save'])
        self.assertEqual(result['script_sha256'], self.definition['script_sha256'])

    def test_unknown_id_task_project_or_changed_script_cannot_launch(self):
        for identifier in ['../example-v1', '/example-v1', 'absent', {}, None]:
            with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                self.load(identifier=identifier)
        with self.assertRaises(ValueError): self.load(task='Different task')
        with self.assertRaises(ValueError): self.load(project=self.root)
        self.script.write_text('changed verifier')
        with self.assertRaises(ValueError): self.load()

    def test_invalid_manifest_paths_case_sets_and_hashes_are_rejected(self):
        cases = [dict(script='../oracle.cjs'), dict(script='local-only/oracle.cjs'),
            dict(script='/tmp/oracle.cjs'), dict(project='..'), dict(id='another'),
            dict(script_sha256='0' * 64), dict(cases=[]), dict(cases=['same', 'same']),
            dict(cases=[None]), dict(cases='save')]
        for changes in cases:
            self.write(**changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError): self.load()

    def test_manifest_and_script_symlinks_are_rejected(self):
        original = self.manifest.read_bytes()
        actual = self.root / 'definition.json'
        actual.write_bytes(original)
        self.manifest.unlink()
        self.manifest.symlink_to(actual)
        with self.assertRaises(ValueError): self.load()
        self.manifest.unlink(); self.manifest.write_bytes(original)
        actual_script = self.root / 'oracle.cjs'
        actual_script.write_bytes(self.script.read_bytes())
        self.script.unlink(); self.script.symlink_to(actual_script)
        with self.assertRaises(ValueError): self.load()



if __name__ == '__main__':
    unittest.main()
