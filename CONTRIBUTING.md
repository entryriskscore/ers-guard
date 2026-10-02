# Contributing

- Keep the runtime dependency-free (Python standard library; `certifi` stays optional).
- Guard must never compute or guess a score: it only reads the public API.
- Never present stale data as current: older than 12 minutes is UNKNOWN.
- Every change comes with a test against `tests/fake_api.py`; run `python -m unittest discover -s tests` and
  `ruff check src tests integrations examples tools`.
- Wording follows the service: Risk Score N/100, HIGH / ELEVATED / NORMAL / MEASURING, "not a probability". Guard is a
  measurement for your own rules, not advice.
