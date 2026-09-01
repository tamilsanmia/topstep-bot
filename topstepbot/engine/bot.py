from __future__ import annotations

import logging
import time
from typing import Any

import pandas as pd

from topstepbot.config import BotConfig
from topstepbot.data.history import bars_to_dataframe
from topstepbot.exchange.projectx import ORDER_MARKET, SIDE_BUY, SIDE_SELL, ProjectXClient
from topstepbot.strategy.interface import IStrategy

logger = logging.getLogger(__name__)


class TradingBot:
    def __init__(self, config: BotConfig, strategy: IStrategy, client: ProjectXClient) -> None:
        self.config = config
        self.strategy = strategy
        self.client = client
        self.account_id: int | None = None
        self.contract: dict[str, Any] | None = None
        self._running = False

    def setup(self) -> None:
        self.config.validate()
        self.client.login()
        self.account_id = self.client.resolve_account_id(self.config.account_id)
        self.contract = self.client.resolve_contract(self.config.contract_root)
        logger.info(
            "Bot ready | account=%s contract=%s dry_run=%s",
            self.account_id,
            self.contract.get("name"),
            self.config.dry_run,
        )

    def fetch_dataframe(self) -> pd.DataFrame:
        assert self.contract is not None
        count = max(self.config.startup_candle_count, self.strategy.startup_candle_count)
        bars = self.client.retrieve_bars(self.contract["id"], self.config.timeframe, count=count)
        return bars_to_dataframe(bars)

    def current_position_qty(self) -> int:
        assert self.account_id is not None and self.contract is not None
        positions = self.client.search_positions(self.account_id)
        for pos in positions:
            pid = pos.get("contractId") or pos.get("contract", {}).get("id")
            if str(pid) != str(self.contract["id"]):
                continue
            return int(pos.get("size") or pos.get("quantity") or 0)
        return 0

    def process_once(self) -> None:
        assert self.account_id is not None and self.contract is not None
        df = self.fetch_dataframe()
        metadata = {
            "pair": self.config.contract_root,
            "contract_id": self.contract["id"],
            "timeframe": self.config.timeframe,
        }
        analyzed = self.strategy.analyze(df, metadata)
        signal = self.strategy.latest_signal(analyzed)
        qty = self.current_position_qty()
        close = float(analyzed.iloc[-1]["close"]) if not analyzed.empty else 0.0

        logger.info(
            "Signal | close=%.2f pos=%s enter_long=%s enter_short=%s exit_long=%s exit_short=%s",
            close,
            qty,
            signal["enter_long"],
            signal["enter_short"],
            signal["exit_long"],
            signal["exit_short"],
        )

        # Exit logic first
        if qty > 0 and signal["exit_long"]:
            if self.strategy.confirm_trade_exit("long", analyzed, metadata):
                self._close_position("long", qty)
                return
        if qty < 0 and signal["exit_short"]:
            if self.strategy.confirm_trade_exit("short", analyzed, metadata):
                self._close_position("short", qty)
                return

        if self.config.max_open_trades <= 0:
            return

        # Entry logic
        if qty == 0 and signal["enter_long"] and self.strategy.confirm_trade_entry("long", analyzed, metadata):
            self._open_position(SIDE_BUY, "long")
        elif qty == 0 and signal["enter_short"] and self.strategy.confirm_trade_entry("short", analyzed, metadata):
            self._open_position(SIDE_SELL, "short")

    def _open_position(self, side: int, label: str) -> None:
        assert self.account_id is not None and self.contract is not None
        size = self.config.stake_amount
        if self.config.dry_run:
            logger.info("[DRY RUN] Would OPEN %s size=%s", label, size)
            return
        result = self.client.place_order(
            account_id=self.account_id,
            contract_id=self.contract["id"],
            side=side,
            size=size,
            order_type=ORDER_MARKET,
        )
        logger.info("Opened %s: %s", label, result)

    def _close_position(self, label: str, qty: int) -> None:
        assert self.account_id is not None and self.contract is not None
        side = SIDE_SELL if qty > 0 else SIDE_BUY
        size = abs(qty)
        if self.config.dry_run:
            logger.info("[DRY RUN] Would CLOSE %s size=%s", label, size)
            return
        result = self.client.place_order(
            account_id=self.account_id,
            contract_id=self.contract["id"],
            side=side,
            size=size,
            order_type=ORDER_MARKET,
        )
        logger.info("Closed %s: %s", label, result)

    def run(self) -> None:
        self.setup()
        self._running = True
        logger.info("Starting bot loop (throttle=%ss)", self.config.process_throttle_secs)
        try:
            while self._running:
                try:
                    self.process_once()
                except Exception:
                    logger.exception("Error in bot iteration")
                time.sleep(self.config.process_throttle_secs)
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")

    def stop(self) -> None:
        self._running = False
