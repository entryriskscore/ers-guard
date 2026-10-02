import os
import shutil
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')
sys.path.insert(0, os.path.join(ROOT, 'src'))
sys.path.insert(0, HERE)
for sub in ('freqtrade', 'hummingbot', 'ccxt'):
    sys.path.insert(0, os.path.join(ROOT, 'integrations', sub))
from fake_api import FakeApi  # noqa: E402

from ers_guard import Guard  # noqa: E402


class Fixture(unittest.TestCase):
    def setUp(self):
        self.api = FakeApi()
        os.environ['ERS_API_KEY'], os.environ['ERS_BASE'] = 'test-key', self.api.url

    def tearDown(self):
        self.api.close()
        os.environ.pop('ERS_BASE', None)


class TestFreqtrade(Fixture):
    def test_mixin_blocks_high_entries_only(self):
        from ers_guard_mixin import ErsGuardMixin

        class FakeIStrategy:
            def confirm_trade_entry(self, *a, **k):
                return True

        class Strat(ErsGuardMixin, FakeIStrategy):
            _ers_guard = None
        s = Strat()
        args = ('limit', 1.0, 100.0, 'GTC', None)
        self.assertFalse(s.confirm_trade_entry('ETH/USDT:USDT', *args, side='long'))
        self.assertTrue(s.confirm_trade_entry('BTC/USDT:USDT', *args, side='long'))
        self.assertTrue(s.confirm_trade_entry('ETH/USDT:USDT', *args, side='short'))


class TestHummingbot(Fixture):
    def test_helper(self):
        import guarded_order_script as h
        g = Guard()
        self.assertFalse(h.entry_allowed(g, 'ETH-USDT', is_buy=True))
        self.assertTrue(h.entry_allowed(g, 'BTC-USDT', is_buy=True))


class TestCcxt(Fixture):
    def test_guarded_create_order(self):
        from guarded import EntryBlocked, guarded_create_order

        class Ex:
            def __init__(self):
                self.orders = []

            def create_order(self, *a):
                self.orders.append(a)
                return {'id': len(self.orders)}
        ex, g = Ex(), Guard()
        with self.assertRaises(EntryBlocked):
            guarded_create_order(ex, 'ETH/USDT:USDT', 'limit', 'buy', 1, 100, guard=g)
        self.assertEqual(guarded_create_order(ex, 'ETH/USDT:USDT', 'limit', 'sell', 1, 100, {'reduceOnly': True},
                                              guard=g)['id'], 1)             # exits are never blocked
        self.assertEqual(guarded_create_order(ex, 'BTC/USDT:USDT', 'market', 'buy', 1, guard=g)['id'], 2)


class TestExamples(Fixture):
    def test_quickstart_runs(self):
        r = subprocess.run([sys.executable, os.path.join(ROOT, 'examples', 'quickstart.py')], capture_output=True,
                           text=True, timeout=30, env=dict(os.environ, PYTHONPATH=os.path.join(ROOT, 'src')))
        self.assertIn("level='HIGH'", r.stdout)

    @unittest.skipUnless(shutil.which('node'), 'Node.js not installed')
    def test_js_client_against_the_same_fake(self):
        r = subprocess.run(['node', os.path.join(ROOT, 'examples', 'node_example.js')], capture_output=True, text=True,
                           timeout=30, env=dict(os.environ))
        self.assertIn("level: 'HIGH'", r.stdout)
        self.assertIn('allow LONG ETH: false', r.stdout)
        r = subprocess.run(['node', os.path.join(HERE, 'js_cases.js')], capture_output=True, text=True, timeout=60,
                           env=dict(os.environ))
        self.assertIn('JS_CASES_OK', r.stdout, r.stdout + r.stderr)


if __name__ == '__main__':
    unittest.main()
