"""Example Freqtrade strategy with the entry-risk check. Copy ers_guard_mixin.py next to it in user_data/strategies,
`pip install ers-guard` (or put src/ers_guard on PYTHONPATH) and set ERS_API_KEY. The indicator logic below is a
placeholder for your own; the mixin only adds the check before entries."""
from ers_guard_mixin import ErsGuardMixin
from freqtrade.strategy import IStrategy  # noqa: F401  (needs Freqtrade)
from pandas import DataFrame


class GuardedSampleStrategy(ErsGuardMixin, IStrategy):
    INTERFACE_VERSION = 3
    timeframe = '5m'
    can_short = True
    minimal_roi = {'0': 0.02}
    stoploss = -0.02
    ers_block = {'HIGH'}
    ers_hold = '60m'

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['ema_fast'] = dataframe['close'].ewm(span=12).mean()
        dataframe['ema_slow'] = dataframe['close'].ewm(span=26).mean()
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe['ema_fast'] > dataframe['ema_slow'], 'enter_long'] = 1
        dataframe.loc[dataframe['ema_fast'] < dataframe['ema_slow'], 'enter_short'] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe
