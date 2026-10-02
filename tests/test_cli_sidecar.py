import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '..', 'src')
sys.path.insert(0, SRC)
sys.path.insert(0, HERE)
from fake_api import FakeApi  # noqa: E402

from ers_guard import Guard, cli  # noqa: E402
from ers_guard.cli import serve, write_atomic  # noqa: E402


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


class TestCli(unittest.TestCase):
    def setUp(self):
        self.api = FakeApi()
        self.env = dict(os.environ, ERS_API_KEY='test-key', ERS_BASE=self.api.url, PYTHONPATH=SRC)

    def tearDown(self):
        self.api.close()

    def run_cli(self, *args):
        return subprocess.run([sys.executable, '-m', 'ers_guard', *args], capture_output=True, text=True, env=self.env,
                              timeout=30)

    def test_check_and_exit_codes(self):
        r = self.run_cli('check', 'ETHUSDT', 'LONG', '--json')
        self.assertEqual(r.returncode, 0)
        self.assertEqual(json.loads(r.stdout)['level'], 'HIGH')
        self.assertEqual(self.run_cli('check', 'ETHUSDT', 'LONG', '--fail-on', 'HIGH').returncode, 2)
        self.assertEqual(self.run_cli('check', 'ZZZUSDT', 'LONG').returncode, 3)
        out = self.run_cli('check', 'BTCUSDT', 'SHORT', '--hold', '8h').stdout
        self.assertIn('MEASURING', out)

    def test_status_and_help(self):
        st = json.loads(self.run_cli('status').stdout)
        self.assertEqual((st['plan'], len(st['covered'])), ('full', 19))
        self.assertEqual(st['quota_remaining'], '19999')
        h = self.run_cli('--help').stdout
        self.assertIn('not investment advice', h)
        self.assertIn('Not a probability', h)
        self.assertNotIn('test-key', h + json.dumps(st))


class TestSidecar(unittest.TestCase):
    def setUp(self):
        self.api = FakeApi()
        self.g = Guard(api_key='test-key', base_url=self.api.url)
        self.tmp = tempfile.TemporaryDirectory()
        self.file = os.path.join(self.tmp.name, 'ers_state.json')
        self.port = free_port()
        self.httpd, self.stop = serve(self.g, self.port, self.file)

    def tearDown(self):
        self.stop.set()
        self.httpd.writer_thread.join(timeout=10)          # nothing may hold the files during cleanup (Windows)
        self.httpd.shutdown()
        self.httpd.server_close()
        self.api.close()
        self.tmp.cleanup()

    def get(self, path):
        with urllib.request.urlopen(f'http://127.0.0.1:{self.port}{path}', timeout=5) as r:
            return json.loads(r.read())

    def test_endpoints_and_local_bind(self):
        self.assertEqual(self.get('/health')['ok'], True)
        c = self.get('/check?symbol=ETHUSDT&side=LONG&hold=60m')
        self.assertEqual((c['level'], c['score']), ('HIGH', 86.0))
        self.assertEqual(len(self.get('/state')['rows']), 19 * 6)
        self.assertEqual(self.httpd.server_address[0], '127.0.0.1')
        for _ in range(50):
            if os.path.exists(self.file):
                break
            time.sleep(0.1)
        self.assertEqual(len(json.load(open(self.file))['rows']), 114)
        self.assertEqual(self.api.calls['/api/v1/state'], 1)



class TestFileWrites(unittest.TestCase):
    """State-file writes, without a background sidecar writing into the same folder."""

    def setUp(self):
        self.api = FakeApi()
        self.g = Guard(api_key='test-key', base_url=self.api.url)
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.api.close()
        self.tmp.cleanup()

    def test_atomic_file_writes(self):
        """A concurrent reader never sees broken JSON and the writer never raises (on any OS)."""
        path = os.path.join(self.tmp.name, 'atomic.json')
        big = {'rows': [{'i': i, 'pad': 'x' * 200} for i in range(2000)]}
        bad, writer_errors, results = [], [], []
        stop = threading.Event()

        def reader():
            while not stop.is_set():
                try:
                    with open(path, encoding='utf-8') as f:
                        json.load(f)
                except (FileNotFoundError, PermissionError):  # Windows: the file is being swapped right now
                    pass
                except ValueError:
                    bad.append(1)
        t = threading.Thread(target=reader)
        t.start()
        try:
            for _ in range(40):
                try:
                    results.append(write_atomic(path, big))
                except Exception as e:                      # noqa: BLE001 - the assertion is "never raises"
                    writer_errors.append(e)
        finally:
            stop.set()
            t.join()
        self.assertEqual((bad, writer_errors), ([], []))
        self.assertTrue(any(results))
        with open(path, encoding='utf-8') as f:
            self.assertEqual(len(json.load(f)['rows']), 2000)
        self.assertEqual([n for n in os.listdir(self.tmp.name) if n.startswith(os.path.basename(path) + '.tmp')], [])

    def test_locked_target_retries_then_succeeds(self):
        path = os.path.join(self.tmp.name, 'locked.json')
        write_atomic(path, {'v': 1})
        real, calls = os.replace, []

        def flaky(src, dst):
            calls.append(1)
            if len(calls) <= 3:
                raise PermissionError(13, 'Access is denied (simulated WinError 5)')
            return real(src, dst)
        with mock.patch.object(cli.os, 'replace', flaky):
            self.assertTrue(write_atomic(path, {'v': 2}, first_wait=0.001))
        self.assertEqual(len(calls), 4)
        with open(path, encoding='utf-8') as f:
            self.assertEqual(json.load(f), {'v': 2})

    def test_always_locked_keeps_previous_file_and_warns_once(self):
        path = os.path.join(self.tmp.name, 'stuck.json')
        write_atomic(path, {'v': 1})

        def locked(src, dst):
            raise PermissionError(13, 'Access is denied (simulated WinError 5)')
        stats = {'file_write_failures': 0}
        with mock.patch.object(cli.os, 'replace', locked), mock.patch.object(cli.time, 'sleep', lambda s: None):
            self.assertFalse(write_atomic(path, {'v': 2}))
            with self.assertLogs('ers_guard', level='WARNING') as cm:
                self.assertFalse(cli.write_cycle(self.g, path, stats))
        self.assertEqual(len([m for m in cm.output if 'kept the previous file' in m and 'stuck.json' in m]), 1)
        self.assertEqual(stats['file_write_failures'], 1)
        self.assertEqual([n for n in os.listdir(self.tmp.name) if n.startswith('stuck.json.tmp')], [])   # temp removed
        with open(path, encoding='utf-8') as f:
            self.assertEqual(json.load(f), {'v': 1})
        self.assertEqual([n for n in os.listdir(self.tmp.name) if n.startswith(os.path.basename(path) + '.tmp')], [])

    def test_health_counts_failures_and_http_keeps_answering(self):
        def locked(src, dst):
            raise PermissionError(13, 'Access is denied (simulated)')
        port = free_port()
        path = os.path.join(self.tmp.name, 'health.json')
        with mock.patch.object(cli.os, 'replace', locked), mock.patch.object(cli.time, 'sleep', lambda s: None):
            httpd, stop = serve(self.g, port, path, interval=0.05)
            try:
                for _ in range(50):                         # time.sleep is patched here: wait on an Event instead
                    if httpd.stats['file_write_failures']:
                        break
                    threading.Event().wait(0.1)
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=5) as r:
                    h = json.loads(r.read())
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/check?symbol=ETHUSDT&side=LONG', timeout=5) as r:
                    c = json.loads(r.read())
            finally:
                stop.set()
                httpd.writer_thread.join(timeout=10)
                httpd.shutdown()
                httpd.server_close()
        self.assertGreaterEqual(h['file_write_failures'], 1)
        self.assertEqual(c['level'], 'HIGH')

if __name__ == '__main__':
    unittest.main()
