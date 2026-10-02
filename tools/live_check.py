#!/usr/bin/env python3
"""Run on your own PC against the real API with your test key:

    python tools/live_check.py --key-file C:\\path\\to\\ers_key.txt

Reads the key from the file (never from the command line), prints only results, never the key."""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from ers_guard import Guard  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--key-file', required=True)
    p.add_argument('--base', default='https://entryriskscore.com')
    a = p.parse_args()
    with open(a.key_file, encoding='utf-8') as f:
        key = f.read().strip()
    g = Guard(api_key=key, base_url=a.base)
    st = g.state()
    print('plan:', st.get('plan'), '| quota left:', st.get('quota_remaining'),
          '| next update:', st.get('next_update_at'))
    print('covered:', len(st.get('covered') or []), 'symbols', '| error:', st.get('last_error') or st.get('reason'))
    for sym, side, hold in (('BTCUSDT', 'LONG', '60m'), ('ETHUSDT', 'SHORT', '60m'), ('ETHUSDT', 'SHORT', '8h'),
                            ('ARBUSDT', 'LONG', '60m'), ('NOTACOIN', 'LONG', '60m')):
        r = g.check(sym, side, hold)
        sc = f' {int(r.score + 0.5)}/100' if r.score is not None else ''
        print(f'{sym:10} {side:5} {hold:4} {r.level:11}{sc:8} {r.reason}')
    print('requests made:', g.requests_made, '(one per 5-minute cycle at most)')


if __name__ == '__main__':
    main()
