from __future__ import annotations

import pandas as pd

from freqtrade.strategy.interface import IStrategy

from indicators import bollinger_bands, crossed_above, crossed_below, directional_movement, typical_price
from topstep_mixin import TopstepMixin


class ZaratustraV13(TopstepMixin, IStrategy):
    """
    Zaratustra V13 — DI trend + Bollinger breakout entries.
    Long: DI alignment or close crossing above upper Bollinger band.
    Short: DI alignment or close crossing below lower Bollinger band.
    """

    timeframe = "5m"
    startup_candle_count = 200
    can_short = True

    stoploss = -0.296
    minimal_roi: dict[str, float] = {}

    trailing_stop = True
    trailing_stop_positive = 0.01
    trailing_stop_positive_offset = 0.1
    trailing_only_offset_is_reached = True

    use_exit_signal = False
    exit_profit_only = True

    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        df = dataframe.copy()
        df["adx"], df["dx"], df["pdi"], df["mdi"] = directional_movement(df)
        df["bbl"], df["bbm"], df["bbu"] = bollinger_bands(typical_price(df), window=20, stds=2.0)
        return df

    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        df = dataframe.copy()
        df["enter_long"] = False
        df["enter_short"] = False
        df["enter_tag"] = ""

        long_di = (
            (df["dx"] > df["mdi"])
            & (df["adx"] > df["mdi"])
            & (df["pdi"] > df["mdi"])
        )
        df.loc[long_di, "enter_long"] = True
        df.loc[long_di, "enter_tag"] = "Long DI enter"

        long_bb = crossed_above(df["close"], df["bbu"])
        df.loc[long_bb, "enter_long"] = True
        df.loc[long_bb, "enter_tag"] = "Long Bollinger enter"

        short_di = (
            (df["dx"] > df["mdi"])
            & (df["adx"] > df["pdi"])
            & (df["mdi"] > df["pdi"])
        )
        df.loc[short_di, "enter_short"] = True
        df.loc[short_di, "enter_tag"] = "Short DI enter"

        short_bb = crossed_below(df["close"], df["bbl"])
        df.loc[short_bb, "enter_short"] = True
        df.loc[short_bb, "enter_tag"] = "Short Bollinger enter"

        return df

    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        df = dataframe.copy()
        df["exit_long"] = False
        df["exit_short"] = False
        return df
