from __future__ import annotations

import pandas as pd

from freqtrade.strategy import DecimalParameter, IntParameter
from freqtrade.strategy.interface import IStrategy

from indicators import crossed_above, crossed_below, stochastic_momentum_index
from topstep_mixin import TopstepMixin


class ReverseSMI(TopstepMixin, IStrategy):
    """
    Reverse Stochastic Momentum Index (RSMI) strategy.

    Pine source: Reverse Stochastic Momentum Index by The_Caretaker (TradingView).
    Converts the SMI / signal-line indicator into a futures strategy:

    Long  : SMI crosses above the signal line
    Short : SMI crosses below the signal line
    Exit  : opposite crossover (or ROI / stoploss)

    Default parameters match the original Pine script inputs.
    """

    timeframe = "5m"
    startup_candle_count = 200
    can_short = True
    process_only_new_candles = True

    stoploss = -0.001
    minimal_roi: dict[str, float] = {"0": 0.002}
    trailing_stop = False

    use_exit_signal = True
    exit_profit_only = False

    smi_len = IntParameter(5, 30, default=13, space="buy", optimize=False)
    smth1 = IntParameter(5, 50, default=25, space="buy", optimize=False)
    smth2 = IntParameter(1, 10, default=2, space="buy", optimize=False)
    sig_len = IntParameter(3, 30, default=12, space="buy", optimize=False)
    alert_hi = DecimalParameter(20.0, 80.0, default=40.0, decimals=1, space="buy", optimize=False)
    alert_lo = DecimalParameter(-80.0, -20.0, default=-40.0, decimals=1, space="buy", optimize=False)
    use_alert_filter = IntParameter(0, 1, default=0, space="buy", optimize=False)

    _INVIS_LINE = {"line": {"color": "rgba(255,255,255,0)", "width": 0}}

    plot_config = {
        "subplots": {
            "RSMI": {
                # Histogram — 4-tone bars like Pine (hist vs hist[1])
                "hist_ur": {
                    "type": "bar",
                    "color": "#26A69A",
                    "plotly": {"opacity": 0.95},
                },
                "hist_uf": {
                    "type": "bar",
                    "color": "#B2DFDB",
                    "plotly": {"opacity": 0.95},
                },
                "hist_lr": {
                    "type": "bar",
                    "color": "#EF5350",
                    "plotly": {"opacity": 0.95},
                },
                "hist_lf": {
                    "type": "bar",
                    "color": "#FFCDD2",
                    "plotly": {"opacity": 0.95},
                },
                # Mid-line cloud (SMI vs zero)
                "smi_pos": {
                    "fill_to": "midline",
                    "fill_label": "SMI above zero",
                    "fill_color": "rgba(0,255,0,0.20)",
                    "plotly": _INVIS_LINE,
                },
                "midline": {"color": "#909090", "plotly": {"line": {"width": 1}}},
                "smi_neg": {
                    "fill_to": "midline",
                    "fill_label": "SMI below zero",
                    "fill_color": "rgba(255,0,0,0.32)",
                    "plotly": _INVIS_LINE,
                },
                # Ribbon fill between SMI and signal
                "smi_bull": {
                    "fill_to": "sig_bull",
                    "fill_label": "SMI > signal",
                    "fill_color": "rgba(0,255,0,0.31)",
                    "plotly": _INVIS_LINE,
                },
                "sig_bull": {"plotly": _INVIS_LINE},
                "smi_bear": {
                    "fill_to": "sig_bear",
                    "fill_label": "SMI < signal",
                    "fill_color": "rgba(255,0,0,0.32)",
                    "plotly": _INVIS_LINE,
                },
                "sig_bear": {"plotly": _INVIS_LINE},
                # Dual-color SMI + signal lines (on top of fills)
                "smi_rise": {"color": "#00ff00", "plotly": {"line": {"width": 2}}},
                "smi_fall": {"color": "#ff0000", "plotly": {"line": {"width": 2}}},
                "sig_rise": {"color": "#00ff00", "plotly": {"line": {"width": 2}}},
                "sig_fall": {"color": "#ff0000", "plotly": {"line": {"width": 2}}},
                # Scale + alert levels
                "scale_hi": {"color": "#e600ff", "plotly": {"line": {"width": 1}}},
                "scale_lo": {"color": "#00ccff", "plotly": {"line": {"width": 1}}},
                "alert_hi": {
                    "color": "#909090",
                    "plotly": {"line": {"dash": "dash", "width": 1}},
                },
                "alert_lo": {
                    "color": "#909090",
                    "plotly": {"line": {"dash": "dash", "width": 1}},
                },
            }
        }
    }

    @staticmethod
    def _add_plot_columns(df: pd.DataFrame) -> pd.DataFrame:
        """Extra columns for TradingView-style RSMI subplot rendering."""
        hist = df["smi_hist"]
        hist_prev = hist.shift(1)
        df["hist_ur"] = hist.where((hist >= 0) & (hist > hist_prev))
        df["hist_uf"] = hist.where((hist >= 0) & (hist <= hist_prev))
        df["hist_lr"] = hist.where((hist < 0) & (hist > hist_prev))
        df["hist_lf"] = hist.where((hist < 0) & (hist <= hist_prev))

        smi_prev = df["smi"].shift(1)
        df["smi_rise"] = df["smi"].where(df["smi"] > smi_prev)
        df["smi_fall"] = df["smi"].where(df["smi"] <= smi_prev)

        sig_prev = df["smi_signal"].shift(1)
        df["sig_rise"] = df["smi_signal"].where(df["smi_signal"] > sig_prev)
        df["sig_fall"] = df["smi_signal"].where(df["smi_signal"] <= sig_prev)

        bull = df["smi"] > df["smi_signal"]
        df["smi_bull"] = df["smi"].where(bull)
        df["sig_bull"] = df["smi_signal"].where(bull)
        df["smi_bear"] = df["smi"].where(~bull)
        df["sig_bear"] = df["smi_signal"].where(~bull)

        df["midline"] = 0.0
        df["smi_pos"] = df["smi"].where(df["smi"] > 0)
        df["smi_neg"] = df["smi"].where(df["smi"] < 0)
        df["scale_hi"] = 100.0
        df["scale_lo"] = -100.0
        return df

    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        df = dataframe.copy()
        smi, signal, hist = stochastic_momentum_index(
            df,
            length=int(self.smi_len.value),
            smooth1=int(self.smth1.value),
            smooth2=int(self.smth2.value),
            signal_length=int(self.sig_len.value),
            source="close",
        )
        df["smi"] = smi
        df["smi_signal"] = signal
        df["smi_hist"] = hist
        df["alert_hi"] = float(self.alert_hi.value)
        df["alert_lo"] = float(self.alert_lo.value)
        df["smi_cross_up"] = crossed_above(df["smi"], df["smi_signal"])
        df["smi_cross_down"] = crossed_below(df["smi"], df["smi_signal"])
        df = self._add_plot_columns(df)
        return df

    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        df = dataframe.copy()
        df["enter_long"] = False
        df["enter_short"] = False
        df["enter_tag"] = ""

        if int(self.use_alert_filter.value):
            long_cond = df["smi_cross_up"] & (df["smi"].shift(1) <= df["alert_lo"])
            short_cond = df["smi_cross_down"] & (df["smi"].shift(1) >= df["alert_hi"])
        else:
            long_cond = df["smi_cross_up"]
            short_cond = df["smi_cross_down"]

        df.loc[long_cond, "enter_long"] = True
        df.loc[long_cond, "enter_tag"] = "RSMI cross up"

        df.loc[short_cond, "enter_short"] = True
        df.loc[short_cond, "enter_tag"] = "RSMI cross down"

        return df

    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        df = dataframe.copy()
        df["exit_long"] = False
        df["exit_short"] = False
        df["exit_tag"] = ""

        df.loc[df["smi_cross_down"], "exit_long"] = True
        df.loc[df["smi_cross_down"], "exit_tag"] = "RSMI cross down"

        df.loc[df["smi_cross_up"], "exit_short"] = True
        df.loc[df["smi_cross_up"], "exit_tag"] = "RSMI cross up"

        return df
