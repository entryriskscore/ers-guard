"""Hummingbot script example: check entry risk before placing an order. Put this file in hummingbot/scripts,
install ers_guard into Hummingbot's environment and set ERS_API_KEY. The order logic is a placeholder for yours."""
from decimal import Decimal

from ers_guard import Guard

GUARD = Guard()


def entry_allowed(guard, trading_pair, is_buy, block=('HIGH',), hold='60m'):
    """Hummingbot pairs look like 'ETH-USDT'; Guard normalises them. Exits are not checked."""
    return guard.allow_entry(trading_pair, 'LONG' if is_buy else 'SHORT', hold=hold, block=block)


try:
    from hummingbot.core.data_type.common import OrderType
    from hummingbot.strategy.script_strategy_base import ScriptStrategyBase
except ImportError:                                   # lets the helper above be tested without Hummingbot
    ScriptStrategyBase = object
    OrderType = None


class GuardedOrderScript(ScriptStrategyBase):
    exchange = 'binance_perpetual'
    trading_pair = 'ETH-USDT'
    markets = {exchange: {trading_pair}}
    order_amount = Decimal('0.01')

    def on_tick(self):
        if not self.my_entry_condition():             # your own logic decides whether to enter at all
            return
        if not entry_allowed(GUARD, self.trading_pair, is_buy=True):
            self.logger().info('ers_guard: HIGH entry risk for %s LONG, entry skipped', self.trading_pair)
            return
        price = self.connectors[self.exchange].get_mid_price(self.trading_pair)
        self.buy(self.exchange, self.trading_pair, self.order_amount, OrderType.LIMIT, price)

    def my_entry_condition(self):
        return False                                  # placeholder: replace with your strategy
