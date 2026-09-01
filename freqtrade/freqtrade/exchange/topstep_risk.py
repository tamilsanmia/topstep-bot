"""Topstep risk guardrails: daily loss, max loss, consistency tracking."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from freqtrade.exchange.topstep_accounts import TopstepAccountInfo, TopstepAccountKind, TopstepRulesConfig

logger = logging.getLogger(__name__)

# CME futures session rolls at 17:00 US/Central (Topstep daily loss resets at market open).
SESSION_TZ = ZoneInfo("America/Chicago")
SESSION_ROLL_HOUR = 17


@dataclass
class TopstepRiskState:
    account_id: int
    buying_power: float
    peak_balance: float
    session_key: str
    session_start_balance: float
    daily_pnls: dict[str, float] = field(default_factory=dict)
    last_balance: float = 0.0
    last_warning: str = ""

    @classmethod
    def load(cls, path: Path, account_id: int, buying_power: float, balance: float) -> "TopstepRiskState":
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if int(data.get("account_id", 0)) == account_id:
                    return cls(
                        account_id=account_id,
                        buying_power=float(data.get("buying_power", buying_power)),
                        peak_balance=float(data.get("peak_balance", balance)),
                        session_key=str(data.get("session_key", "")),
                        session_start_balance=float(data.get("session_start_balance", balance)),
                        daily_pnls={str(k): float(v) for k, v in (data.get("daily_pnls") or {}).items()},
                        last_balance=float(data.get("last_balance", balance)),
                        last_warning=str(data.get("last_warning", "")),
                    )
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                logger.warning("Could not load Topstep risk state from %s: %s", path, exc)

        session_key = trading_session_key()
        return cls(
            account_id=account_id,
            buying_power=buying_power,
            peak_balance=max(balance, buying_power),
            session_key=session_key,
            session_start_balance=balance,
            daily_pnls={},
            last_balance=balance,
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")


def trading_session_key(when: datetime | None = None) -> str:
    """Return session id (rolls at 17:00 US/Central — CME-style daily reset)."""
    now = when or datetime.now(SESSION_TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=SESSION_TZ)
    else:
        now = now.astimezone(SESSION_TZ)
    session_date = now.date()
    if now.hour >= SESSION_ROLL_HOUR:
        session_date = session_date + timedelta(days=1)
    return session_date.isoformat()


def _consistency_pct(account: TopstepAccountInfo) -> float:
    if account.kind == TopstepAccountKind.EXPRESS_FUNDED:
        return 40.0
    return float(account.rules.consistency_pct or 50.0)


@dataclass
class TopstepRiskSnapshot:
    balance: float
    daily_pnl: float
    total_profit: float
    best_day_profit: float
    consistency_ratio: float | None
    max_loss_floor: float
    drawdown_from_peak: float
    peak_balance: float
    can_enter: bool
    block_reason: str | None
    block_type: str | None
    warning: str | None
    session_key: str = ""
    daily_loss_limit: float | None = None
    max_loss_limit: float | None = None
    consistency_limit_pct: float | None = None
    loss_ratio: float = 0.8
    daily_loss_trigger: float | None = None
    max_loss_trigger: float | None = None
    consistency_trigger_pct: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "balance": self.balance,
            "daily_pnl": self.daily_pnl,
            "total_profit": self.total_profit,
            "best_day_profit": self.best_day_profit,
            "consistency_ratio": self.consistency_ratio,
            "consistency_ratio_pct": (
                round(self.consistency_ratio * 100, 2) if self.consistency_ratio is not None else None
            ),
            "max_loss_floor": self.max_loss_floor,
            "drawdown_from_peak": self.drawdown_from_peak,
            "peak_balance": self.peak_balance,
            "can_enter": self.can_enter,
            "block_reason": self.block_reason,
            "block_type": self.block_type,
            "warning": self.warning,
            "session_key": self.session_key,
            "loss_ratio": self.loss_ratio,
            "limits": {
                "daily_loss": self.daily_loss_limit,
                "daily_loss_trigger": self.daily_loss_trigger,
                "max_loss": self.max_loss_limit,
                "max_loss_trigger": self.max_loss_trigger,
                "consistency_pct": self.consistency_limit_pct,
                "consistency_trigger_pct": self.consistency_trigger_pct,
            },
        }


class TopstepRiskTracker:
    def __init__(
        self,
        *,
        account: TopstepAccountInfo,
        rules_cfg: TopstepRulesConfig,
        state_path: Path,
    ) -> None:
        self.account = account
        self.rules_cfg = rules_cfg
        self.state_path = state_path
        self.state = TopstepRiskState.load(
            state_path,
            account.account_id,
            float(account.buying_power),
            account.balance,
        )

    def refresh(self, balance: float) -> TopstepRiskSnapshot:
        self.account.balance = balance
        session_key = trading_session_key()

        if session_key != self.state.session_key:
            if self.state.session_key:
                prev_pnl = self.state.last_balance - self.state.session_start_balance
                self.state.daily_pnls[self.state.session_key] = prev_pnl
            self.state.session_key = session_key
            self.state.session_start_balance = balance

        self.state.peak_balance = max(self.state.peak_balance, balance)
        self.state.last_balance = balance
        self.state.save(self.state_path)

        return self.evaluate()

    def evaluate(self) -> TopstepRiskSnapshot:
        balance = self.state.last_balance
        rules = self.account.rules
        daily_pnl = balance - self.state.session_start_balance
        total_profit = max(0.0, balance - float(self.account.buying_power))
        best_day = max([v for v in self.state.daily_pnls.values() if v > 0], default=0.0)
        if daily_pnl > 0:
            best_day = max(best_day, daily_pnl)

        consistency_pct = _consistency_pct(self.account)
        consistency_ratio: float | None = None
        if total_profit > 0:
            consistency_ratio = best_day / total_profit

        loss_ratio = self.rules_cfg.loss_ratio
        effective_max_loss = rules.max_loss_limit * loss_ratio
        max_loss_floor = self.state.peak_balance - effective_max_loss
        drawdown = self.state.peak_balance - balance
        effective_daily_loss = (
            rules.daily_loss_limit * loss_ratio if rules.daily_loss_limit else None
        )
        effective_consistency = (consistency_pct / 100.0) * loss_ratio

        block_reason: str | None = None
        block_type: str | None = None
        warning: str | None = None

        if self.rules_cfg.block_on_max_loss and balance <= max_loss_floor:
            block_type = "max_loss"
            block_reason = (
                f"Topstep max loss limit: balance ${balance:,.2f} at/below floor "
                f"${max_loss_floor:,.2f} (peak ${self.state.peak_balance:,.2f} − "
                f"${effective_max_loss:,.0f} trigger, plan ${rules.max_loss_limit:,.0f} × "
                f"{loss_ratio:.2f} loss_ratio)"
            )

        if (
            not block_reason
            and self.rules_cfg.block_on_daily_loss
            and effective_daily_loss
            and daily_pnl <= -effective_daily_loss
        ):
            block_type = "daily_loss"
            block_reason = (
                f"Topstep daily loss limit: session P&L ${daily_pnl:,.2f} reached "
                f"-${effective_daily_loss:,.0f} trigger (plan ${rules.daily_loss_limit:,.0f} × "
                f"{loss_ratio:.2f} loss_ratio)"
            )

        if (
            not block_reason
            and self.rules_cfg.block_on_consistency
            and consistency_ratio is not None
            and consistency_ratio >= effective_consistency
        ):
            block_type = "consistency"
            block_reason = (
                f"Topstep consistency rule: best day ${best_day:,.2f} is "
                f"{consistency_ratio * 100:.1f}% of total profit ${total_profit:,.2f} "
                f"(trigger {effective_consistency * 100:.1f}%, plan {consistency_pct:.0f}% × "
                f"{loss_ratio:.2f} loss_ratio)"
            )

        if self.rules_cfg.warn_on_consistency and consistency_ratio is not None:
            warn_threshold = effective_consistency * 0.85
            if consistency_ratio >= warn_threshold:
                warning = (
                    f"Consistency warning: best day is {consistency_ratio * 100:.1f}% of "
                    f"total profit (trigger {effective_consistency * 100:.1f}%). "
                    f"Best=${best_day:,.2f} Total=${total_profit:,.2f}"
                )

        if self.rules_cfg.block_on_daily_loss and effective_daily_loss:
            remaining = effective_daily_loss + daily_pnl
            if remaining <= effective_daily_loss * 0.15 and daily_pnl < 0:
                loss_warn = (
                    f"Daily loss warning: ${abs(daily_pnl):,.2f} lost today, "
                    f"${remaining:,.2f} buffer before ${effective_daily_loss:,.0f} trigger "
                    f"(loss_ratio {loss_ratio:.2f})"
                )
                warning = loss_warn if not warning else f"{warning}; {loss_warn}"

        if self.rules_cfg.block_on_max_loss:
            buffer = balance - max_loss_floor
            if 0 < buffer <= effective_max_loss * 0.1:
                dd_warn = (
                    f"Max loss warning: ${buffer:,.2f} above trigger floor "
                    f"${max_loss_floor:,.2f} (${drawdown:,.2f} drawn down from peak, "
                    f"loss_ratio {loss_ratio:.2f})"
                )
                warning = dd_warn if not warning else f"{warning}; {dd_warn}"

        if warning and warning != self.state.last_warning:
            logger.warning(warning)
            self.state.last_warning = warning
            self.state.save(self.state_path)

        return TopstepRiskSnapshot(
            balance=balance,
            daily_pnl=daily_pnl,
            total_profit=total_profit,
            best_day_profit=best_day,
            consistency_ratio=consistency_ratio,
            max_loss_floor=max_loss_floor,
            drawdown_from_peak=drawdown,
            peak_balance=self.state.peak_balance,
            can_enter=block_reason is None,
            block_reason=block_reason,
            block_type=block_type,
            warning=warning,
            session_key=self.state.session_key,
            daily_loss_limit=rules.daily_loss_limit,
            max_loss_limit=rules.max_loss_limit,
            consistency_limit_pct=consistency_pct,
            loss_ratio=loss_ratio,
            daily_loss_trigger=effective_daily_loss,
            max_loss_trigger=effective_max_loss,
            consistency_trigger_pct=effective_consistency * 100.0,
        )

    def check_entry(self, balance: float) -> TopstepRiskSnapshot:
        snap = self.refresh(balance)
        return snap


def handle_topstep_risk_violation(
    snap: TopstepRiskSnapshot,
    rules_cfg: TopstepRulesConfig,
) -> str | None:
    """Pause or stop the bot when Topstep limits are breached. Returns action taken."""
    if not snap.block_reason or not snap.block_type:
        return None

    action: str | None = None
    if snap.block_type == "daily_loss" and rules_cfg.auto_pause_on_daily_loss:
        action = pause_trading_bot(snap.block_reason)
    elif snap.block_type == "max_loss" and rules_cfg.auto_stop_on_max_loss:
        action = stop_trading_bot(snap.block_reason)
    elif snap.block_type == "consistency" and rules_cfg.block_on_consistency:
        action = pause_trading_bot(snap.block_reason)

    return action


def pause_trading_bot(reason: str) -> str:
    from freqtrade.enums import State
    from freqtrade.rpc.api_server.webserver import ApiServer

    if not ApiServer._has_rpc or not ApiServer._rpc:
        return "no_rpc"
    ft = ApiServer._rpc._freqtrade
    if ft.state == State.RUNNING:
        ft.state = State.PAUSED
        ApiServer._rpc.send_msg({"type": "warning", "status": f"Topstep auto-pause: {reason}"})
        logger.warning("Topstep auto-pause: %s", reason)
        return "paused"
    return "already_paused"


def stop_trading_bot(reason: str) -> str:
    from freqtrade.enums import State
    from freqtrade.rpc.api_server.webserver import ApiServer

    if not ApiServer._has_rpc or not ApiServer._rpc:
        return "no_rpc"
    ft = ApiServer._rpc._freqtrade
    if ft.state != State.STOPPED:
        ft.state = State.STOPPED
        ApiServer._rpc.send_msg({"type": "warning", "status": f"Topstep auto-stop: {reason}"})
        logger.warning("Topstep auto-stop: %s", reason)
        return "stopped"
    return "already_stopped"
