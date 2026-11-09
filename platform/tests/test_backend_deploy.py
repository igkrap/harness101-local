"""Backend deploy: secrets stay in a 0600 env file, unchanged sources skip, the live container's networks are kept."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backend_deploy as d


class BackendDeployTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'backend/src/main').mkdir(parents=True)
        (self.root / 'backend/pom.xml').write_text('<project/>')
        (self.root / 'backend/src/main/A.java').write_text('class A {}')

    def tearDown(self):
        self.tmp.cleanup()

    def test_env_file_is_private_and_overrides_db_url(self):
        path = d.env_file(['A=1', 'DB_URL=jdbc:old', 'WORKSPACE_ADMIN_PASSWORD=x'], self.root, 'jdbc:clone')
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        lines = path.read_text().split()
        self.assertIn('DB_URL=jdbc:clone', lines)
        self.assertNotIn('DB_URL=jdbc:old', lines)

    def test_unchanged_sources_are_not_redeployed(self):
        state = self.root / 'state'
        (state / 'deploys').mkdir(parents=True)
        (state / 'deploys/current.json').write_text(json.dumps({'source_sha': d.source_hash(self.root / 'backend')}))
        with patch.object(d, 'build_jar', side_effect=AssertionError('must not build')):
            result = d.deploy(self.root, state)
        self.assertTrue(result['skipped'])

    def test_failed_step_is_reported_and_not_marked_live(self):
        state = self.root / 'state'
        with patch.object(d, 'flyway_versions', return_value=['1']), \
             patch.object(d, 'build_jar', return_value=self.root / 'app.jar'), \
             patch.object(d, 'backup', return_value=self.root / 'x.dump'), \
             patch.object(d, 'live_config', return_value={}), \
             patch.object(d, 'rehearse', side_effect=d.DeployError('clone failed')), \
             patch.object(d, 'swap', side_effect=AssertionError('must not swap')):
            result = d.deploy(self.root, state)
        self.assertFalse(result['success'])
        self.assertEqual(result['step'], 'rehearsal')
        self.assertFalse((state / 'deploys/current.json').exists())

    def test_published_container_joins_every_live_network(self):
        calls = []
        with patch.object(d, 'sh', side_effect=lambda cmd, **kw: calls.append(cmd) or ''):
            d.run_app('n', {'image': 'img', 'ports': {'8080/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '8083'}]},
                            'networks': ['mdi-internal', 'mdi-public']}, '/j.jar', '/e.env')
        self.assertIn('127.0.0.1:8083:8080', calls[0])
        self.assertEqual(calls[1], ['docker', 'network', 'connect', 'mdi-public', 'n'])


if __name__ == '__main__':
    unittest.main()
