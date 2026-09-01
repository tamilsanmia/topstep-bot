from __future__ import annotations

import logging
import time
from typing import Any

import pandas as pd

from topstepbot.config import BotConfig
from topstepbot.data.history import bars_to_dataframe
from topstepbot.exchange.projectx import ORDER_MARKET, SIDE_BUY, SIDE_SELL, ProjectXClient
from topstepbot.rpc.state import BotRunState, BotState, TradeRecord
from topstepbot.strategy.interface import IStrategy

logger = logging.getLogger(__name__)


class TradingBot:
    def __init__(
        self,
        config: BotConfig,
        strategy: IStrategy,
        client: ProjectXClient,
        state: BotState | None = None,
    ) -> None:
        self.config = config
        self.strategy = strategy
        self.client = client
        self.state = state or BotState()
        self.state.bind_bot(self)
        self.state.bot_name = config.bot_name
        self.state.dry_run = config.dry_run
        self.state.strategy = config.strategy
        self.state.primary_pair = config.primary_pair
        self.state.pairs = config.pairs
        self.state.timeframe = config.timeframe
        self.state.run_state = BotRunState(config.initial_state)
        self.account_id: int | None = None
        self.contract: dict[str, Any] | None = None
        self._running = False
        self._open_trade: TradeRecord | None = None

    def setup(self) -> None:
        self.config.validate()
        self.client.login()
        self.account_id = self.client.resolve_account_id(self.config.account_id)
        self.contract = self.client.resolve_contract(self.config.primary_pair)
        self.state.account_id = self.account_id
        self.state.contract_name = str(self.contract.get("name", ""))
        self.state.add_log(
            f"Bot ready | account={self.account_id} pair={self.config.primary_pair} "
            f"contract={self.contract.get('name')} dry_run={self.config.dry_run}"
        )
        logger.info(
            "Bot ready | account=%s pair=%s contract=%s dry_run=%s",
            self.account_id,
            self.config.primary_pair,
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
        if not self.state.should_process():
            return

        assert self.account_id is not None and self.contract is not None
        try:
            df = self.fetch_dataframe()
            metadata = {
                "pair": self.config.primary_pair,
                "pairs": self.config.pairs,
                "contract_id": self.contract["id"],
                "timeframe": self.config.timeframe,
            }
            analyzed = self.strategy.analyze(df, metadata)
            signal = self.strategy.latest_signal(analyzed)
            qty = self.current_position_qty()
            close = float(analyzed.iloc[-1]["close"]) if not analyzed.empty else 0.0

            self.state.update_snapshot(
                position_qty=qty,
                last_close=close,
                signal=signal,
                contract_name=str(self.contract.get("name", "")),
            )
            self.state.last_error = ""

            logger.info(
                "Signal | close=%.2f pos=%s enter_long=%s enter_short=%s exit_long=%s exit_short=%s",
                close,
                qty,
                signal["enter_long"],
                signal["enter_short"],
                signal["exit_long"],
                signal["exit_short"],
            )

            if qty > 0 and signal["exit_long"]:
                if self.strategy.confirm_trade_exit("long", analyzed, metadata):
                    self._close_position("long", qty, close)
                    return
            if qty < 0 and signal["exit_short"]:
                if self.strategy.confirm_trade_exit("short", analyzed, metadata):
                    self._close_position("short", qty, close)
                    return

            if self.config.max_open_trades <= 0 or self.state.run_state == BotRunState.STOPBUY:
                return

            if qty == 0 and signal["enter_long"] and self.strategy.confirm_trade_entry("long", analyzed, metadata):
                self._open_position(SIDE_BUY, "long", close)
            elif qty == 0 and signal["enter_short"] and self.strategy.confirm_trade_entry("short", analyzed, metadata):
                self._open_position(SIDE_SELL, "short", close)
        except Exception as exc:
            self.state.last_error = str(exc)
            raise

    def _open_position(self, side: int, label: str, rate: float | None = None) -> None:
        assert self.account_id is not None and self.contract is not None
        size = self.config.stake_amount
        open_rate = rate if rate is not None else self.state.last_close
        if self.config.dry_run:
            msg = f"[DRY RUN] Would OPEN {label} size={size}"
            logger.info(msg)
            self.state.add_log(msg)
        else:
            result = self.client.place_order(
                account_id=self.account_id,
                contract_id=self.contract["id"],
                side=side,
                size=size,
                order_type=ORDER_MARKET,
            )
            logger.info("Opened %s: %s", label, result)
            self.state.add_log(f"Opened {label} size={size}")

        self._open_trade = self.state.open_trade(
            pair=self.config.primary_pair,
            is_short=label == "short",
            amount=float(size),
            rate=open_rate,
            stake=float(size),
        )

    def _close_position(self, label: str, qty: int, rate: float | None = None) -> None:
        assert self.account_id is not None and self.contract is not None
        side = SIDE_SELL if qty > 0 else SIDE_BUY
        size = abs(qty)
        close_rate = rate if rate is not None else self.state.last_close
        if self.config.dry_run:
            msg = f"[DRY RUN] Would CLOSE {label} size={size}"
            logger.info(msg)
            self.state.add_log(msg)
        else:
            result = self.client.place_order(
                account_id=self.account_id,
                contract_id=self.contract["id"],
                side=side,
                size=size,
                order_type=ORDER_MARKET,
            )
            logger.info("Closed %s: %s", label, result)
            self.state.add_log(f"Closed {label} size={size}")

        if self._open_trade and self._open_trade.is_open:
            self.state.close_trade(self._open_trade, rate=close_rate)
            self._open_trade = None

    def run(self) -> None:
        self.setup()
        self._running = True
        logger.info("Starting bot loop (throttle=%ss)", self.config.process_throttle_secs)
        self.state.add_log(f"Starting bot loop (throttle={self.config.process_throttle_secs}s)")
        try:
            while self._running:
                if self.state.run_state == BotRunState.STOPPED:
                    break
                try:
                    self.process_once()
                except Exception:
                    logger.exception("Error in bot iteration")
                time.sleep(self.config.process_throttle_secs)
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
            self.state.add_log("Bot stopped by user")

    def stop(self) -> None:
        self._running = False
        self.state.run_state = BotRunState.STOPPED
