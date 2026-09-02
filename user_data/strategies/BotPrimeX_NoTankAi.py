from __future__ import annotations

import logging
import warnings
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import talib.abstract as ta
from pandas import DataFrame
from scipy.signal import argrelextrema

from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy

from topstep_mixin import TopstepMixin
from ranked_sr_zones import RankedSRConfig, compute_ranked_sr_zones

warnings.filterwarnings("ignore")
warnings.simplefilter(action="ignore", category=pd.errors.PerformanceWarning)

logger = logging.getLogger(__name__)


class BotPrimeX_NoTankAi(TopstepMixin, IStrategy):
    """
    Minima/maxima reversal strategy for TopstepX CME micro futures.

    stake_is_lots: config stake_amount = contracts per entry / safety order.
    DCA adds equal or scaled lots on drawdown steps; stoploss is widened to fit safety orders.
    """

    timeframe = "5m"
    startup_candle_count = 500
    process_only_new_candles = True
    can_short = True

    # Room for safety orders before hard stop (0.8% vs 0.10% per-step DCA triggers).
    stoploss = -0.008
    minimal_roi = {
        "0": 0.004,
        "60": 0.003,
        "120": 0.0025,
        "240": 0.002,
        "360": 0.0015,
        "720": 0.001,
        "1440": 0.0008,
        "2880": 0.0005,
        "3600": 0.0003,
        "7200": 0.0002,
    }
    trailing_stop = False

    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    position_adjustment_enable = True
    max_entry_position_adjustment = 3

    # Safety-order DCA (profit triggers are negative price-move ratios).
    max_safety_orders = 2
    initial_safety_order_trigger = -0.0012
    safety_order_step_scale = 1.25
    safety_order_volume_scale = 1.0
    partial_exit_1 = 0.003
    partial_exit_2 = 0.005

    order_types = {
        "entry": "market",
        "exit": "market",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }

    cooldown_lookback = 1
    stop_duration = 4
    use_stop_protection = True

    # RSI filter (long below rsi_buy, short above rsi_sell).
    use_rsi_filter = True
    rsi_buy = 50
    rsi_sell = 50

    # MACD Histogram Displacement (Pine: MHD by displacement bars).
    use_mhd_filter = True
    mhd_fast = 12
    mhd_slow = 26
    mhd_signal = 9
    mhd_displacement = 1

    # Ranked Support & Resistance Zones (Zeiierman) — Pine defaults.
    use_sr_filter = True
    sr_visible_limit = 8
    sr_stored_limit = 60
    sr_pivot_span = 5
    sr_min_swing_atr = 0.15
    sr_absorb_atr = 0.55
    sr_zone_atr_width = 0.40
    sr_vol_len = 20
    sr_trend_len = 50
    sr_break_atr = 0.12
    sr_keep_broken = 4

    # CME Globex (America/Chicago): Sun 17:00 – Fri 16:00, daily halt 16:00–17:00.
    use_market_hours = True
    market_hours_tz = "America/Chicago"
    cme_halt_start = "16:00"
    cme_halt_end = "17:00"
    exit_at_cme_eod = True

    plot_config = {
        "main_plot": {
            "sr_nearest_support": {"color": "#1ad8c2"},
            "sr_nearest_resistance": {"color": "#d84c1a"},
            "sr_sup_top_1": {
                "color": "#1ad8c2",
                "fill_to": "sr_sup_bottom_1",
                "fill_color": "rgba(26, 216, 194, 0.22)",
            },
            "sr_sup_bottom_1": {"color": "#1ad8c2"},
            "sr_sup_top_2": {
                "color": "#1ad8c2",
                "fill_to": "sr_sup_bottom_2",
                "fill_color": "rgba(26, 216, 194, 0.22)",
            },
            "sr_sup_bottom_2": {"color": "#1ad8c2"},
            "sr_res_top_1": {
                "color": "#d84c1a",
                "fill_to": "sr_res_bottom_1",
                "fill_color": "rgba(216, 76, 26, 0.22)",
            },
            "sr_res_bottom_1": {"color": "#d84c1a"},
            "sr_res_top_2": {
                "color": "#d84c1a",
                "fill_to": "sr_res_bottom_2",
                "fill_color": "rgba(216, 76, 26, 0.22)",
            },
            "sr_res_bottom_2": {"color": "#d84c1a"},
        },
        "subplots": {
            "MHD": {
                "mhd_hist": {"color": "#ff00ff"},
                "mhd_hist_disp": {"color": "#00ffff"},
                "mhd_zero": {"color": "#606060"},
            },
            "RSI": {
                "rsi": {"color": "#b388ff"},
            },
            "Extrema": {
                "s_extrema": {"color": "#f53580"},
            },
        },
    }

    @property
    def protections(self):
        prot = [
            {"method": "CooldownPeriod", "stop_duration_candles": self.cooldown_lookback}
        ]
        if self.use_stop_protection:
            prot.append(
                {
                    "method": "StoplossGuard",
                    "lookback_period_candles": 24 * 3,
                    "trade_limit": 2,
                    "stop_duration_candles": self.stop_duration,
                    "only_per_pair": False,
                }
            )
        return prot

    @staticmethod
    def _hhmm_minutes(value: str) -> int:
        hour, minute = value.split(":")
        return int(hour) * 60 + int(minute)

    def _session_local(self, when: datetime) -> datetime:
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return when.astimezone(ZoneInfo(self.market_hours_tz))

    def _cme_is_open(self, weekday: int, minutes: int) -> bool:
        """CME Globex: closed Sat, Sun before 17:00, Fri from 16:00, and daily 16:00–17:00 halt."""
        halt_start = self._hhmm_minutes(self.cme_halt_start)
        halt_end = self._hhmm_minutes(self.cme_halt_end)
        if weekday == 5:
            return False
        if weekday == 6:
            return minutes >= halt_end
        if weekday == 4:
            return minutes < halt_start
        return not (halt_start <= minutes < halt_end)

    def _is_market_hours(self, when: datetime) -> bool:
        if not self.use_market_hours:
            return True
        local = self._session_local(when)
        minutes = local.hour * 60 + local.minute
        return self._cme_is_open(local.weekday(), minutes)

    def _is_cme_eod(self, when: datetime) -> bool:
        return self.exit_at_cme_eod and not self._is_market_hours(when)

    def _apply_market_hours(self, dataframe: DataFrame) -> DataFrame:
        if not self.use_market_hours:
            dataframe["market_hours"] = 1
            return dataframe
        ts = pd.to_datetime(dataframe["date"], utc=True).dt.tz_convert(self.market_hours_tz)
        minutes = ts.dt.hour * 60 + ts.dt.minute
        halt_start = self._hhmm_minutes(self.cme_halt_start)
        halt_end = self._hhmm_minutes(self.cme_halt_end)
        wd = ts.dt.weekday
        saturday = wd == 5
        sunday_closed = (wd == 6) & (minutes < halt_end)
        friday_closed = (wd == 4) & (minutes >= halt_start)
        daily_halt = (wd <= 3) & (minutes >= halt_start) & (minutes < halt_end)
        dataframe["market_hours"] = (~(saturday | sunday_closed | friday_closed | daily_halt)).astype(int)
        return dataframe

    @staticmethod
    def _config_lot_stake(config: dict) -> float:
        stake = config.get("stake_amount", 1)
        if isinstance(stake, (int, float)):
            return float(stake)
        return 1.0

    def _safety_trigger(self, safety_index: int) -> float:
        """Drawdown ratio required before safety order N (0 = first safety order)."""
        base = float(self.initial_safety_order_trigger)
        step = float(self.safety_order_step_scale)
        return base * (step**safety_index)

    def _safety_lot_stake(self, safety_index: int) -> float:
        """Stake returned to Freqtrade = lot count when stake_is_lots is enabled."""
        base_lots = self._config_lot_stake(self.config)
        scale = float(self.safety_order_volume_scale)
        return base_lots * (scale**safety_index)

    def custom_stake_amount(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_stake: float,
        min_stake: Optional[float],
        max_stake: float,
        leverage: float,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> float:
        """Initial entry: config lot count (stake_is_lots). Plan margin for 1 + max_safety_orders."""
        stake = self._config_lot_stake(self.config)
        if min_stake is not None:
            stake = max(stake, min_stake)
        return min(stake, max_stake)

    def confirm_trade_exit(
        self,
        pair: str,
        trade: Trade,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        exit_reason: str,
        current_time: datetime,
        **kwargs,
    ) -> bool:
        if exit_reason == "partial_exit" and trade.calc_profit_ratio(rate) < 0:
            logger.info("%s blocked partial exit while underwater", trade.pair)
            return False
        return True

    def confirm_trade_entry(
        self,
        pair: str,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        current_time: datetime,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> bool:
        if not self._is_market_hours(current_time):
            logger.info("%s skipped %s — outside CME Globex hours", pair, entry_tag or side)
            return False
        return True

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> Optional[str]:
        if self._is_cme_eod(current_time):
            return "eod"
        return None

    def check_entry_timeout(
        self,
        pair: str,
        trade: Trade,
        order,
        current_time: datetime,
        **kwargs,
    ) -> bool:
        return self._is_cme_eod(current_time)

    def check_exit_timeout(
        self,
        pair: str,
        trade: Trade,
        order,
        current_time: datetime,
        **kwargs,
    ) -> bool:
        return self._is_cme_eod(current_time)

    def bot_loop_start(self, current_time: datetime, **kwargs) -> None:
        """Cancel leftover working orders at the CME daily halt / weekend close."""
        if not self._is_cme_eod(current_time):
            return
        if not hasattr(self, "dp") or self.dp is None:
            return
        exchange = getattr(self.dp, "_exchange", None)
        if exchange is None:
            return
        for trade in Trade.get_open_trades():
            orders = list(getattr(trade, "open_orders", None) or [])
            for order in orders:
                order_id = getattr(order, "order_id", None)
                if not order_id:
                    continue
                try:
                    exchange.cancel_order(order_id, trade.pair)
                    logger.info("%s canceled pending order %s at CME EOD", trade.pair, order_id)
                except Exception as exc:
                    logger.warning("%s CME EOD cancel failed for %s: %s", trade.pair, order_id, exc)

    def adjust_trade_position(
        self,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        min_stake: Optional[float],
        max_stake: float,
        current_entry_rate: float,
        current_exit_rate: float,
        current_entry_profit: float,
        current_exit_profit: float,
        **kwargs,
    ) -> Optional[float] | tuple[Optional[float], str]:
        # Partial take-profits (Topstep-friendly price-move ratios).
        if current_profit >= float(self.partial_exit_2) and trade.nr_of_successful_exits == 1:
            return -(trade.stake_amount / 3), "tp2"
        if current_profit >= float(self.partial_exit_1) and trade.nr_of_successful_exits == 0:
            return -(trade.stake_amount / 4), "tp1"

        if not self._is_market_hours(current_time):
            return None

        entries = trade.nr_of_successful_entries
        max_safety = int(self.max_safety_orders)
        if entries > max_safety:
            return None

        safety_index = entries - 1
        trigger = self._safety_trigger(safety_index)
        if current_profit > trigger:
            return None

        stake = self._safety_lot_stake(safety_index)
        if min_stake is not None and stake < min_stake:
            stake = min_stake
        if stake > max_stake:
            logger.info(
                "%s SO%d skipped — need %s lots, max stake %s (margin)",
                trade.pair,
                safety_index + 1,
                stake,
                max_stake,
            )
            return None

        logger.info(
            "%s SO%d at profit %.3f%% (trigger %.3f%%), adding %s lots",
            trade.pair,
            safety_index + 1,
            current_profit * 100,
            trigger * 100,
            stake,
        )
        return stake, f"SO{safety_index + 1}"

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["rsi"] = ta.RSI(dataframe)
        dataframe["DI_values"] = ta.PLUS_DI(dataframe) - ta.MINUS_DI(dataframe)
        dataframe["DI_cutoff"] = 0
        dataframe["DI_catch"] = np.where(dataframe["DI_values"] > dataframe["DI_cutoff"], 0, 1)

        maxima = np.zeros(len(dataframe))
        minima = np.zeros(len(dataframe))
        max_peaks = argrelextrema(dataframe["close"].values, np.greater, order=5)[0]
        min_peaks = argrelextrema(dataframe["close"].values, np.less, order=5)[0]
        maxima[max_peaks] = 1
        minima[min_peaks] = 1
        dataframe["maxima"] = maxima
        dataframe["minima"] = minima

        dataframe["&s-extrema"] = 0
        dataframe.loc[min_peaks, "&s-extrema"] = -1
        dataframe.loc[max_peaks, "&s-extrema"] = 1
        dataframe["s_extrema"] = dataframe["&s-extrema"]

        dataframe["maxima_check"] = (
            dataframe["maxima"].rolling(4).apply(lambda x: int((x != 1).all()), raw=True).fillna(0)
        )
        dataframe["minima_check"] = (
            dataframe["minima"].rolling(4).apply(lambda x: int((x != 1).all()), raw=True).fillna(0)
        )

        mhd = ta.MACD(
            dataframe,
            fastperiod=int(self.mhd_fast),
            slowperiod=int(self.mhd_slow),
            signalperiod=int(self.mhd_signal),
        )
        disp = int(self.mhd_displacement)
        mhd_hist = mhd["macdhist"]
        dataframe["mhd_hist"] = mhd_hist
        # Pine plot(hist, offset=displacement): current bar shows hist from displacement bars ago.
        dataframe["mhd_hist_disp"] = mhd_hist.shift(disp)
        dataframe["mhd_zero"] = 0.0
        if self.use_rsi_filter:
            dataframe["rsi_long"] = (dataframe["rsi"] < int(self.rsi_buy)).astype(int)
            dataframe["rsi_short"] = (dataframe["rsi"] > int(self.rsi_sell)).astype(int)
        else:
            dataframe["rsi_long"] = 1
            dataframe["rsi_short"] = 1

        if self.use_mhd_filter:
            dataframe["mhd_long"] = (dataframe["mhd_hist"] > dataframe["mhd_hist_disp"]).astype(int)
            dataframe["mhd_short"] = (dataframe["mhd_hist"] < dataframe["mhd_hist_disp"]).astype(int)
        else:
            dataframe["mhd_long"] = 1
            dataframe["mhd_short"] = 1

        sr_cfg = RankedSRConfig(
            visible_limit=int(self.sr_visible_limit),
            stored_limit=int(self.sr_stored_limit),
            pivot_span=int(self.sr_pivot_span),
            min_swing_atr=float(self.sr_min_swing_atr),
            absorb_atr=float(self.sr_absorb_atr),
            zone_atr_width=float(self.sr_zone_atr_width),
            vol_len=int(self.sr_vol_len),
            trend_len=int(self.sr_trend_len),
            break_atr=float(self.sr_break_atr),
            keep_broken_count=int(self.sr_keep_broken),
        )
        dataframe = compute_ranked_sr_zones(dataframe, sr_cfg)
        dataframe["sr_at_support"] = False
        dataframe["sr_at_resistance"] = False
        for rank in range(1, 5):
            sup_top = dataframe[f"sr_sup_top_{rank}"]
            sup_bot = dataframe[f"sr_sup_bottom_{rank}"]
            res_top = dataframe[f"sr_res_top_{rank}"]
            res_bot = dataframe[f"sr_res_bottom_{rank}"]
            dataframe["sr_at_support"] |= (
                sup_top.notna()
                & (dataframe["high"] >= sup_bot)
                & (dataframe["low"] <= sup_top)
            )
            dataframe["sr_at_resistance"] |= (
                res_top.notna()
                & (dataframe["high"] >= res_bot)
                & (dataframe["low"] <= res_top)
            )
        if not self.use_sr_filter:
            dataframe["sr_at_support"] = True
            dataframe["sr_at_resistance"] = True
        dataframe["sr_at_support"] = dataframe["sr_at_support"].astype(int)
        dataframe["sr_at_resistance"] = dataframe["sr_at_resistance"].astype(int)
        for col in (
            "sr_support_created",
            "sr_resistance_created",
            "sr_support_break",
            "sr_resistance_break",
            "sr_top_rank_support",
            "sr_top_rank_resistance",
        ):
            if col in dataframe.columns:
                dataframe[col] = dataframe[col].astype(int)

        dataframe = self._apply_market_hours(dataframe)
        return dataframe

    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:

        df.loc[
            (
                (df["minima_check"] == 0)
                & (df["volume"] > 0)
                & (df["rsi_long"])
                & (df["mhd_long"])
                & (df["sr_at_support"])
                & (df["market_hours"] == 1)
            ),
            ["enter_long", "enter_tag"],
        ] = (1, "long")

        df.loc[
            (
                (df["DI_catch"] == 1)
                & (df["minima_check"] == 0)
                & (df["minima_check"].shift(5) == 1)
                & (df["volume"] > 0)
                & (df["rsi_long"])
                & (df["mhd_long"])
                & (df["sr_at_support"])
                & (df["market_hours"] == 1)
            ),
            ["enter_long", "enter_tag"],
        ] = (1, "long shift")

        df.loc[
            (
                (df["maxima_check"] == 0)
                & (df["volume"] > 0)
                & (df["rsi_short"])
                & (df["mhd_short"])
                & (df["sr_at_resistance"])
                & (df["market_hours"] == 1)
            ),
            ["enter_short", "enter_tag"],
        ] = (1, "short")

        df.loc[
            (
                (df["DI_catch"] == 0)
                & (df["maxima_check"] == 0)
                & (df["maxima_check"].shift(5) == 1)
                & (df["volume"] > 0)
                & (df["rsi_short"])
                & (df["mhd_short"])
                & (df["sr_at_resistance"])
                & (df["market_hours"] == 1)
            ),
            ["enter_short", "enter_tag"],
        ] = (1, "short shift")
        return df

    def populate_exit_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df.loc[((df["maxima_check"] == 0) & (df["volume"] > 0)), ["exit_long", "exit_tag"]] = (
            1,
            "Maxima Check",
        )
        df.loc[
            (
                (df["DI_catch"] == 0)
                & (df["&s-extrema"] > 0)
                & (df["maxima"].shift(1) == 1)
                & (df["volume"] > 0)
            ),
            ["exit_long", "exit_tag"],
        ] = (1, "Maxima")
        df.loc[((df["maxima_check"] == 0) & (df["volume"] > 0)), ["exit_long", "exit_tag"]] = (
            1,
            "Maxima Full Send",
        )

        df.loc[((df["minima_check"] == 0) & (df["volume"] > 0)), ["exit_short", "exit_tag"]] = (
            1,
            "Minima Check",
        )
        df.loc[
            (
                (df["DI_catch"] == 1)
                & (df["&s-extrema"] < 0)
                & (df["minima"].shift(1) == 1)
                & (df["volume"] > 0)
            ),
            ["exit_short", "exit_tag"],
        ] = (1, "Minima")
        df.loc[((df["minima_check"] == 0) & (df["volume"] > 0)), ["exit_short", "exit_tag"]] = (
            1,
            "Minima Full Send",
        )
        eod = (df["market_hours"] == 0) & (df["market_hours"].shift(1) == 1)
        df.loc[eod, ["exit_long", "exit_tag"]] = (1, "eod")
        df.loc[eod, ["exit_short", "exit_tag"]] = (1, "eod")
        return df
