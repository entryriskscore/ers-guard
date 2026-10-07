<p align="center">
  <img src="https://raw.githubusercontent.com/entryriskscore/ers-guard/main/ers-guard-readme-banner-1280x320.png" alt="ERS Guard — an entry-risk check for any trading bot" width="100%">
</p>

<p align="center">
  <a href="https://github.com/entryriskscore/ers-guard/actions/workflows/tests.yml"><img src="https://github.com/entryriskscore/ers-guard/actions/workflows/tests.yml/badge.svg" alt="tests"></a>
  <a href="https://pypi.org/project/ers-guard/"><img src="https://img.shields.io/pypi/v/ers-guard" alt="PyPI"></a>
  <a href="https://github.com/entryriskscore/ers-guard/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/python-3.9%E2%80%933.13-informational" alt="Python 3.9–3.13">
  <img src="https://img.shields.io/badge/os-Linux%20%7C%20Windows%20%7C%20macOS-informational" alt="Linux | Windows | macOS">
</p>

<p align="center">
  <a href="https://entryriskscore.com">Website</a> ·
  <a href="https://entryriskscore.com/docs">Docs</a> ·
  <a href="https://entryriskscore.com/docs/mcp">MCP</a> ·
  <a href="https://entryriskscore.com/api/v1/openapi.json">OpenAPI</a> ·
  <a href="https://entryriskscore.com/try">Free 7-day trial</a>
</p>

# ERS Guard

**Add an entry-risk check to your bot in 3 lines.** ERS Guard asks the
[Entry Risk Score](https://entryriskscore.com) API one question before your bot opens a position:
*how risky is it to enter this symbol and side now, compared with that coin's own history?*

It works with a free 7-day trial key (10 coins) and with Full (19 Binance USDT-M perpetuals).

**What it is:** a small, dependency-free client (Python 3.9+, plus a single-file JavaScript client and a local
sidecar for any language) that reads the published Risk Score and gives your code a level to act on with your own rules.

**What it is not:** a signal, a strategy or advice. Guard never computes a score, never tells you to buy or sell and
never changes your bot's logic. You decide what a HIGH level means for your entries.

## Quickstart

```bash
pip install ers-guard                    # Python 3.9+, no dependencies (or copy src/ers_guard into your project)
export ERS_API_KEY=ers_...               # dashboard → API & MCP (trial keys work)
```

```python
from ers_guard import Guard
guard = Guard()
print(guard.check("ETHUSDT", "LONG", hold="60m"))
```

```python
r = guard.check("ETHUSDT", "LONG", hold="60m")   # hold: 60m | 8h | 24h
r.level, r.score, r.as_of, r.reason              # 'HIGH', 86.0, datetime(...), 'Risk Score 86/100 for entries held 60 min: ...'

if guard.allow_entry("ETHUSDT", "LONG", block={"HIGH"}):   # your policy, not ours
    place_order(...)
```

## The answer

| `level` | Meaning |
|---|---|
| `HIGH` | Risk Score 80/100 or above: the coin's own riskiest 20% of moments |
| `ELEVATED` | Risk Score 60–79 |
| `NORMAL` | Risk Score below 60 (not HIGH does not mean low risk) |
| `MEASURING` | this side × holding period is not scored yet (reserved; since score v1.1 every side and holding period is scored) |
| `UNKNOWN` | no current answer: data older than 12 minutes, the API unreachable, a key problem, WARMING or STALE coin |
| `NOT_COVERED` | the symbol is not in your key's plan (trial: BTC, ETH, SOL, XRP, BNB, DOGE, ADA, LINK, AVAX, NEAR) or not a USDT-M perpetual |

**Risk Score N/100** = riskier to enter than N% of that coin's own moments over the last 90 days (score v1.1). **Not a probability.** Tested on Jan–Sep 2026 history: see [entryriskscore.com/evidence](https://entryriskscore.com/evidence).
Holding periods: `60m` (adverse move 1%), `8h` (2%), `24h` (3%).

`Result` fields: `symbol, side, hold, level, score, base_rate, as_of, next_update_at, stale, reason, drivers, raw`.
`drivers` (component percentiles) are fetched only with `check(..., with_drivers=True)` — one extra request per cycle.

## Policies

- `Guard(on_unknown="allow")` (default) or `"block"`: what `allow_entry()` returns for `UNKNOWN` / `NOT_COVERED`.
- `allow_entry(symbol, side, hold="60m", block={"HIGH"})`: block any set of levels, e.g. `{"HIGH", "ELEVATED"}`.
- Guard **never presents stale data as current**: if the newest measurement is older than 12 minutes, the answer is
  `UNKNOWN` with the reason.

## Quota-friendly by design

- One `GET /api/v1/state` (all your coins) per 5-minute update cycle, cached until `meta.next_update_at` plus a few
  seconds; **never more than one request per 60 seconds**, whatever your code does. 50 threads calling `check()` at
  once cause one request.
- `Retry-After` and the `X-RateLimit-*` headers are respected. A trial key needs at most 288 requests a day (quota 500).
- Thread-safe; `await guard.acheck(...)` for asyncio. Logs go to `logging.getLogger("ers_guard")`; the key is never logged.

## Command line

```bash
ers-guard check ETHUSDT LONG --hold 8h --json
ers-guard check ETHUSDT LONG --fail-on HIGH && ./my_entry.sh      # exit 0 ok, 2 level matched, 3 UNKNOWN/NOT_COVERED
ers-guard status                                                  # plan, quota left, as_of, next update, coins
ers-guard serve --port 8787 --file ers_state.json                 # local sidecar
```

## Any language: the sidecar

`ers-guard serve` keeps one shared cache and listens on **127.0.0.1 only**:

- `GET http://127.0.0.1:8787/check?symbol=ETHUSDT&side=LONG&hold=60m` → the result as JSON
- `GET /state` → every row · `GET /health`
- with `--file`, the whole state is written atomically to a JSON file every cycle (for bots that read files).
  **On Windows, open the file, read it and close it at once (or use the HTTP endpoint):** a reader that keeps the
  file open blocks the update. The sidecar then retries, keeps the previous file and counts the miss in
  `/health` (`file_write_failures`); it never stops answering HTTP.

Snippets: [`examples/sidecar_curl.sh`](https://github.com/entryriskscore/ers-guard/blob/main/examples/sidecar_curl.sh),
[`examples/go/main.go`](https://github.com/entryriskscore/ers-guard/blob/main/examples/go/main.go),
[`examples/csharp/Program.cs`](https://github.com/entryriskscore/ers-guard/blob/main/examples/csharp/Program.cs).

## Integrations

- **Freqtrade** — [`integrations/freqtrade`](https://github.com/entryriskscore/ers-guard/tree/main/integrations/freqtrade): `ErsGuardMixin` adds the check to
  `confirm_trade_entry` (entries only; exits are never blocked) and an example strategy.
- **Hummingbot** — [`integrations/hummingbot/guarded_order_script.py`](https://github.com/entryriskscore/ers-guard/blob/main/integrations/hummingbot/guarded_order_script.py):
  checks before placing an order.
- **ccxt** — [`integrations/ccxt/guarded.py`](https://github.com/entryriskscore/ers-guard/blob/main/integrations/ccxt/guarded.py): `guarded_create_order(exchange, symbol,
  type, side, amount, price, params)`; `reduceOnly` orders pass through.
- **JavaScript / TypeScript (Node 18+)** — [`js/ers-guard.js`](https://github.com/entryriskscore/ers-guard/blob/main/js/ers-guard.js): same caching rules, no dependencies.
  ```js
  const { ErsGuard } = require('./js/ers-guard.js');
  const guard = new ErsGuard();                  // ERS_API_KEY from the environment
  if (await guard.allowEntry('ETH/USDT:USDT', 'LONG', { block: ['HIGH'] })) { /* your order */ }
  ```
- Symbols such as `ETH/USDT:USDT`, `ETH/USDT`, `ETH-USDT-SWAP`, `ETH_USDT`, `ETHUSDT.P` are normalised to `ETHUSDT`.

## Using an AI coding assistant?

Paste one of these into Claude Code, Cursor, Codex, Windsurf, Antigravity or any other assistant.

**Add Guard to a Python bot**
```text
Add an entry-risk check to my trading bot using ERS Guard (https://github.com/entryriskscore/ers-guard).
First read https://entryriskscore.com/llms.txt and this repository's README.
Rules: read the API key from the ERS_API_KEY environment variable and never hard-code it;
call guard.allow_entry(symbol, side, block={"HIGH"}) right before opening a position and never before closing one;
keep my strategy logic unchanged; ask me whether UNKNOWN should allow or block entries;
add a short test with a fake response. It is a risk check, not a trading signal — say so in a code comment.
```

**Add Guard to a Freqtrade strategy**
```text
Add ERS Guard (https://github.com/entryriskscore/ers-guard) to my Freqtrade strategy using the mixin in
integrations/freqtrade. Read the README first. Use confirm_trade_entry only (never block exits), read the key from
ERS_API_KEY, keep my indicators and signals unchanged, ask me about the UNKNOWN policy, and show me how to dry-run it.
```

**Add Guard to a Node.js bot**
```text
Add an entry-risk check to my Node.js bot with js/ers-guard.js from https://github.com/entryriskscore/ers-guard
(Node 18+, no dependencies). Read the README first. Read the key from process.env.ERS_API_KEY, check right before
opening a position (never before closing), respect the 5-minute cache, ask me about the UNKNOWN policy, add a small test.
```

## FAQ

**Is this a trading signal?** No. It is a measurement of entry-timing risk. Your bot keeps all its logic; Guard only
gives it a level you can use in your own rules.

**Why not a probability?** The Risk Score ranks this moment against the coin's own history. How often HIGH moments
were followed by an adverse move is published every day, including the days the score is wrong, in the
[ledger](https://entryriskscore.com/ledger).

**Certificate errors on Windows or old systems?** `pip install certifi` — Guard uses it automatically if present —
or update the system's CA certificates.

**Can I test without a key?** The tests run against a local fake API: `python -m unittest discover -s tests`.
With your own key: `python tools/live_check.py --key-file path/to/key.txt`.

Docs: https://entryriskscore.com/docs · API reference: https://entryriskscore.com/docs/api ·
MCP for AI agents: https://entryriskscore.com/docs/mcp

**Hosted MCP server.** `https://entryriskscore.com/api/v1/mcp` (Streamable HTTP, the same API key in an
`X-API-Key` or `Authorization: Bearer` header, four read-only tools). MCP Registry name:
`io.github.entryriskscore/entry-risk-score`; its entry is [`mcp/server.json`](https://github.com/entryriskscore/ers-guard/blob/main/mcp/server.json).

## Data Notice

Entry Risk Score is a data service that measures entry-timing risk on Binance USDT-M futures. It is not a signal, not
investment advice, and makes no promise of returns. Published rates describe the past and do not guarantee future
results. You are solely responsible for your trading decisions.

MIT licensed. See [LICENSE](https://github.com/entryriskscore/ers-guard/blob/main/LICENSE), [SECURITY.md](https://github.com/entryriskscore/ers-guard/blob/main/SECURITY.md),
[CONTRIBUTING.md](https://github.com/entryriskscore/ers-guard/blob/main/CONTRIBUTING.md).
