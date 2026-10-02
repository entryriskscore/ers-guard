"""ccxt: create an order only after the entry-risk check. Orders with reduceOnly (exits) are never blocked."""
import logging

from ers_guard import Guard

log = logging.getLogger('ers_guard.ccxt')


class EntryBlocked(Exception):
    def __init__(self, result):
        super().__init__(f'{result.symbol} {result.side}: {result.level} — {result.reason}')
        self.result = result


def guarded_create_order(exchange, symbol, type, side, amount, price=None, params=None, guard=None, hold='60m',
                         block=('HIGH',), on_unknown='allow'):
    """Same arguments as exchange.create_order(symbol, type, side, amount, price, params) plus the Guard policy.
    Raises EntryBlocked when the level is in `block` (or UNKNOWN/NOT_COVERED with on_unknown="block")."""
    params = params or {}
    if params.get('reduceOnly') or params.get('reduce_only'):
        return exchange.create_order(symbol, type, side, amount, price, params)
    g = guard or Guard()
    r = g.check(symbol, 'LONG' if side.lower() == 'buy' else 'SHORT', hold)
    if r.level in set(block) or (r.level in ('UNKNOWN', 'NOT_COVERED') and on_unknown == 'block'):
        log.info('ers_guard: entry blocked: %s %s %s', symbol, side, r.level)
        raise EntryBlocked(r)
    return exchange.create_order(symbol, type, side, amount, price, params)
