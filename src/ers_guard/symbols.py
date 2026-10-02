"""Symbol normalisation: exchange-style inputs to Binance USDT-M names (ETHUSDT). Unknown input -> None."""
import re

_SEP = re.compile(r'[/\-_: ]+')


def normalize_symbol(s):
    """'ETH/USDT:USDT', 'ETH/USDT', 'eth-usdt', 'ETH-USDT-SWAP', 'ETH_USDT', 'ETHUSDT', 'ETHUSDT.P' -> 'ETHUSDT'.
    Returns None for anything that is not a USDT-margined perpetual name."""
    if not isinstance(s, str):
        return None
    t = s.strip().upper()
    if t.endswith('.P'):
        t = t[:-2]
    for suffix in ('-SWAP', '_PERP', '-PERP', 'PERP', ':USDT'):
        if t.endswith(suffix) and len(t) > len(suffix):
            t = t[: -len(suffix)]
    parts = [p for p in _SEP.split(t) if p]
    if len(parts) == 2 and parts[1] == 'USDT':
        t = parts[0] + 'USDT'
    elif len(parts) == 1:
        t = parts[0]
    else:
        return None
    return t if re.fullmatch(r'[A-Z0-9]{2,16}USDT', t) else None
