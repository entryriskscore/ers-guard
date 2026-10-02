"""A local fake of the Entry Risk Score API (v1.2 response shapes) for tests and runnable examples."""
import email.utils
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FULL = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'BNBUSDT', 'DOGEUSDT', 'ADAUSDT', 'LINKUSDT', 'AVAXUSDT',
        'NEARUSDT', 'LTCUSDT', 'SUIUSDT', 'APTUSDT', 'ARBUSDT', 'TRXUSDT', 'HYPEUSDT', 'ENAUSDT', '1000PEPEUSDT',
        'WIFUSDT']
TRIAL = FULL[:10]
NOTICE = ('Entry Risk Score is a data service that measures entry-timing risk on Binance USDT-M futures. It is not '
          'a signal, not investment advice, and makes no promise of returns.')


def iso(ms):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(ms / 1000))


class FakeApi:
    """mode: normal | 401 | 403 | 404 | 429 | quota. as_of_age_s: age of every row. skew_s: server clock ahead.
    slow_s: delay before answering."""

    def __init__(self, plan='full', key='test-key'):
        self.plan, self.key, self.mode = plan, key, 'normal'
        self.as_of_age_s, self.skew_s, self.slow_s, self.retry_after = 30, 0, 0, 2
        self.status = {('ETHUSDT', 'LONG'): ('HIGH', 86.0)}
        self.calls = {'/api/v1/state': 0, '/api/v1/components': 0}
        self.lock = threading.Lock()
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), self._handler())
        self.httpd.handle_error = lambda request, client_address: None      # clients that time out on purpose
        self.url = f'http://127.0.0.1:{self.httpd.server_address[1]}'
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def now_ms(self):
        return int((time.time() + self.skew_s) * 1000)

    def rows(self):
        as_of = (self.now_ms() - self.as_of_age_s * 1000) // 300_000 * 300_000 if self.as_of_age_s < 300 \
            else self.now_ms() - self.as_of_age_s * 1000
        out = []
        for sym in (FULL if self.plan == 'full' else TRIAL):
            for prof in ('scalp', 'intraday', 'daily'):
                for side in ('LONG', 'SHORT'):
                    st, sc = self.status.get((sym, side), ('NORMAL', 31.0))
                    if side == 'SHORT' and prof != 'scalp':
                        st, sc = 'MEASURING', None
                    elif st in ('WARMING', 'STALE'):
                        sc = None
                    out.append({'symbol': sym, 'profile': prof, 'side': side, 'status': st, 'score': sc,
                                'base_rate': 0.2, 'base_n': 1400, 'history_n': 2000, 'as_of_ms': as_of,
                                'as_of': iso(as_of)})
        return out, as_of

    def _handler(self):
        api = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def send(self, code, obj, headers=None):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Date', email.utils.formatdate(time.time() + api.skew_s, usegmt=True))
                for k, v in (headers or {}).items():
                    self.send_header(k, str(v))
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                path = self.path.split('?')[0]
                with api.lock:
                    if path in api.calls:
                        api.calls[path] += 1
                if api.slow_s:
                    time.sleep(api.slow_s)
                key = self.headers.get('X-API-Key') or (self.headers.get('Authorization') or '').replace('Bearer ', '')
                if api.mode == '401' or key != api.key:
                    return self.send(401, {'error': {'code': 'invalid_key', 'message': 'Unknown API key.'}})
                if api.mode == '403':
                    return self.send(403, {'error': {'code': 'plan_ended', 'message': 'The plan has ended.'}})
                if api.mode == '404':
                    return self.send(404, {'error': {'code': 'not_found', 'message': 'Unknown endpoint.'}})
                if api.mode in ('429', 'quota'):
                    code = 'rate_limited' if api.mode == '429' else 'quota_exceeded'
                    return self.send(429, {'error': {'code': code, 'message': 'Slow down.',
                                                     'retry_after_s': api.retry_after}},
                                     {'Retry-After': api.retry_after})
                rows, as_of = api.rows()
                meta = {'api': 'ERS_API_V1.2', 'plan': api.plan, 'health': 'OK', 'next_update_ms': as_of + 300_000,
                        'next_update_at': iso(as_of + 300_000), 'notice': NOTICE,
                        'score_meaning': "Risk Score N/100 = riskier to enter than N% of that coin's own moments. "
                                         'Not a probability.'}
                hdr = {'X-RateLimit-Limit': 20000 if api.plan == 'full' else 500, 'X-RateLimit-Remaining': 19999}
                if path == '/api/v1/state':
                    return self.send(200, {'data': rows, 'meta': meta}, hdr)
                if path == '/api/v1/components':
                    comp = [{'symbol': r['symbol'], 'side': r['side'], 'status': r['status'], 'score': r['score'],
                             'components': {'volatility': {'input': 'atr1_pct', 'value': 0.42, 'percentile': 0.78},
                                            'crowding': {'input': 'funding_pctile', 'value': 0.95, 'percentile': 0.94},
                                            'extension_4h': {'input': 'ext4h_atr1h', 'value': 2.1, 'percentile': 0.81}},
                             'as_of_ms': r['as_of_ms'], 'as_of': r['as_of']} for r in rows if r['profile'] == 'scalp']
                    return self.send(200, {'data': comp, 'meta': meta}, hdr)
                return self.send(404, {'error': {'code': 'not_found', 'message': 'Unknown endpoint.'}})
        return H


if __name__ == '__main__':                       # python tests/fake_api.py  -> prints the URL, serves until Ctrl+C
    a = FakeApi()
    print(a.url, flush=True)
    while True:
        time.sleep(3600)
