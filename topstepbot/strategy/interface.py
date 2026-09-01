from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd


class IStrategy(ABC):
    """
    Freqtrade-inspired strategy interface.

    Subclass and implement populate_* methods in user_data/strategies/.
    """

    # Strategy metadata
    timeframe: str = "5m"
    startup_candle_count: int = 200

    # Risk (optional — engine may override from config)
    stoploss: float | None = None
    minimal_roi: dict[str, float] | None = None

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    @abstractmethod
    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict[str, Any]) -> pd.DataFrame:
        """Add indicator columns to OHLCV dataframe."""

    @abstractmethod
    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict[str, Any]) -> pd.DataFrame:
        """Set dataframe['enter_long'] and/or dataframe['enter_short'] bool columns."""

    @abstractmethod
    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict[str, Any]) -> pd.DataFrame:
        """Set dataframe['exit_long'] and/or dataframe['exit_short'] bool columns."""

    def confirm_trade_entry(
        self,
        side: str,
        dataframe: pd.DataFrame,
        metadata: dict[str, Any],
    ) -> bool:
        """Last-chance filter before opening a trade."""
        return True

    def confirm_trade_exit(
        self,
        side: str,
        dataframe: pd.DataFrame,
        metadata: dict[str, Any],
    ) -> bool:
        return True

    def analyze(self, dataframe: pd.DataFrame, metadata: dict[str, Any]) -> pd.DataFrame:
        df = self.populate_indicators(dataframe.copy(), metadata)
        df = self.populate_entry_trend(df, metadata)
        df = self.populate_exit_trend(df, metadata)
        for col in ("enter_long", "enter_short", "exit_long", "exit_short"):
            if col not in df.columns:
                df[col] = False
        return df

    def latest_signal(self, dataframe: pd.DataFrame) -> dict[str, bool]:
        if dataframe.empty:
            return {"enter_long": False, "enter_short": False, "exit_long": False, "exit_short": False}
        row = dataframe.iloc[-1]
        return {
            "enter_long": bool(row.get("enter_long", False)),
            "enter_short": bool(row.get("enter_short", False)),
            "exit_long": bool(row.get("exit_long", False)),
            "exit_short": bool(row.get("exit_short", False)),
        }
