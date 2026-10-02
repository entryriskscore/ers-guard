// ers-guard.js — entry-risk check for Node 18+ bots (no dependencies). Same rules as the Python package:
// one GET /api/v1/state per 5-minute cycle (never more than once per 60 s), Retry-After respected, data older than
// 12 min is UNKNOWN, symbols outside the plan are NOT_COVERED. It reports a measurement; it decides nothing.
'use strict';

const HOLDS = { '60m': 'scalp', '8h': 'intraday', '24h': 'daily' };
const STALE_AFTER_MS = 12 * 60 * 1000;
const MIN_INTERVAL_MS = 60 * 1000;

function normalizeSymbol(s) {
  if (typeof s !== 'string') return null;
  let t = s.trim().toUpperCase().replace(/\.P$/, '');
  for (const suf of ['-SWAP', '_PERP', '-PERP', 'PERP', ':USDT']) {
    if (t.endsWith(suf) && t.length > suf.length) t = t.slice(0, -suf.length);
  }
  const parts = t.split(/[/\-_: ]+/).filter(Boolean);
  if (parts.length === 2 && parts[1] === 'USDT') t = parts[0] + 'USDT';
  else if (parts.length === 1) t = parts[0];
  else return null;
  return /^[A-Z0-9]{2,16}USDT$/.test(t) ? t : null;
}

class ErsGuard {
  constructor({ apiKey = process.env.ERS_API_KEY, baseUrl = process.env.ERS_BASE || 'https://entryriskscore.com',
                onUnknown = 'allow' } = {}) {
    this.apiKey = apiKey; this.baseUrl = baseUrl.replace(/\/$/, ''); this.onUnknown = onUnknown;
    this.snap = null; this.lastTry = 0; this.blockedUntil = 0; this.inflight = null; this.lastError = null;
    this.requestsMade = 0;
  }

  due(now) {
    if (now < this.blockedUntil || now - this.lastTry < MIN_INTERVAL_MS) return false;
    if (!this.snap) return true;
    const nxt = this.snap.meta.next_update_ms;
    return nxt ? now + this.snap.skewMs >= nxt + 10000 : now - this.snap.fetchedAt >= 300000;
  }

  async refresh() {
    if (this.inflight) return this.inflight;                       // single flight
    const now = Date.now();
    if (!this.due(now)) return this.snap;
    this.lastTry = now;
    this.inflight = (async () => {
      try {
        this.requestsMade += 1;
        const r = await fetch(`${this.baseUrl}/api/v1/state`, { headers: { 'X-API-Key': this.apiKey || '' } });
        if (!r.ok) {
          let code = 'http_error';
          try { code = (await r.json()).error.code; } catch (e) { /* not JSON */ }
          const ra = Number(r.headers.get('retry-after'));
          if (ra) this.blockedUntil = Date.now() + ra * 1000;
          this.lastError = `${r.status} ${code}`;
          return this.snap;
        }
        const body = await r.json();
        const date = Date.parse(r.headers.get('date') || '');
        const index = new Map(body.data.map((x) => [`${x.symbol}|${x.profile}|${x.side}`, x]));
        this.snap = { rows: body.data, meta: body.meta, index, fetchedAt: Date.now(),
                      skewMs: Number.isFinite(date) ? date - Date.now() : 0 };
        this.lastError = null;
        return this.snap;
      } catch (e) {
        this.lastError = `unreachable (${e.message})`;
        return this.snap;
      } finally {
        this.inflight = null;
      }
    })();
    return this.inflight;
  }

  async check(symbol, side, hold = '60m') {
    side = String(side).toUpperCase();
    if (!HOLDS[hold]) throw new Error('hold must be 60m, 8h or 24h');
    const sym = normalizeSymbol(symbol);
    const snap = await this.refresh();
    if (!sym) return { symbol, side, hold, level: 'NOT_COVERED', reason: 'not a Binance USDT-M perpetual symbol' };
    if (!snap) return { symbol: sym, side, hold, level: 'UNKNOWN', stale: true, reason: this.lastError || 'no data yet' };
    const row = snap.index.get(`${sym}|${HOLDS[hold]}|${side}`);
    if (!row) return { symbol: sym, side, hold, level: 'NOT_COVERED', reason: `${sym} is not covered by this key's plan` };
    const age = Date.now() + snap.skewMs - row.as_of_ms;
    const out = { symbol: sym, side, hold, level: 'UNKNOWN', score: row.score, asOf: row.as_of,
                  nextUpdateAt: snap.meta.next_update_at, stale: false, reason: '', raw: row };
    if (age > STALE_AFTER_MS) {
      return { ...out, score: null, stale: true, reason: `last measurement ${Math.floor(age / 60000)} min old: not current` };
    }
    if (['HIGH', 'ELEVATED', 'NORMAL'].includes(row.status)) {
      out.level = row.status;
      out.reason = `Risk Score ${Math.round(row.score)}/100: riskier to enter than ${Math.round(row.score)}% of ${sym}'s own moments. Not a probability.`;
    } else if (row.status === 'MEASURING') {
      Object.assign(out, { level: 'MEASURING', score: null, reason: 'not scored yet for this holding period' });
    } else {
      Object.assign(out, { score: null, reason: `${row.status}: no current score` });
    }
    return out;
  }

  async allowEntry(symbol, side, { hold = '60m', block = ['HIGH'], onUnknown } = {}) {
    const r = await this.check(symbol, side, hold);
    if (block.includes(r.level)) return false;
    if (r.level === 'UNKNOWN' || r.level === 'NOT_COVERED') return (onUnknown || this.onUnknown) === 'allow';
    return true;
  }
}

module.exports = { ErsGuard, normalizeSymbol };
