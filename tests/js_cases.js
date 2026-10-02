// JS client cases against the fake API (ERS_BASE / ERS_API_KEY from the test): caching, not covered, stale, symbols.
const assert = require('assert');
const { ErsGuard, normalizeSymbol } = require('../js/ers-guard.js');

(async () => {
  const g = new ErsGuard();
  const all = await Promise.all(Array.from({ length: 50 }, () => g.check('ETHUSDT', 'LONG')));
  assert.strictEqual(all.filter((r) => r.level === 'HIGH').length, 50);
  assert.strictEqual(g.requestsMade, 1);
  assert.strictEqual((await g.check('ETHUSDT', 'SHORT', '24h')).level, 'MEASURING');
  assert.strictEqual((await g.check('NOPEUSDT', 'LONG')).level, 'NOT_COVERED');
  assert.strictEqual(normalizeSymbol('ETH/USDT:USDT'), 'ETHUSDT');
  assert.strictEqual(normalizeSymbol('ETH-USDT-SWAP'), 'ETHUSDT');
  assert.strictEqual(normalizeSymbol('ETH/BTC'), null);
  const dead = new ErsGuard({ baseUrl: 'http://127.0.0.1:9' });
  const r = await dead.check('ETHUSDT', 'LONG');
  assert.strictEqual(r.level, 'UNKNOWN');
  assert.strictEqual(await dead.allowEntry('ETHUSDT', 'LONG', { onUnknown: 'block' }), false);
  console.log('JS_CASES_OK');
})().catch((e) => { console.error(e); process.exit(1); });
