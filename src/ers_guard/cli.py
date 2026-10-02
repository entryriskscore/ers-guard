"""ers-guard command line: check, status and a local sidecar for bots in any language."""
import argparse
import json
import logging
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import __version__
from .guard import HOLDS, NOTICE, Guard

EXIT_OK, EXIT_FAIL_ON, EXIT_UNKNOWN = 0, 2, 3


log = logging.getLogger('ers_guard')


def write_atomic(path, data, tries=10, first_wait=0.02, max_wait=0.2):
    """Write JSON to a temp file and move it over `path` in one step, so a reader never sees half a file.

    On Windows a reader that holds `path` open blocks the replace (PermissionError / WinError 5): retry with a short
    backoff (20 ms doubling up to 200 ms). If the target stays locked, the previous file is kept, the temp file is
    removed and False is returned; this function never raises because of the target being in use."""
    tmp = f'{path}.tmp{os.getpid()}.{threading.get_ident()}'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, separators=(',', ':'))
        f.flush()
        os.fsync(f.fileno())
    wait = first_wait
    for _ in range(tries):
        try:
            os.replace(tmp, path)
            return True
        except OSError:                               # PermissionError is a subclass
            time.sleep(wait)
            wait = min(max_wait, wait * 2)
    try:
        os.remove(tmp)
    except OSError:
        pass
    return False


def make_handler(guard, stats=None):
    stats = stats if stats is not None else {'file_write_failures': 0}
    class Handler(BaseHTTPRequestHandler):
        server_version = f'ers-guard/{__version__}'

        def log_message(self, fmt, *args):          # quiet; never logs headers or the key
            pass

        def send(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if u.path == '/health':
                return self.send(200, {'ok': True, 'version': __version__,
                                       'file_write_failures': stats['file_write_failures']})
            if u.path == '/state':
                return self.send(200, guard.state())
            if u.path == '/check':
                try:
                    r = guard.check(q.get('symbol', ''), q.get('side', ''), q.get('hold', '60m'),
                                    q.get('drivers') in ('1', 'true'))
                except ValueError as e:
                    return self.send(400, {'error': str(e)})
                return self.send(200, r.to_dict())
            return self.send(404, {'error': 'use /check, /state or /health'})
    return Handler


def write_cycle(guard, path, stats):
    """One writer cycle: never raises; at most ONE warning per failed cycle; failures counted for /health."""
    try:
        ok = write_atomic(path, guard.state())
        reason = 'the file stayed locked by a reader'
    except OSError as e:                                    # e.g. the folder is not writable
        ok, reason = False, str(e)
    if not ok:
        stats['file_write_failures'] += 1
        log.warning('ers-guard: could not update %s (%s); kept the previous file', path, reason)
    return ok


def serve(guard, port, path, stop=None, interval=30):
    stats = {'file_write_failures': 0}
    httpd = ThreadingHTTPServer(('127.0.0.1', port), make_handler(guard, stats))   # local only, by design
    stop = stop or threading.Event()

    def writer():
        while not stop.is_set():
            if path:
                write_cycle(guard, path, stats)
            stop.wait(interval)
    httpd.writer_thread = threading.Thread(target=writer, daemon=True)
    httpd.writer_thread.start()
    httpd.stats = stats
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, stop


def main(argv=None):
    p = argparse.ArgumentParser(prog='ers-guard',
                                description='Entry-risk check for trading bots (Entry Risk Score API). Risk Score '
                                            'N/100 = riskier to enter than N%% of that coin\'s own moments. '
                                            'Not a probability.',
                                epilog='Exit codes: 0 ok, 2 level matched --fail-on, 3 UNKNOWN or NOT_COVERED. '
                                       'Key: ERS_API_KEY. ' + NOTICE.replace('%', '%%'))
    p.add_argument('--version', action='version', version=f'ers-guard {__version__}')
    sub = p.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('check', help='check one symbol and side')
    c.add_argument('symbol')
    c.add_argument('side', choices=['LONG', 'SHORT', 'long', 'short'])
    c.add_argument('--hold', default='60m', choices=list(HOLDS))
    c.add_argument('--json', action='store_true')
    c.add_argument('--drivers', action='store_true', help='also fetch component percentiles (one extra request)')
    c.add_argument('--fail-on', default='', help='comma list of levels that exit with code 2, e.g. HIGH')
    sub.add_parser('status', help='plan, quota left, as_of, next update, covered symbols')
    s = sub.add_parser('serve', help='local sidecar on 127.0.0.1 for bots in any language')
    s.add_argument('--port', type=int, default=8787)
    s.add_argument('--file', default=None, help='also write the whole state to this JSON file every cycle')
    a = p.parse_args(argv)
    guard = Guard()
    if a.cmd == 'check':
        r = guard.check(a.symbol, a.side.upper(), a.hold, a.drivers)
        if a.json:
            print(json.dumps(r.to_dict()))
        else:
            sc = f' {int(r.score + 0.5)}/100' if r.score is not None else ''
            print(f'{r.symbol} {r.side} {r.hold}: {r.level}{sc} — {r.reason}')
        if r.level in ('UNKNOWN', 'NOT_COVERED'):
            return EXIT_UNKNOWN
        if r.level in {x.strip().upper() for x in a.fail_on.split(',') if x.strip()}:
            return EXIT_FAIL_ON
        return EXIT_OK
    if a.cmd == 'status':
        st = guard.state()
        st.pop('rows', None)
        print(json.dumps(st, indent=2))
        return EXIT_OK if st.get('ok') else EXIT_UNKNOWN
    if a.cmd == 'serve':
        httpd, stop = serve(guard, a.port, a.file)
        print(f'ers-guard sidecar on http://127.0.0.1:{a.port} (Ctrl+C to stop)')
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            stop.set()
            httpd.shutdown()
        return EXIT_OK
    return EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
