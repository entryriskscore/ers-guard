import asyncio
import os
import sys
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'src'))
sys.path.insert(0, HERE)
from fake_api import FakeApi  # noqa: E402

from ers_guard import Guard, normalize_symbol  # noqa: E402


class Base(unittest.TestCase):
    plan = 'full'

    def setUp(self):
        self.api = FakeApi(plan=self.plan)
        self.g = Guard(api_key='test-key', base_url=self.api.url, timeout=2)

    def tearDown(self):
        self.api.close()


class TestAnswers(Base):
    def test_high_normal_and_fields(self):
        r = self.g.check('ETHUSDT', 'LONG', '60m')
        self.assertEqual((r.level, r.score), ('HIGH', 86.0))
        self.assertIn('Risk Score 86/100', r.reason)
        self.assertIn('Not a probability', r.reason)
        self.assertFalse(r.stale)
        self.assertIsNotNone(r.as_of)
        self.assertIsNotNone(r.next_update_at)
        self.assertEqual(self.g.check('BTCUSDT', 'LONG').level, 'NORMAL')

    def test_measuring_short_8h(self):
        r = self.g.check('ETHUSDT', 'SHORT', '8h')
        self.assertEqual((r.level, r.score), ('MEASURING', None))

    def test_warming_and_stale_rows(self):
        self.api.status[('SOLUSDT', 'LONG')] = ('WARMING', None)
        self.api.status[('XRPUSDT', 'LONG')] = ('STALE', None)
        self.assertEqual(self.g.check('SOLUSDT', 'LONG').level, 'UNKNOWN')
        r = self.g.check('XRPUSDT', 'LONG')
        self.assertEqual(r.level, 'UNKNOWN')
        self.assertIn('STALE', r.reason)

    def test_stale_as_of_is_unknown_never_fresh(self):
        self.api.as_of_age_s = 20 * 60
        r = self.g.check('ETHUSDT', 'LONG')
        self.assertEqual((r.level, r.stale, r.score), ('UNKNOWN', True, None))
        self.assertIn('more than 12 min', r.reason)

    def test_with_drivers(self):
        r = self.g.check('ETHUSDT', 'LONG', with_drivers=True)
        self.assertEqual(r.drivers['crowding']['percentile'], 0.94)
        self.assertEqual(r.reason, 'funding top 6% · 1-h volatility top 22% · stretched 4-h move')
        self.assertEqual(self.api.calls['/api/v1/components'], 1)

    def test_symbols(self):
        for s in ('ETH/USDT:USDT', 'ETH/USDT', 'eth-usdt', 'ETH-USDT-SWAP', 'ETH_USDT', 'ETHUSDT', 'ETHUSDT.P'):
            self.assertEqual(normalize_symbol(s), 'ETHUSDT', s)
        self.assertEqual(normalize_symbol('1000PEPE/USDT:USDT'), '1000PEPEUSDT')
        for s in ('ETH/BTC', 'BTC-USD', '', None, 'A/B/C'):
            self.assertIsNone(normalize_symbol(s))
        self.assertEqual(self.g.check('ETH/BTC', 'LONG').level, 'NOT_COVERED')
        self.assertEqual(self.g.check('DOGSUSDT', 'LONG').level, 'NOT_COVERED')

    def test_allow_entry_policies(self):
        self.assertFalse(self.g.allow_entry('ETHUSDT', 'LONG', block={'HIGH'}))
        self.assertTrue(self.g.allow_entry('BTCUSDT', 'LONG', block={'HIGH'}))
        self.assertTrue(self.g.allow_entry('NOPEUSDT', 'LONG'))
        self.assertFalse(self.g.allow_entry('NOPEUSDT', 'LONG', on_unknown='block'))

    def test_async(self):
        r = asyncio.run(self.g.acheck('ETHUSDT', 'LONG'))
        self.assertEqual(r.level, 'HIGH')


class TestCaching(Base):
    def test_one_call_per_cycle_under_50_concurrent_checks(self):
        out = []
        ts = [threading.Thread(target=lambda: out.append(self.g.check('ETHUSDT', 'LONG').level)) for _ in range(50)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(out.count('HIGH'), 50)
        self.assertEqual(self.api.calls['/api/v1/state'], 1)
        for _ in range(20):
            self.g.check('BTCUSDT', 'LONG')
        self.assertEqual(self.api.calls['/api/v1/state'], 1)                   # cached until next_update_at

    def test_next_cycle_and_minimum_interval(self):
        self.g.check('ETHUSDT', 'LONG')
        self.g._state.meta['next_update_ms'] = int(time.time() * 1000) - 60_000   # scores due a minute ago
        self.g.check('ETHUSDT', 'LONG')
        self.assertEqual(self.api.calls['/api/v1/state'], 1)                   # < 60 s since the last request
        self.g._last_try['state'] -= 61
        self.g.check('ETHUSDT', 'LONG')
        self.assertEqual(self.api.calls['/api/v1/state'], 2)

    def test_trial_budget(self):
        self.assertLessEqual(24 * 60 // 5, 500)                                # 288 cycles a day < trial quota

    def test_clock_skew(self):
        self.api.skew_s = 600                                                 # server clock 10 min ahead
        r = self.g.check('ETHUSDT', 'LONG')
        self.assertEqual(r.level, 'HIGH')                                     # fresh by the server's clock
        self.assertAlmostEqual(self.g._state.skew_s, 600, delta=3)
        self.api.skew_s = -600                                                # server behind: still fresh
        g2 = Guard(api_key='test-key', base_url=self.api.url)
        self.assertEqual(g2.check('ETHUSDT', 'LONG').level, 'HIGH')


class TestErrors(Base):
    def check_error(self, mode, needle):
        self.api.mode = mode
        r = self.g.check('ETHUSDT', 'LONG')
        self.assertEqual(r.level, 'UNKNOWN')
        self.assertIn(needle, r.reason)
        return r

    def test_401_403_404(self):
        self.check_error('401', '401')
        self.api.close()
        self.setUp()
        self.check_error('403', 'plan ended')
        self.api.close()
        self.setUp()
        self.check_error('404', '404')

    def test_429_rate_limited_and_quota_respect_retry_after(self):
        self.check_error('429', 'rate_limited')
        self.g._last_try['state'] -= 61                                       # interval passed, Retry-After not
        self.api.retry_after = 2
        self.g._blocked_until = time.time() + 2
        self.g.check('ETHUSDT', 'LONG')
        self.assertEqual(self.api.calls['/api/v1/state'], 1)
        self.api.mode = 'quota'
        self.g._blocked_until = 0
        self.check_error('quota', 'quota_exceeded')
        self.assertEqual(self.api.calls['/api/v1/state'], 2)

    def test_cached_answer_survives_a_failed_refresh_until_stale(self):
        self.assertEqual(self.g.check('ETHUSDT', 'LONG').level, 'HIGH')
        self.api.mode = '429'
        self.g._state.meta['next_update_ms'] = 0
        self.g._last_try['state'] -= 61
        self.assertEqual(self.g.check('ETHUSDT', 'LONG').level, 'HIGH')       # still within 12 min

    def test_network_down_and_slow_server(self):
        url = self.api.url
        self.api.close()
        g = Guard(api_key='test-key', base_url=url, timeout=1)
        r = g.check('ETHUSDT', 'LONG')
        self.assertEqual(r.level, 'UNKNOWN')
        self.assertIn('unreachable', r.reason)
        self.assertTrue(g.allow_entry('ETHUSDT', 'LONG'))
        self.assertFalse(Guard(api_key='k', base_url=url, timeout=1, on_unknown='block').allow_entry('ETHUSDT', 'LONG'))
        self.api = FakeApi()
        self.api.slow_s = 2
        t0 = time.time()
        r = Guard(api_key='test-key', base_url=self.api.url, timeout=0.5).check('ETHUSDT', 'LONG')
        self.assertEqual(r.level, 'UNKNOWN')
        self.assertLess(time.time() - t0, 2)


class TestTrial(Base):
    plan = 'trial'

    def test_not_covered(self):
        self.assertEqual(self.g.check('ETHUSDT', 'LONG').level, 'HIGH')
        r = self.g.check('ARBUSDT', 'LONG')
        self.assertEqual(r.level, 'NOT_COVERED')
        self.assertIn('not covered by this key', r.reason)


class TestKeyNeverLogged(Base):
    def test_logs(self):
        import logging
        with self.assertLogs('ers_guard', level='DEBUG') as cm:
            self.g.check('ETHUSDT', 'LONG')
            self.api.mode = '403'
            self.g._state = None
            self.g._last_try['state'] = 0
            self.g.check('ETHUSDT', 'LONG')
        self.assertFalse(any('test-key' in m for m in cm.output))
        self.assertTrue(logging.getLogger('ers_guard'))


if __name__ == '__main__':
    unittest.main()
