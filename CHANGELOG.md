# Changelog

## 0.1.1 — 2026-10-02
- Windows: the sidecar's state-file write no longer fails while a bot has the file open. The replace is retried with a
  short backoff (20 ms doubling to 200 ms, 10 tries); if the file stays locked the previous file is kept, the temp file
  is removed, one warning is logged for that cycle and `/health` counts `file_write_failures`. The sidecar keeps
  answering HTTP whatever happens to the file.
- Tests: the concurrent-reader test is valid on every OS; new tests for a temporarily and a permanently locked target.
- CI: Linux, Windows and macOS × Python 3.9–3.13 (macOS without 3.9), Node on every OS.

## 0.1.0 — 2026-10-05
- First release: Python package `ers_guard` (Guard, Result, allow_entry, acheck), CLI `ers-guard`
  (check, status, serve sidecar with JSON file), JavaScript client `js/ers-guard.js`, integrations for Freqtrade,
  Hummingbot and ccxt, Go and C# sidecar snippets, `tools/live_check.py`.
- One GET /api/v1/state per 5-minute update cycle (never more than once per 60 s), Retry-After respected, data older
  than 12 minutes reported as UNKNOWN, symbols outside the key's plan reported as NOT_COVERED.
