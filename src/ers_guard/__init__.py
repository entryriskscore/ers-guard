"""ers_guard — an entry-risk check for any trading bot, built on the Entry Risk Score API.

    from ers_guard import Guard
    guard = Guard()                               # reads ERS_API_KEY
    r = guard.check("ETHUSDT", "LONG", hold="60m")
    if guard.allow_entry("ETHUSDT", "LONG", block={"HIGH"}): ...

Guard reports a measurement; it is not a signal and decides nothing for you.
"""
__version__ = '0.1.1'

from .guard import HOLDS, NOTICE, ApiError, Guard, Result  # noqa: E402
from .symbols import normalize_symbol  # noqa: E402

__all__ = ['Guard', 'Result', 'ApiError', 'normalize_symbol', 'HOLDS', 'NOTICE', '__version__']
