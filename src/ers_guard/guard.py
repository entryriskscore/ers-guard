"""Guard: a quota-friendly, read-only client for the Entry Risk Score API (v1.2).

It answers one question for your bot: how risky is it to enter this symbol and side now? It never computes a score
itself and never decides for you. One GET /api/v1/state per 5-minute update cycle, shared by every caller.
"""
from __future__ import annotations

import asyncio
import email.utils
import json
import logging
import os
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

from .symbols import normalize_symbol

log = logging.getLogger('ers_guard')

DEFAULT_BASE = 'https://entryriskscore.com'
HOLDS = {'60m': 'scalp', '8h': 'intraday', '24h': 'daily'}
HOLD_TEXT = {'60m': '60 min', '8h': '8 h', '24h': '24 h'}
STALE_AFTER_S = 12 * 60          # same rule as the service: older than 12 minutes is not current
MIN_INTERVAL_S = 60              # never more than one request per 60 s, whatever the caller does
CYCLE_S = 300
NOTICE = ('Entry Risk Score is a data service that measures entry-timing risk on Binance USDT-M futures. It is not '
          'a signal, not investment advice, and makes no promise of returns. Published rates describe the past and do '
          'not guarantee future results. You are solely responsible for your trading decisions.')
LEVELS = ('HIGH', 'ELEVATED', 'NORMAL', 'MEASURING', 'UNKNOWN', 'NOT_COVERED')


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # optional; the system store is used otherwise
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


@dataclass
class Result:
    """The answer for one symbol, side and holding period. `level` is one of HIGH, ELEVATED, NORMAL, MEASURING,
    UNKNOWN or NOT_COVERED. `score` is the Risk Score 0-100 (riskier to enter than score% of that coin's own
    moments; not a probability) or None."""
    symbol: str
    side: str
    hold: str
    level: str
    score: Optional[float] = None
    base_rate: Optional[float] = None
    as_of: Optional[datetime] = None
    next_update_at: Optional[datetime] = None
    stale: bool = False
    reason: str = ''
    drivers: Optional[Dict[str, Any]] = None
    raw: Optional[Dict[str, Any]] = field(default=None, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {'symbol': self.symbol, 'side': self.side, 'hold': self.hold, 'level': self.level, 'score': self.score,
                'base_rate': self.base_rate, 'as_of': self.as_of.strftime('%Y-%m-%dT%H:%M:%SZ') if self.as_of else None,
                'next_update_at': self.next_update_at.strftime('%Y-%m-%dT%H:%M:%SZ') if self.next_update_at else None,
                'stale': self.stale, 'reason': self.reason, 'drivers': self.drivers}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, retry_after: Optional[float] = None):
        super().__init__(f'{status} {code}: {message}')
        self.status, self.code, self.message, self.retry_after = status, code, message, retry_after


class _Snapshot:
    def __init__(self, rows, meta, fetched_at, skew_s, headers):
        self.rows, self.meta, self.fetched_at, self.skew_s, self.headers = rows, meta, fetched_at, skew_s, headers
        self.index = {}
        for r in rows:
            self.index[(r.get('symbol'), r.get('profile'), r.get('side'))] = r
        self.newest = max((r.get('as_of_ms') or 0 for r in rows), default=0) or None


class Guard:
    """Thread-safe client. Reads ERS_API_KEY from the environment unless `api_key` is given.

    on_unknown: what allow_entry() returns when the answer is UNKNOWN or NOT_COVERED: "allow" (default) or "block".
    """

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, on_unknown: str = 'allow',
                 timeout: float = 10.0, user_agent: Optional[str] = None):
        from . import __version__
        self.api_key = api_key or os.environ.get('ERS_API_KEY', '')
        self.base_url = (base_url or os.environ.get('ERS_BASE') or DEFAULT_BASE).rstrip('/')
        if on_unknown not in ('allow', 'block'):
            raise ValueError('on_unknown must be "allow" or "block"')
        self.on_unknown = on_unknown
        self.timeout = timeout
        self.user_agent = user_agent or f'ers-guard/{__version__}'
        self._lock = threading.Lock()
        self._state: Optional[_Snapshot] = None
        self._components: Optional[_Snapshot] = None
        self._last_try = {'state': 0.0, 'components': 0.0}
        self._blocked_until = 0.0                    # Retry-After from the API
        self._last_error: Optional[ApiError] = None
        self._ctx = _ssl_context()
        self.requests_made = 0

    # ------------------------------------------------------------------ HTTP
    def _get(self, path: str):
        req = urllib.request.Request(self.base_url + path, headers={
            'X-API-Key': self.api_key, 'Accept': 'application/json', 'User-Agent': self.user_agent})
        self.requests_made += 1
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout,
                                        context=self._ctx if self.base_url.startswith('https') else None) as r:
                body = json.loads(r.read().decode('utf-8'))
                headers = dict(r.headers.items())
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read().decode('utf-8')).get('error', {})
            except (ValueError, AttributeError):
                err = {}
            ra = e.headers.get('Retry-After') if e.headers else None
            raise ApiError(e.code, err.get('code', 'http_error'), err.get('message', str(e)),
                           float(ra) if ra and str(ra).replace('.', '', 1).isdigit() else None) from None
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise ApiError(0, 'unreachable', f'{type(e).__name__}: {e}') from None
        skew = 0.0
        date = headers.get('Date') or headers.get('date')
        if date:
            try:
                skew = email.utils.parsedate_to_datetime(date).timestamp() - (t0 + time.time()) / 2
            except (TypeError, ValueError):
                skew = 0.0
        return body, headers, skew

    # ------------------------------------------------------------------ cache
    def _due(self, snap: Optional[_Snapshot], now: float, kind: str) -> bool:
        if now < self._blocked_until or now - self._last_try[kind] < MIN_INTERVAL_S:
            return False
        if snap is None:
            return True
        nxt = (snap.meta or {}).get('next_update_ms')
        if not nxt:
            return now - snap.fetched_at >= CYCLE_S
        jitter = (hash(self.api_key) % 15) + 5        # 5-19 s after the scores are due, stable per key
        return now + snap.skew_s >= nxt / 1000 + jitter

    def _refresh(self, kind: str = 'state') -> Optional[_Snapshot]:
        """Single flight: callers hold self._lock, so 50 concurrent check() calls cause one request."""
        now = time.time()
        snap = self._state if kind == 'state' else self._components
        if not self._due(snap, now, kind):
            return snap
        self._last_try[kind] = now
        try:
            body, headers, skew = self._get('/api/v1/state' if kind == 'state' else '/api/v1/components')
            snap = _Snapshot(body.get('data') or [], body.get('meta') or {}, time.time(), skew, headers)
            self._last_error = None
            if kind == 'state':
                self._state = snap
            else:
                self._components = snap
            log.debug('ers_guard: refreshed %s (%d rows, next update %s)', kind, len(snap.rows),
                      snap.meta.get('next_update_at'))
        except ApiError as e:
            self._last_error = e
            if e.retry_after:
                self._blocked_until = time.time() + e.retry_after
            log.warning('ers_guard: %s request failed: %s %s', kind, e.status, e.code)
        return snap

    # ------------------------------------------------------------------ answers
    def check(self, symbol: str, side: str, hold: str = '60m', with_drivers: bool = False) -> Result:
        side = (side or '').upper()
        if side in ('BUY',):
            side = 'LONG'
        if side in ('SELL',):
            side = 'SHORT'
        if hold not in HOLDS:
            raise ValueError('hold must be one of 60m, 8h, 24h')
        if side not in ('LONG', 'SHORT'):
            raise ValueError('side must be LONG or SHORT')
        sym = normalize_symbol(symbol)
        with self._lock:
            snap = self._refresh('state')
            comps = self._refresh('components') if with_drivers else None
        if sym is None:
            return Result(str(symbol), side, hold, 'NOT_COVERED', reason='not a Binance USDT-M perpetual symbol')
        if snap is None:
            return Result(sym, side, hold, 'UNKNOWN', stale=True, reason=self._why_unavailable())
        server_now = time.time() + snap.skew_s
        nxt = _parse_iso(snap.meta.get('next_update_at'))
        row = snap.index.get((sym, HOLDS[hold], side))
        if row is None:
            covered = {r.get('symbol') for r in snap.rows}
            reason = (f'{sym} is not covered by this key\'s plan' if sym not in covered
                      else f'no row for {sym} {side} {HOLD_TEXT[hold]}')
            return Result(sym, side, hold, 'NOT_COVERED', next_update_at=nxt, reason=reason)
        as_of = _parse_iso(row.get('as_of'))
        age = server_now - (row.get('as_of_ms') or 0) / 1000
        status = row.get('status')
        res = Result(sym, side, hold, 'UNKNOWN', score=row.get('score'), base_rate=row.get('base_rate'), as_of=as_of,
                     next_update_at=nxt, raw=row)
        if age > STALE_AFTER_S:
            res.stale, res.score = True, None
            res.reason = (f'last measurement {int(age // 60)} min old (more than 12 min): not current'
                          + (f'; {self._why_unavailable()}' if self._last_error else ''))
            return res
        if status in ('HIGH', 'ELEVATED', 'NORMAL'):
            res.level = status
            res.reason = (f'Risk Score {int(res.score + 0.5)}/100 for entries held {HOLD_TEXT[hold]}: riskier to enter '
                          f'than {int(res.score + 0.5)}% of {sym}\'s own moments. Not a probability.')
        elif status == 'MEASURING':
            res.level, res.score = 'MEASURING', None
            res.reason = f'{side} for {HOLD_TEXT[hold]} is not scored yet (being measured)'
        else:
            res.score = None
            res.reason = f'{status or "no status"}: ' + ('not enough history yet' if status == 'WARMING'
                                                          else 'no fresh data for this coin')
        if with_drivers and comps is not None:
            c = comps.index.get((sym, 'scalp', side)) or next(
                (r for r in comps.rows if r.get('symbol') == sym and r.get('side') == side), None)
            if c:
                res.drivers = c.get('components')
                txt = _driver_text(side, c.get('components') or {})
                if txt and res.level in ('HIGH', 'ELEVATED', 'NORMAL'):
                    res.reason = txt
        return res

    def allow_entry(self, symbol: str, side: str, hold: str = '60m', block: Iterable[str] = ('HIGH',),
                    on_unknown: Optional[str] = None) -> bool:
        """Convenience: False when the level is in `block`; UNKNOWN / NOT_COVERED follow `on_unknown`
        (or the Guard default). The policy is yours: Guard only reports the measured level."""
        r = self.check(symbol, side, hold)
        if r.level in set(block):
            return False
        if r.level in ('UNKNOWN', 'NOT_COVERED'):
            return (on_unknown or self.on_unknown) == 'allow'
        return True

    async def acheck(self, symbol: str, side: str, hold: str = '60m', with_drivers: bool = False) -> Result:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self.check(symbol, side, hold, with_drivers))

    def state(self) -> Dict[str, Any]:
        """The cached /state document plus client-side status (for the CLI and the sidecar)."""
        with self._lock:
            snap = self._refresh('state')
        if snap is None:
            return {'ok': False, 'reason': self._why_unavailable(), 'rows': []}
        h = {k.lower(): v for k, v in (snap.headers or {}).items()}
        return {'ok': True, 'plan': snap.meta.get('plan'), 'next_update_at': snap.meta.get('next_update_at'),
                'as_of_ms': snap.newest, 'quota_remaining': h.get('x-ratelimit-remaining'),
                'quota_limit': h.get('x-ratelimit-limit'), 'covered': sorted({r.get('symbol') for r in snap.rows}),
                'score_meaning': snap.meta.get('score_meaning'), 'rows': snap.rows,
                'last_error': f'{self._last_error.status} {self._last_error.code}' if self._last_error else None}

    def _why_unavailable(self) -> str:
        e = self._last_error
        if e is None:
            return 'no data yet'
        if e.status == 0:
            return f'API unreachable ({e.message})'
        if e.status == 401:
            return 'API key missing or unknown (401): set ERS_API_KEY'
        if e.status == 403:
            return f'key revoked or plan ended (403 {e.code})'
        if e.status == 429:
            return f'{e.code} (429); retrying after {int(e.retry_after or 60)} s'
        return f'API error {e.status} {e.code}'


def _driver_text(side: str, comps: Dict[str, Any]) -> str:
    out = []
    crowd = (comps.get('crowding') or {}).get('percentile')
    vol = (comps.get('volatility') or {}).get('percentile')
    ext = comps.get('extension_4h') or {}
    if crowd is not None and crowd >= 0.7:
        out.append(f'funding {"top" if side == "LONG" else "bottom"} {max(1, int(100 - crowd * 100 + 0.5))}%')
    if vol is not None and vol >= 0.7:
        out.append(f'1-h volatility top {max(1, int(100 - vol * 100 + 0.5))}%')
    if ext.get('percentile') is not None and ext['percentile'] >= 0.7:
        out.append('stretched 4-h move')
    return ' · '.join(out)
