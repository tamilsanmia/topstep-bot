from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from topstepbot.engine.bot import TradingBot


class BotRunState(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    PAUSED = "paused"
    STOPBUY = "stopbuy"


@dataclass
class TradeRecord:
    trade_id: int
    pair: str
    is_open: bool = True
    is_short: bool = False
    amount: float = 0.0
    stake_amount: float = 0.0
    open_rate: float = 0.0
    close_rate: float | None = None
    open_date: str = ""
    close_date: str | None = None
    profit_abs: float = 0.0
    profit_ratio: float = 0.0
    exit_reason: str | None = None
    enter_tag: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "pair": self.pair,
            "is_open": self.is_open,
            "is_short": self.is_short,
            "amount": self.amount,
            "stake_amount": self.stake_amount,
            "open_rate": self.open_rate,
            "close_rate": self.close_rate,
            "open_date": self.open_date,
            "close_date": self.close_date,
            "profit_abs": self.profit_abs,
            "profit_ratio": self.profit_ratio,
            "exit_reason": self.exit_reason,
            "enter_tag": self.enter_tag,
        }


@dataclass
class BotState:
    """Shared runtime state between bot loop and API server."""

    bot_name: str = "topstepbot"
    run_state: BotRunState = BotRunState.RUNNING
    dry_run: bool = True
    strategy: str = ""
    primary_pair: str = ""
    pairs: list[str] = field(default_factory=list)
    timeframe: str = "5m"
    account_id: int | None = None
    contract_name: str = ""
    position_qty: int = 0
    last_close: float = 0.0
    last_signal: dict[str, Any] = field(default_factory=dict)
    last_loop: str = ""
    last_error: str = ""
    trades: list[TradeRecord] = field(default_factory=list)
    logs: deque[str] = field(default_factory=lambda: deque(maxlen=200))
    ws_subscribers: list[Any] = field(default_factory=list)
    pending_ws_messages: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=100))
    _trade_counter: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _bot: TradingBot | None = field(default=None, repr=False)

    def bind_bot(self, bot: TradingBot) -> None:
        self._bot = bot

    def next_trade_id(self) -> int:
        with self._lock:
            self._trade_counter += 1
            return self._trade_counter

    def add_log(self, message: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        line = f"{ts} - {message}"
        with self._lock:
            self.logs.appendleft(line)
        self.broadcast({"type": "log", "data": line})

    def open_trade(self, *, pair: str, is_short: bool, amount: float, rate: float, stake: float) -> TradeRecord:
        trade = TradeRecord(
            trade_id=self.next_trade_id(),
            pair=pair,
            is_short=is_short,
            amount=amount,
            stake_amount=stake,
            open_rate=rate,
            open_date=datetime.now(timezone.utc).isoformat(),
        )
        with self._lock:
            self.trades.append(trade)
        self.broadcast({"type": "entry_fill", "data": trade.to_dict()})
        return trade

    def close_trade(self, trade: TradeRecord, *, rate: float, reason: str = "exit_signal") -> None:
        trade.is_open = False
        trade.close_rate = rate
        trade.close_date = datetime.now(timezone.utc).isoformat()
        trade.exit_reason = reason
        if trade.is_short:
            trade.profit_abs = (trade.open_rate - rate) * trade.amount
        else:
            trade.profit_abs = (rate - trade.open_rate) * trade.amount
        if trade.open_rate:
            trade.profit_ratio = trade.profit_abs / trade.open_rate
        self.broadcast({"type": "exit_fill", "data": trade.to_dict()})

    def update_snapshot(
        self,
        *,
        position_qty: int,
        last_close: float,
        signal: dict[str, Any],
        contract_name: str = "",
    ) -> None:
        with self._lock:
            self.position_qty = position_qty
            self.last_close = last_close
            self.last_signal = signal
            self.last_loop = datetime.now(timezone.utc).isoformat()
            if contract_name:
                self.contract_name = contract_name

    def broadcast(self, message: dict[str, Any]) -> None:
        self.pending_ws_messages.append(message)

    @property
    def open_trades(self) -> list[TradeRecord]:
        return [t for t in self.trades if t.is_open]

    @property
    def closed_trades(self) -> list[TradeRecord]:
        return [t for t in self.trades if not t.is_open]

    def total_profit(self) -> dict[str, Any]:
        closed = self.closed_trades
        profit = sum(t.profit_abs for t in closed)
        return {
            "profit_closed_coin": profit,
            "profit_closed_percent": sum(t.profit_ratio for t in closed) * 100 if closed else 0.0,
            "trade_count": len(closed),
            "first_trade_date": closed[0].open_date if closed else "",
            "latest_trade_date": closed[-1].close_date if closed else "",
        }

    def can_enter(self) -> bool:
        return self.run_state in (BotRunState.RUNNING,) and self.run_state != BotRunState.STOPBUY

    def should_process(self) -> bool:
        return self.run_state in (BotRunState.RUNNING, BotRunState.STOPBUY)
