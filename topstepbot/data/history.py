from __future__ import annotations

from typing import Any

import pandas as pd


def bars_to_dataframe(bars: list[dict[str, Any]]) -> pd.DataFrame:
    if not bars:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    rows = []
    for bar in bars:
        ts = bar.get("t") or bar.get("timestamp") or bar.get("time")
        rows.append(
            {
                "date": pd.to_datetime(ts, utc=True),
                "open": float(bar.get("o") or bar.get("open") or 0),
                "high": float(bar.get("h") or bar.get("high") or 0),
                "low": float(bar.get("l") or bar.get("low") or 0),
                "close": float(bar.get("c") or bar.get("close") or 0),
                "volume": float(bar.get("v") or bar.get("volume") or 0),
            }
        )

    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    return df
