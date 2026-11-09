import errno
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import trial_safety as safety


class TrialSafetyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / 'evidence'
        self.output.mkdir()
        self.evidence = safety.TrialEvidence(self.output)

    def terminal(self, **updates):
        return dict({'id': 'owned', 'status': 'stopped', 'pid': 23456,
                     'exit_code': 0, 'finished_at': 'now'}, **updates)

    def test_preflight_requires_two_gib_and_atomic_failure_preserves_previous_evidence(self):
        with patch.object(safety.shutil, 'disk_usage', return_value=Mock(free=2 * 1024 ** 3 - 1)):
            with self.assertRaises(OSError): safety.require_free_space(self.root)
        with patch.object(safety.shutil, 'disk_usage', return_value=Mock(free=2 * 1024 ** 3)):
            self.assertEqual(safety.require_free_space(self.root), 2 * 1024 ** 3)
        destination = self.output / 'progress.json'
        destination.write_text('previous')
        with patch.object(safety.os, 'fsync', side_effect=OSError(errno.ENOSPC, 'disk full')):
            self.assertFalse(self.evidence.json(destination, {'next': True}))
        self.assertEqual(destination.read_text(), 'previous')
        self.assertEqual(list(self.output.iterdir()), [destination])

    def test_enospc_logging_does_not_precede_or_prevent_stop_and_restoration(self):
        self.evidence.arm_reserve(8192)
        order = []
        current = self.terminal(status='running', exit_code=None, finished_at=None)
        def stop(identifier):
            self.assertFalse(self.evidence.reserve.exists())
            order.append('stop')
            current.update(self.terminal())
        def restore():
            order.append('restore')
            return {'completed_sources_restored': True, 'prior_state_restored': True}
        with patch.object(safety, 'atomic_write', side_effect=OSError(errno.ENOSPC, 'disk full')):
            self.assertFalse(self.evidence.text(self.output / 'progress.json', 'progress'))
            result = safety.cleanup_trial(self.evidence, 'owned', True, lambda _: current, stop,
                                          restore, timeout=1, interval=0, probe=lambda _: False)
            self.assertFalse(self.evidence.json(self.output / 'result.json', result))
        self.assertEqual(order, ['stop', 'restore'])
        self.assertTrue(result['completed_sources_restored'])

    def test_failed_native_stop_live_job_blocks_restore_without_killing_any_pid(self):
        restore = Mock()
        stop = Mock(side_effect=OSError(errno.ENOSPC, 'stop metadata unavailable'))
        with patch.object(safety.os, 'kill') as kill, patch.object(safety.os, 'killpg') as killpg:
            result = safety.cleanup_trial(self.evidence, 'owned', True,
                lambda _: self.terminal(status='running'), stop, restore, timeout=0, probe=lambda _: True)
        stop.assert_called_once_with('owned')
        restore.assert_not_called()
        kill.assert_not_called(); killpg.assert_not_called()
        self.assertIn('restore_blocked', result)
        self.assertIn('stop_error', result['cleanup_job'])

    def test_unproven_terminal_interrupted_and_unknown_launch_never_restore(self):
        for status, alive in [('stopped', True), ('interrupted', False), ('stopping', False), ('stopped', None)]:
            with self.subTest(status=status, alive=alive):
                restore = Mock()
                result = safety.cleanup_trial(self.evidence, 'owned', True,
                    lambda _: self.terminal(status=status), Mock(), restore, timeout=0, probe=lambda _: alive)
                restore.assert_not_called()
                self.assertIn('restore_blocked', result)
        restore = Mock(); stop = Mock()
        result = safety.cleanup_trial(self.evidence, None, True, Mock(), stop, restore)
        stop.assert_not_called(); restore.assert_not_called()
        self.assertIn('Launch outcome is unknown', result['restore_blocked'])

    def test_normal_restoration_removes_new_sources_and_restores_prior_bytes(self):
        app = self.root / 'app'; app.mkdir()
        (app / 'old.tsx').write_bytes(b'changed')
        (app / 'new.tsx').write_bytes(b'created')
        state = self.root / 'state.json'; state.write_bytes(b'cleared')
        absent = self.root / 'previously-absent'; absent.write_bytes(b'created')
        collect = lambda: {p.name: p.read_bytes() for p in app.iterdir()}
        result = safety.cleanup_trial(self.evidence, 'owned', True, lambda _: self.terminal(), Mock(),
            lambda: safety.restore_snapshot(app, {'old.tsx': b'original'},
                {state: b'prior', absent: None}, collect), timeout=0, probe=lambda _: False)
        self.assertTrue(result['completed_sources_restored'])
        self.assertTrue(result['prior_state_restored'])
        self.assertEqual(collect(), {'old.tsx': b'original'})
        self.assertEqual(state.read_bytes(), b'prior')
        self.assertFalse(absent.exists())

    def test_source_write_failure_still_attempts_other_sources_and_prior_state(self):
        app = self.root / 'app'; app.mkdir()
        for name in ('a', 'b'): (app / name).write_bytes(b'changed')
        prior = self.root / 'prior'; prior.write_bytes(b'changed')
        original = safety.atomic_write
        def write(path, raw):
            if Path(path).name == 'a': raise OSError(errno.ENOSPC, 'disk full')
            original(path, raw)
        with patch.object(safety, 'atomic_write', side_effect=write):
            result = safety.restore_snapshot(app, {'a': b'a', 'b': b'b'}, {prior: b'prior'},
                lambda: {p.name: p.read_bytes() for p in app.iterdir()})
        self.assertFalse(result['completed_sources_restored'])
        self.assertTrue(result['prior_state_restored'])
        self.assertEqual((app / 'b').read_bytes(), b'b')

    def supervisor(self, fail_progress=False):
        spec = importlib.util.spec_from_file_location('trial_supervisor_fixture', '/tmp/gemma-component-trial-fixed.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        app = self.root / 'local-only'
        for folder in ('frontend/src', 'backend/src', 'harness/state'):
            (app / folder).mkdir(parents=True, exist_ok=True)
        original = app / 'frontend/src/Original.tsx'; original.write_bytes(b'original')
        prior = app / 'harness/state/failures.json'; prior.write_bytes(b'[{"prior":true}]')
        module.ROOT = self.root; module.APP = app; module.STATE = self.root / 'state'; module.STATE.mkdir()
        module.ORACLE = self.root / 'oracle.cjs'; module.ORACLE.write_text('frozen oracle')
        module.frozen = lambda: {'oracle': 'frozen'}
        module.events = lambda _: [{'type': 'model.request', 'seq': 1, 'data': {}}]
        module.require_free_space = Mock(return_value=32 * 1024 ** 3)
        current = self.terminal(id='a' * 32, status='running' if fail_progress else 'succeeded',
                                exit_code=None if fail_progress else 0,
                                finished_at=None if fail_progress else 'now')
        calls = []
        def request(path, body=None):
            calls.append(path)
            if path == '/api/state': return {'token': 'fixture-token', 'active': None, 'external': []}
            if path == '/api/jobs':
                jobdir = module.STATE / current['id']; jobdir.mkdir()
                (jobdir / 'job.json').write_text(json.dumps(current))
                target = app / module.TARGET; target.parent.mkdir(exist_ok=True)
                target.write_text('BusinessWorkspace QueryPanel RecordGrid')
                original.write_bytes(b'model change')
                return dict(current)
            current.update(status='stopped', exit_code=0, finished_at='now')
            (module.STATE / current['id'] / 'job.json').write_text(json.dumps(current))
            return dict(current)
        module.request = request
        real_write = safety.atomic_write
        def write(path, raw):
            if fail_progress and Path(path).name in ('progress.json', 'supervisor-error.log', 'result.json'):
                raise OSError(errno.ENOSPC, 'simulated disk full')
            # Do not alter the real active-trial pointer in an offline test.
            if str(path) == '/tmp/gemma-component-trial-current.txt': return
            real_write(path, raw)
        with patch.object(safety, 'atomic_write', side_effect=write), \
                patch.object(safety.os, 'kill', side_effect=ProcessLookupError), \
                patch.object(safety.os, 'killpg', side_effect=ProcessLookupError), \
                patch.object(safety.time, 'sleep'), \
                patch.object(module.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as check, \
                patch('builtins.print'):
            code = module.main()
        self.assertEqual(original.read_bytes(), b'original')
        self.assertEqual(prior.read_bytes(), b'[{"prior":true}]')
        self.assertFalse((app / module.TARGET).exists())
        self.assertFalse(list(module.STATE.rglob('.cleanup-reserve')))
        return code, calls, check.call_count, module.STATE

    def test_actual_supervisor_enospc_progress_error_log_and_final_result_still_cleans_up(self):
        code, calls, checks, _ = self.supervisor(fail_progress=True)
        self.assertEqual(code, 1)
        self.assertEqual(calls, ['/api/state', '/api/jobs', '/api/jobs/' + 'a' * 32 + '/stop'])
        self.assertEqual(checks, 0)

    def test_actual_supervisor_normal_trial_keeps_both_checks_and_restores(self):
        code, calls, checks, state = self.supervisor()
        self.assertEqual(code, 0)
        self.assertEqual(calls, ['/api/state', '/api/jobs'])
        self.assertEqual(checks, 2)
        result = json.loads(next(state.rglob('result.json')).read_text())
        self.assertTrue(result['automatic_restoration'])
        self.assertTrue(result['result_written'])

    def test_supervisor_stop_reuses_token_without_state_or_history_request(self):
        spec = importlib.util.spec_from_file_location('trial_token_fixture', '/tmp/gemma-component-trial-fixed.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        module.API_TOKEN = 'non-secret-fixture-token'
        with patch.object(module.urllib.request, 'urlopen', return_value=io.BytesIO(b'{"status":"stopping"}')) as opened:
            module.request('/api/jobs/' + 'a' * 32 + '/stop', {})
        opened.assert_called_once()
        self.assertTrue(opened.call_args.args[0].full_url.endswith('/stop'))
        self.assertEqual(opened.call_args.args[0].get_header('X-platform-token'), 'non-secret-fixture-token')


if __name__ == '__main__':
    unittest.main()
