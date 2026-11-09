import errno
import os
from pathlib import Path
import select
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import Platform, now


class LifecyclePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app = Platform(self.root, self.root / 'state', 0)
        self.children, self.threads = [], []

    def tearDown(self):
        for child in self.children:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=3)
            if child.stdout: child.stdout.close()
        for thread in self.threads: thread.join(timeout=3)
        self.app.history.db.close()
        self.temp.cleanup()

    def child(self, ignore_term=False):
        script = 'import signal,time\n' + ('signal.signal(signal.SIGTERM,signal.SIG_IGN)\n' if ignore_term else '')
        child = subprocess.Popen([sys.executable, '-c', script + 'print("ready",flush=True)\ntime.sleep(20)'],
                                 stdout=subprocess.PIPE, text=True, start_new_session=True)
        self.children.append(child)
        self.assertTrue(select.select([child.stdout], [], [], 3)[0], 'child did not become ready')
        self.assertEqual(child.stdout.readline().strip(), 'ready')
        return child

    def owned(self, child, status='running', reaper=True):
        key = 'a' * 32
        self.app.jobs[key] = {'id': key, 'status': status, 'pid': child.pid, 'started_at': now()}
        self.app.processes[key] = child
        if reaper:
            thread = threading.Thread(target=self.app.reap, args=(key,), daemon=True)
            self.threads.append(thread)
            thread.start()
        return key

    def await_reaped(self, key):
        deadline = time.monotonic() + 3
        while key in self.app.processes and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertNotIn(key, self.app.processes)
        self.assertIn(self.app.jobs[key]['status'], ('succeeded', 'failed', 'stopped'))
        self.assertIsInstance(self.app.jobs[key]['exit_code'], int)
        self.assertTrue(self.app.jobs[key]['finished_at'])

    def full(self):
        return OSError(errno.ENOSPC, 'No space left on device')

    def test_required_job_persistence_failure_never_spawns(self):
        with patch.object(self.app, 'external', return_value=[]), patch.object(self.app, 'save', side_effect=self.full()), \
                patch('server.subprocess.Popen') as spawn:
            with self.assertRaises(OSError):
                self.app.start({'kind': 'checks', 'checks': ['frontend']})
        spawn.assert_not_called()
        self.assertFalse(self.app.processes)

    def test_prelaunch_history_failure_never_spawns(self):
        with patch.object(self.app, 'external', return_value=[]), \
                patch.object(self.app.history, 'sync', side_effect=sqlite3.OperationalError('database or disk is full')), \
                patch('server.subprocess.Popen') as spawn:
            with self.assertRaises(sqlite3.OperationalError):
                self.app.start({'kind': 'checks', 'checks': ['frontend']})
        spawn.assert_not_called()

    def test_postspawn_disk_failures_return_known_job_and_reap_owned_process(self):
        child = self.child()
        original_save, original_sync = self.app.save, self.app.history.sync
        calls = {'save': 0, 'sync': 0}
        def save(job):
            calls['save'] += 1
            if calls['save'] > 1: raise self.full()
            return original_save(job)
        def sync(job):
            calls['sync'] += 1
            if calls['sync'] > 1: raise sqlite3.OperationalError('database or disk is full')
            return original_sync(job)
        with patch.object(self.app, 'external', return_value=[]), patch('server.subprocess.Popen', return_value=child), \
                patch.object(self.app, 'save', side_effect=save), patch.object(self.app.history, 'sync', side_effect=sync):
            job = self.app.start({'kind': 'checks', 'checks': ['frontend']})
            self.assertEqual(job['pid'], child.pid)
            self.assertIs(self.app.processes[job['id']], child)
            self.assertTrue(job['persistence_errors'])
            os.killpg(child.pid, signal.SIGTERM)
            child.wait(timeout=3)
            self.await_reaped(job['id'])
        self.assertTrue(any(e['phase'] == 'reaped' for e in job['persistence_errors']))

    def test_stop_sends_signal_and_reaps_even_when_both_stores_are_full(self):
        child = self.child()
        key = self.owned(child)
        with patch.object(self.app, 'save', side_effect=self.full()), \
                patch.object(self.app.history, 'sync', side_effect=sqlite3.OperationalError('database or disk is full')):
            job = self.app.stop(key)
            child.wait(timeout=3)
            self.await_reaped(key)
        self.assertTrue(job['stop_signal_sent'])
        self.assertTrue(job['stop_watch_started'])
        self.assertEqual(job['status'], 'stopped')
        self.assertLessEqual(len(job['persistence_errors']), 8)

    def test_old_stopping_state_without_signal_can_be_retried(self):
        child = self.child()
        key = self.owned(child, status='stopping')
        self.app.stop(key)
        child.wait(timeout=3)
        self.await_reaped(key)
        self.assertTrue(self.app.jobs[key]['stop_signal_sent'])

    def test_grace_kill_precedes_persistence_failure(self):
        child = self.child(ignore_term=True)
        key = self.owned(child)
        with patch.object(self.app, 'save', side_effect=self.full()), \
                patch.object(self.app.history, 'sync', side_effect=sqlite3.OperationalError('database or disk is full')):
            self.app.stop(key)
            self.app.finish_stop(key, child, grace=.02)
            self.assertEqual(child.wait(timeout=3), -signal.SIGKILL)
            self.await_reaped(key)
        self.assertTrue(self.app.jobs[key]['force_killed'])
        self.assertFalse(self.app.jobs[key]['clean_stop'])

    def test_unknown_programming_error_is_not_swallowed_but_dead_process_is_removed(self):
        child = self.child()
        key = self.owned(child, reaper=False)
        os.killpg(child.pid, signal.SIGTERM)
        child.wait(timeout=3)
        with patch.object(self.app.history, 'sync', side_effect=sqlite3.OperationalError('no such table: bad_schema')):
            with self.assertRaises(sqlite3.OperationalError):
                self.app.reap(key)
        self.assertNotIn(key, self.app.processes)
        self.assertEqual(self.app.jobs[key]['status'], 'failed')
        self.assertTrue(self.app.jobs[key]['finished_at'])


if __name__ == '__main__':
    unittest.main()
