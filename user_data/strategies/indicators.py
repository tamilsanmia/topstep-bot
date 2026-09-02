"""Pure-pandas technical indicators (talib/qtpylib equivalents)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def typical_price(dataframe: pd.DataFrame) -> pd.Series:
    return (dataframe["high"] + dataframe["low"] + dataframe["close"]) / 3.0


def bollinger_bands(
    series: pd.Series,
    window: int = 20,
    stds: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = series.rolling(window).mean()
    std = series.rolling(window).std()
    upper = mid + stds * std
    lower = mid - stds * std
    return lower, mid, upper


def crossed_above(series1: pd.Series, series2: pd.Series) -> pd.Series:
    return (series1 > series2) & (series1.shift(1) <= series2.shift(1))


def crossed_below(series1: pd.Series, series2: pd.Series) -> pd.Series:
    return (series1 < series2) & (series1.shift(1) >= series2.shift(1))


def stochastic_momentum_index(
    dataframe: pd.DataFrame,
    *,
    length: int = 13,
    smooth1: int = 25,
    smooth2: int = 2,
    signal_length: int = 12,
    source: str = "close",
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Stochastic Momentum Index (SMI) — matches TradingView ta.ema smoothing.

    Based on the Reverse Stochastic Momentum Index by The_Caretaker / everget SMI.
    """
    src = dataframe[source]
    highest = dataframe["high"].rolling(length).max()
    lowest = dataframe["low"].rolling(length).min()
    hl_mid = 0.5 * (highest + lowest)
    hl_range = highest - lowest

    numerator = (src - hl_mid).ewm(span=smooth1, adjust=False).mean().ewm(span=smooth2, adjust=False).mean()
    denominator = (0.5 * hl_range).ewm(span=smooth1, adjust=False).mean().ewm(span=smooth2, adjust=False).mean()
    denominator = denominator.replace(0, np.nan)

    smi = 100 * numerator / denominator
    signal = smi.ewm(span=signal_length, adjust=False).mean()
    hist = smi - signal
    return smi, signal, hist


def _wilder_smooth(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(alpha=1.0 / period, adjust=False).mean()


def directional_movement(dataframe: pd.DataFrame, period: int = 14) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    high = dataframe["high"]
    low = dataframe["low"]
    close = dataframe["close"]

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=dataframe.index,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=dataframe.index,
    )

    tr = pd.concat(
        [
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr = _wilder_smooth(tr, period).replace(0, np.nan)
    plus_di = 100.0 * _wilder_smooth(plus_dm, period) / atr
    minus_di = 100.0 * _wilder_smooth(minus_dm, period) / atr

    di_sum = (plus_di + minus_di).replace(0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / di_sum
    adx = _wilder_smooth(dx, period)

    return adx, dx, plus_di, minus_di
