"""Shared helpers for Topstep / ProjectX strategies running under Freqtrade."""

from __future__ import annotations

from datetime import datetime


class TopstepMixin:
    """
    TopstepX applies account leverage on the exchange side.
    Freqtrade must not scale size or P&L by leverage — orders are plain lot counts.
    """

    def leverage(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> float:
        return 1.0
