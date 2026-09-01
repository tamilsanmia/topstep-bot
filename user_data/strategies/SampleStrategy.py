from __future__ import annotations

import pandas as pd

from topstepbot.strategy.interface import IStrategy


class SampleStrategy(IStrategy):
    """
    Simple EMA crossover for MNQ / futures.

    Long when fast EMA crosses above slow EMA.
    Short when fast EMA crosses below slow EMA.
    """

    timeframe = "5m"
    startup_candle_count = 100

    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        df = dataframe.copy()
        df["ema_fast"] = df["close"].ewm(span=9, adjust=False).mean()
        df["ema_slow"] = df["close"].ewm(span=21, adjust=False).mean()
        df["cross_up"] = (df["ema_fast"] > df["ema_slow"]) & (df["ema_fast"].shift(1) <= df["ema_slow"].shift(1))
        df["cross_down"] = (df["ema_fast"] < df["ema_slow"]) & (df["ema_fast"].shift(1) >= df["ema_slow"].shift(1))
        return df

    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        df = dataframe.copy()
        df["enter_long"] = df["cross_up"]
        df["enter_short"] = df["cross_down"]
        return df

    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        df = dataframe.copy()
        df["exit_long"] = df["cross_down"]
        df["exit_short"] = df["cross_up"]
        return df
