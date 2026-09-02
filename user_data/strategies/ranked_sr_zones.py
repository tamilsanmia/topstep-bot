"""
Ranked Support & Resistance Zones (Zeiierman) — Pine v6 port.

Licensed under CC BY-NC-SA 4.0 (original Pine indicator © Zeiierman).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd


DirectionFilter = Literal["All", "Support Only", "Resistance Only"]


@dataclass
class RankedSRConfig:
    visible_limit: int = 8
    stored_limit: int = 60
    pivot_span: int = 5
    min_swing_atr: float = 0.15
    absorb_atr: float = 0.55
    zone_atr_width: float = 0.40
    vol_len: int = 20
    trend_len: int = 50
    atr_len: int = 14
    break_atr: float = 0.12
    keep_broken_count: int = 4
    zone_max_age: int = 450
    direction_filter: DirectionFilter = "All"
    mintick: float = 0.01


@dataclass
class RankedZone:
    score: float
    top: float
    bottom: float
    mid: float
    dir: int
    born_bar: int
    left_time: int
    width: float
    mitigation: float = 0.0
    touch_count: float = 0.0
    vol_score: float = 1.0
    trend_score: float = 0.0
    swing_score: float = 0.0
    bull_strength: int = 0
    bear_strength: int = 0
    broken: bool = False


def _zone_score(
    width: float,
    vol_score: float,
    trend_score: float,
    swing_score: float,
    mitigation: float,
    touches: float,
    age: int,
    atr: float,
) -> float:
    size_norm = min(width / atr, 1.0) if atr > 0 else 0.0
    vol_norm = min(vol_score / 2.0, 1.0)
    swing_norm = min(swing_score / 1.5, 1.0)
    touch_norm = min(touches / 4.0, 1.0)
    age_norm = min(age / max(450, 1), 1.0)

    raw = size_norm * 20.0 + vol_norm * 18.0 + trend_score * 12.0 + swing_norm * 28.0 + touch_norm * 16.0 + 10.0
    penalty = mitigation * 22.0 + age_norm * 10.0
    return max(min(raw - penalty, 100.0), 0.0)


def _strengths(dir_: int, score: float, trend_score: float, mitigation: float) -> tuple[int, int]:
    score_norm = max(min(score, 100.0), 0.0)
    if score_norm >= 75:
        zone_side = 72 + (score_norm - 75) * 1.12
    elif score_norm >= 45:
        zone_side = 48 + (score_norm - 45) * 0.75
    else:
        zone_side = score_norm * 1.05

    zone_side += trend_score * 6.0
    zone_side -= mitigation * 28.0
    zone_side = max(min(zone_side, 100.0), 0.0)

    opposite_side = 5.0 + mitigation * 65.0 + score_norm * 0.08
    opposite_side = max(min(opposite_side, 100.0), 0.0)

    bull = int(zone_side) if dir_ == -1 else int(opposite_side)
    bear = int(zone_side) if dir_ == 1 else int(opposite_side)
    return bull, bear


def _swing_quality(
    price: float,
    dir_: int,
    high: np.ndarray,
    low: np.ndarray,
    pivot_bar: int,
    atr: float,
) -> float:
    if atr <= 0 or pivot_bar <= 0 or pivot_bar + 1 >= len(high):
        return 0.0
    if dir_ == 1:
        local_max = max(float(high[pivot_bar - 1]), float(high[pivot_bar + 1]))
        return max((price - local_max) / atr, 0.0)
    local_min = min(float(low[pivot_bar - 1]), float(low[pivot_bar + 1]))
    return max((local_min - price) / atr, 0.0)


def _overlaps(
    zone: RankedZone,
    new_top: float,
    new_bottom: float,
    new_dir: int,
    absorb_atr: float,
    atr: float,
    mintick: float,
) -> bool:
    overlap_top = min(zone.top, new_top)
    overlap_bottom = max(zone.bottom, new_bottom)
    overlap = max(overlap_top - overlap_bottom, 0.0)
    smaller = min(
        max(zone.top - zone.bottom, mintick),
        max(new_top - new_bottom, mintick),
    )
    same_side = zone.dir == new_dir
    close_mid = abs(zone.mid - (new_top + new_bottom) * 0.5) <= absorb_atr * atr
    meaningful_overlap = (overlap / smaller >= 0.35) if smaller > 0 else False
    return same_side and (close_mid or meaningful_overlap)


def _can_display(zone: RankedZone, direction_filter: DirectionFilter) -> bool:
    if direction_filter == "All":
        return True
    if direction_filter == "Support Only":
        return zone.dir == -1
    return zone.dir == 1


def _pivot_high(high: np.ndarray, i: int, span: int) -> float | None:
    if i < 2 * span:
        return None
    p = i - span
    window = high[p - span : p + span + 1]
    if high[p] == np.max(window):
        return float(high[p])
    return None


def _pivot_low(low: np.ndarray, i: int, span: int) -> float | None:
    if i < 2 * span:
        return None
    p = i - span
    window = low[p - span : p + span + 1]
    if low[p] == np.min(window):
        return float(low[p])
    return None


def compute_ranked_sr_zones(dataframe: pd.DataFrame, config: RankedSRConfig | None = None) -> pd.DataFrame:
    """Bar-by-bar Zeiierman ranked S/R engine; adds zone + nearest-level columns."""
    cfg = config or RankedSRConfig()
    df = dataframe.copy()
    n = len(df)

    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    volume = df["volume"].to_numpy(dtype=float)

    atr_raw = pd.Series(high - low).rolling(cfg.atr_len).mean().to_numpy()
    atr = np.where((np.isnan(atr_raw)) | (atr_raw == 0), cfg.mintick * 10.0, atr_raw)
    vol_base = pd.Series(volume).rolling(cfg.vol_len).mean().to_numpy()
    trend_base = pd.Series(close).ewm(span=cfg.trend_len, adjust=False).mean().to_numpy()

    dates = df["date"].astype("int64").to_numpy() if "date" in df.columns else np.arange(n)

    sr_zones: list[RankedZone] = []
    broken_zones: list[RankedZone] = []

    limit = cfg.visible_limit
    out: dict[str, np.ndarray] = {
        "sr_nearest_support": np.full(n, np.nan),
        "sr_nearest_resistance": np.full(n, np.nan),
        "sr_support_created": np.zeros(n, dtype=bool),
        "sr_resistance_created": np.zeros(n, dtype=bool),
        "sr_support_break": np.zeros(n, dtype=bool),
        "sr_resistance_break": np.zeros(n, dtype=bool),
        "sr_top_rank_support": np.zeros(n, dtype=bool),
        "sr_top_rank_resistance": np.zeros(n, dtype=bool),
    }
    for rank in range(1, limit + 1):
        out[f"sr_top_{rank}"] = np.full(n, np.nan)
        out[f"sr_bottom_{rank}"] = np.full(n, np.nan)
        out[f"sr_mid_{rank}"] = np.full(n, np.nan)
        out[f"sr_dir_{rank}"] = np.zeros(n, dtype=int)
    for rank in range(1, 5):
        out[f"sr_sup_top_{rank}"] = np.full(n, np.nan)
        out[f"sr_sup_bottom_{rank}"] = np.full(n, np.nan)
        out[f"sr_sup_mid_{rank}"] = np.full(n, np.nan)
        out[f"sr_res_top_{rank}"] = np.full(n, np.nan)
        out[f"sr_res_bottom_{rank}"] = np.full(n, np.nan)
        out[f"sr_res_mid_{rank}"] = np.full(n, np.nan)

    def add_zone(pivot_price: float, dir_: int, pivot_bar: int, pivot_time: int, bar_i: int) -> bool:
        nonlocal sr_zones
        half = cfg.zone_atr_width * atr[bar_i] * 0.5
        top = pivot_price + half
        bottom = pivot_price - half
        mid = pivot_price
        width = max(top - bottom, cfg.mintick)
        vol_score = (
            float(volume[pivot_bar] / vol_base[bar_i])
            if vol_base[bar_i] not in (0,) and not np.isnan(vol_base[bar_i])
            else 1.0
        )
        trend_score = (
            1.0
            if (dir_ == -1 and pivot_price > trend_base[bar_i])
            or (dir_ == 1 and pivot_price < trend_base[bar_i])
            else 0.0
        )
        swing_score = _swing_quality(pivot_price, dir_, high, low, pivot_bar, float(atr[bar_i]))
        mitigation = 0.0
        touches = 0.0
        age = bar_i - pivot_bar
        score = _zone_score(width, vol_score, trend_score, swing_score, mitigation, touches, age, float(atr[bar_i]))
        bull_strength, bear_strength = _strengths(dir_, score, trend_score, mitigation)

        absorbed = False
        created = False
        for idx, old in enumerate(sr_zones):
            if _overlaps(old, top, bottom, dir_, cfg.absorb_atr, float(atr[bar_i]), cfg.mintick) and not absorbed:
                old.top = max(old.top, top)
                old.bottom = min(old.bottom, bottom)
                old.mid = (old.top + old.bottom) * 0.5
                old.width = max(old.top - old.bottom, cfg.mintick)
                old.born_bar = min(old.born_bar, pivot_bar)
                old.left_time = min(old.left_time, pivot_time)
                old.vol_score = max(old.vol_score, vol_score)
                old.trend_score = max(old.trend_score, trend_score)
                old.swing_score = max(old.swing_score, swing_score)
                old.mitigation = 0.0
                old.touch_count += 1.0
                old.score = max(old.score, score) + 3.0
                old.bull_strength = max(old.bull_strength, bull_strength)
                old.bear_strength = max(old.bear_strength, bear_strength)
                sr_zones[idx] = old
                absorbed = True

        if not absorbed:
            sr_zones.append(
                RankedZone(
                    score=score,
                    top=top,
                    bottom=bottom,
                    mid=mid,
                    dir=dir_,
                    born_bar=pivot_bar,
                    left_time=pivot_time,
                    width=width,
                    mitigation=mitigation,
                    touch_count=touches,
                    vol_score=vol_score,
                    trend_score=trend_score,
                    swing_score=swing_score,
                    bull_strength=bull_strength,
                    bear_strength=bear_strength,
                )
            )
            created = True
        return created

    previous_leader_key = ""

    for i in range(n):
        if i >= 2 * cfg.pivot_span:
            pivot_bar = i - cfg.pivot_span
            ph = _pivot_high(high, i, cfg.pivot_span)
            if ph is not None:
                sq = _swing_quality(ph, 1, high, low, pivot_bar, float(atr[i]))
                if sq >= cfg.min_swing_atr and add_zone(ph, 1, pivot_bar, int(dates[pivot_bar]), i):
                    out["sr_resistance_created"][i] = True

            pl = _pivot_low(low, i, cfg.pivot_span)
            if pl is not None:
                sq = _swing_quality(pl, -1, high, low, pivot_bar, float(atr[i]))
                if sq >= cfg.min_swing_atr and add_zone(pl, -1, pivot_bar, int(dates[pivot_bar]), i):
                    out["sr_support_created"][i] = True

        remaining: list[RankedZone] = []
        for z in sr_zones:
            age = i - z.born_bar
            expired = age > cfg.zone_max_age
            touched = high[i] >= z.bottom and low[i] <= z.top
            broken_support = z.dir == -1 and close[i] < z.bottom - cfg.break_atr * atr[i]
            broken_resistance = z.dir == 1 and close[i] > z.top + cfg.break_atr * atr[i]

            if touched and not broken_support and not broken_resistance:
                z.touch_count += 0.20
                fill_distance = z.top - low[i] if z.dir == -1 else high[i] - z.bottom
                z.mitigation = min(max(fill_distance / max(z.width, cfg.mintick), 0.0), 1.0)

            z.score = _zone_score(
                z.width, z.vol_score, z.trend_score, z.swing_score, z.mitigation, z.touch_count, age, float(atr[i])
            )
            bull, bear = _strengths(z.dir, z.score, z.trend_score, z.mitigation)
            z.bull_strength = bull
            z.bear_strength = bear

            if expired:
                continue
            if broken_support or broken_resistance:
                z.broken = True
                out["sr_support_break"][i] = out["sr_support_break"][i] or broken_support
                out["sr_resistance_break"][i] = out["sr_resistance_break"][i] or broken_resistance
                if cfg.keep_broken_count > 0:
                    broken_zones.append(z)
                    while len(broken_zones) > cfg.keep_broken_count:
                        broken_zones.pop(0)
            else:
                remaining.append(z)
        sr_zones = remaining

        sr_zones.sort(key=lambda z: z.score, reverse=True)
        while len(sr_zones) > cfg.stored_limit:
            sr_zones.pop()

        if sr_zones:
            leader = sr_zones[0]
            leader_key = f"{leader.left_time}_{leader.dir}"
            if leader_key != previous_leader_key:
                if leader.dir == -1:
                    out["sr_top_rank_support"][i] = True
                else:
                    out["sr_top_rank_resistance"][i] = True
                previous_leader_key = leader_key

        nearest_support = np.nan
        nearest_resistance = np.nan
        visible_count = 0
        sup_plot = 0
        res_plot = 0
        for z in sr_zones:
            if not _can_display(z, cfg.direction_filter):
                continue
            if visible_count >= cfg.visible_limit:
                break
            rank = visible_count + 1
            out[f"sr_top_{rank}"][i] = z.top
            out[f"sr_bottom_{rank}"][i] = z.bottom
            out[f"sr_mid_{rank}"][i] = z.mid
            out[f"sr_dir_{rank}"][i] = z.dir
            visible_count += 1

            if z.dir == -1 and sup_plot < 4:
                sup_plot += 1
                out[f"sr_sup_top_{sup_plot}"][i] = z.top
                out[f"sr_sup_bottom_{sup_plot}"][i] = z.bottom
                out[f"sr_sup_mid_{sup_plot}"][i] = z.mid
            elif z.dir == 1 and res_plot < 4:
                res_plot += 1
                out[f"sr_res_top_{res_plot}"][i] = z.top
                out[f"sr_res_bottom_{res_plot}"][i] = z.bottom
                out[f"sr_res_mid_{res_plot}"][i] = z.mid

            if z.dir == -1 and z.mid < close[i]:
                nearest_support = z.mid if np.isnan(nearest_support) or z.mid > nearest_support else nearest_support
            if z.dir == 1 and z.mid > close[i]:
                nearest_resistance = (
                    z.mid if np.isnan(nearest_resistance) or z.mid < nearest_resistance else nearest_resistance
                )

        out["sr_nearest_support"][i] = nearest_support
        out["sr_nearest_resistance"][i] = nearest_resistance

    for key, values in out.items():
        df[key] = values
    return df
