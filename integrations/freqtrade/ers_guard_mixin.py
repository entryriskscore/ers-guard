"""Freqtrade: skip entries while the coin/side is HIGH entry risk.

    from ers_guard_mixin import ErsGuardMixin
    class MyStrategy(ErsGuardMixin, IStrategy):
        ers_block = {"HIGH"}          # levels that stop an entry
        ers_hold = "60m"              # 60m | 8h | 24h
        ...

Your strategy keeps all its own logic; this only adds a check in confirm_trade_entry (called by Freqtrade right
before an entry order). Exits are never blocked.
"""
import logging

from ers_guard import Guard

log = logging.getLogger('ers_guard.freqtrade')


class ErsGuardMixin:
    ers_block = {'HIGH'}
    ers_hold = '60m'
    ers_on_unknown = 'allow'
    _ers_guard = None

    @property
    def ers_guard(self):
        if self._ers_guard is None:
            type(self)._ers_guard = Guard(on_unknown=self.ers_on_unknown)
        return self._ers_guard

    def confirm_trade_entry(self, pair, order_type, amount, rate, time_in_force, current_time, entry_tag=None,
                            side='long', **kwargs):
        base = getattr(super(), 'confirm_trade_entry', None)
        if base is not None and not base(pair, order_type, amount, rate, time_in_force, current_time,
                                         entry_tag=entry_tag, side=side, **kwargs):
            return False
        r = self.ers_guard.check(pair, 'SHORT' if str(side).lower() == 'short' else 'LONG', self.ers_hold)
        if r.level in self.ers_block:
            log.info('ers_guard: skipping %s %s entry: %s', pair, side, r.reason)
            return False
        if r.level in ('UNKNOWN', 'NOT_COVERED'):
            return self.ers_on_unknown == 'allow'
        return True
