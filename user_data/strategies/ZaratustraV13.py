from __future__ import annotations

import pandas as pd

from freqtrade.strategy.interface import IStrategy

from topstep_mixin import TopstepMixin


class ZaratustraV13(TopstepMixin, IStrategy):
    """
    EMA trend follow — signal on every candle while trend holds.
    Long: EMA 30 > EMA 50
    Short: EMA 30 < EMA 50
    SL: 0.1% | TP: 0.2%
    """

    timeframe = "5m"
    startup_candle_count = 200
    can_short = True

    stoploss = -0.001
    minimal_roi: dict[str, float] = {"0": 0.002}

    trailing_stop = False

    use_exit_signal = False
    exit_profit_only = False

    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        df = dataframe.copy()
        df["ema30"] = df["close"].ewm(span=30, adjust=False).mean()
        df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
        return df

    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        df = dataframe.copy()
        df["enter_long"] = False
        df["enter_short"] = False
        df["enter_tag"] = ""

        long_trend = df["ema30"] > df["ema50"]
        df.loc[long_trend, "enter_long"] = True
        df.loc[long_trend, "enter_tag"] = "Long EMA30>EMA50"

        short_trend = df["ema30"] < df["ema50"]
        df.loc[short_trend, "enter_short"] = True
        df.loc[short_trend, "enter_tag"] = "Short EMA30<EMA50"

        return df

    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        df = dataframe.copy()
        df["exit_long"] = False
        df["exit_short"] = False
        return df
