"""Topstep account types, rule profiles, and account selection helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

AccountFilter = Literal["combine", "express_funded", "live_funded", "any"]
LiveDataSetting = bool | Literal["auto"]


class TopstepAccountKind(str, Enum):
    COMBINE = "combine"
    EXPRESS_FUNDED = "express_funded"
    LIVE_FUNDED = "live_funded"
    UNKNOWN = "unknown"


# Micro contracts (Topstep micro / e-mini micro roots)
MICRO_ROOTS = frozenset(
    {
        "MNQ",
        "MES",
        "M2K",
        "MYM",
        "MCL",
        "MGC",
        "MNG",
        "MBT",
        "MET",
        "M6E",
        "M6B",
        "M6A",
        "M6J",
    }
)

# Mini / standard roots count 10x toward micro limit on Topstep
MINI_ROOTS = frozenset(
    {
        "NQ",
        "ES",
        "RTY",
        "YM",
        "CL",
        "GC",
        "NG",
        "SI",
        "6E",
        "6B",
        "6A",
        "6J",
        "BTC",
        "ETH",
    }
)

MINI_TO_MICRO_RATIO = 10


@dataclass(frozen=True)
class TopstepRuleProfile:
    """Topstep plan limits (from topstep.com plan features)."""

    buying_power: int
    max_mini_contracts: int
    max_micro_contracts: int
    max_loss_limit: float
    daily_loss_limit: float | None
    profit_target: float | None
    consistency_pct: float | None
    label: str

    def max_lots_for_root(self, root: str) -> int:
        root = root.upper()
        if root in MICRO_ROOTS or root.startswith("M"):
            return self.max_micro_contracts
        return self.max_mini_contracts

    def weighted_contracts(self, root: str, lots: int) -> int:
        root = root.upper()
        if root in MICRO_ROOTS or (root.startswith("M") and root not in MINI_ROOTS):
            return lots
        if root in MINI_ROOTS:
            return lots * MINI_TO_MICRO_RATIO
        # Unknown symbol — treat as mini to stay conservative
        return lots * MINI_TO_MICRO_RATIO


RULE_PROFILES: dict[int, TopstepRuleProfile] = {
    50_000: TopstepRuleProfile(
        buying_power=50_000,
        max_mini_contracts=5,
        max_micro_contracts=50,
        max_loss_limit=2_000,
        daily_loss_limit=1_000,
        profit_target=3_000,
        consistency_pct=50.0,
        label="$50K",
    ),
    100_000: TopstepRuleProfile(
        buying_power=100_000,
        max_mini_contracts=10,
        max_micro_contracts=100,
        max_loss_limit=3_000,
        daily_loss_limit=2_000,
        profit_target=6_000,
        consistency_pct=50.0,
        label="$100K",
    ),
    150_000: TopstepRuleProfile(
        buying_power=150_000,
        max_mini_contracts=15,
        max_micro_contracts=150,
        max_loss_limit=4_500,
        daily_loss_limit=3_000,
        profit_target=9_000,
        consistency_pct=50.0,
        label="$150K",
    ),
}


@dataclass
class TopstepAccountInfo:
    account_id: int
    name: str
    balance: float
    can_trade: bool
    simulated: bool
    kind: TopstepAccountKind
    buying_power: int
    rules: TopstepRuleProfile
    live_data: bool
    raw: dict[str, Any]

    @property
    def display_type(self) -> str:
        phase = {
            TopstepAccountKind.COMBINE: "Trading Combine (evaluation)",
            TopstepAccountKind.EXPRESS_FUNDED: "Express Funded (sim)",
            TopstepAccountKind.LIVE_FUNDED: "Live Funded",
            TopstepAccountKind.UNKNOWN: "Unknown",
        }[self.kind]
        return f"{self.rules.label} {phase}"


def _parse_buying_power(name: str) -> int | None:
    text = name.upper()
    match = re.search(r"\b(50|100|150)K", text)
    if match:
        return int(match.group(1)) * 1000
    return None


def _infer_kind(name: str, simulated: bool) -> TopstepAccountKind:
    text = name.upper()
    if not simulated:
        return TopstepAccountKind.LIVE_FUNDED
    if "TC" in text or "COMBINE" in text or re.search(r"\d+KTC", text):
        return TopstepAccountKind.COMBINE
    if any(token in text for token in ("XFA", "EXPRESS", "FUNDED", "PRAC")):
        return TopstepAccountKind.EXPRESS_FUNDED
    # Simulated non-combine names are usually express funded
    if simulated:
        return TopstepAccountKind.EXPRESS_FUNDED
    return TopstepAccountKind.UNKNOWN


def classify_account(raw: dict[str, Any]) -> TopstepAccountInfo:
    account_id = int(raw.get("id") or raw.get("accountId"))
    name = str(raw.get("name") or raw.get("accountName") or "?")
    balance = float(raw.get("balance") or raw.get("accountBalance") or 0)
    can_trade = bool(raw.get("canTrade", raw.get("can_trade", True)))
    simulated = bool(raw.get("simulated", raw.get("isSimulated", True)))

    buying_power = _parse_buying_power(name)
    if buying_power is None:
        # Infer from round balance near plan size
        for size in (150_000, 100_000, 50_000):
            if balance >= size * 0.85:
                buying_power = size
                break
        if buying_power is None:
            buying_power = 50_000

    rules = RULE_PROFILES.get(buying_power, RULE_PROFILES[50_000])
    kind = _infer_kind(name, simulated)
    live_data = not simulated

    return TopstepAccountInfo(
        account_id=account_id,
        name=name,
        balance=balance,
        can_trade=can_trade,
        simulated=simulated,
        kind=kind,
        buying_power=buying_power,
        rules=rules,
        live_data=live_data,
        raw=raw,
    )


def resolve_live_data(setting: LiveDataSetting, account: TopstepAccountInfo) -> bool:
    if setting == "auto" or setting is None:
        return account.live_data
    if isinstance(setting, str):
        return setting.lower() in ("1", "true", "yes")
    return bool(setting)


def _matches_filter(account: TopstepAccountInfo, account_filter: AccountFilter | None) -> bool:
    if not account_filter or account_filter == "any":
        return True
    if account_filter == "combine":
        return account.kind == TopstepAccountKind.COMBINE
    if account_filter == "express_funded":
        return account.kind == TopstepAccountKind.EXPRESS_FUNDED
    if account_filter == "live_funded":
        return account.kind == TopstepAccountKind.LIVE_FUNDED
    return True


def select_account(
    accounts: list[dict[str, Any]],
    *,
    preferred_id: int | None = None,
    account_filter: AccountFilter | None = "any",
) -> TopstepAccountInfo:
    classified = [classify_account(a) for a in accounts]
    if not classified:
        raise ValueError("No Topstep accounts returned from API")

    if preferred_id is not None:
        for acct in classified:
            if acct.account_id == preferred_id:
                return acct
        raise ValueError(f"account_id {preferred_id} not found in active Topstep accounts")

    filtered = [a for a in classified if a.can_trade and _matches_filter(a, account_filter)]
    if not filtered:
        filtered = [a for a in classified if _matches_filter(a, account_filter)]
    if not filtered:
        filtered = classified

    # Prefer combine first (evaluation), then express funded, then live
    priority = {
        TopstepAccountKind.COMBINE: 0,
        TopstepAccountKind.EXPRESS_FUNDED: 1,
        TopstepAccountKind.LIVE_FUNDED: 2,
        TopstepAccountKind.UNKNOWN: 3,
    }
    filtered.sort(key=lambda a: (priority.get(a.kind, 9), -a.balance))
    return filtered[0]


@dataclass
class TopstepRulesConfig:
    enabled: bool = True
    enforce_max_contracts: bool = True
    block_when_cannot_trade: bool = True
    block_on_daily_loss: bool = True
    block_on_max_loss: bool = True
    warn_on_consistency: bool = True
    block_on_consistency: bool = False
    auto_pause_on_daily_loss: bool = True
    auto_stop_on_max_loss: bool = True
    loss_ratio: float = 0.8

    @classmethod
    def from_exchange_config(cls, exchange: dict[str, Any]) -> "TopstepRulesConfig":
        raw = exchange.get("topstep_rules") or {}
        if not isinstance(raw, dict):
            raw = {}
        enabled = exchange.get("topstep_rules_enabled", raw.get("enabled", True))
        loss_ratio = float(raw.get("loss_ratio", exchange.get("loss_ratio", 0.8)))
        loss_ratio = max(0.01, min(1.0, loss_ratio))
        return cls(
            enabled=bool(enabled),
            enforce_max_contracts=bool(raw.get("enforce_max_contracts", True)),
            block_when_cannot_trade=bool(raw.get("block_when_cannot_trade", True)),
            block_on_daily_loss=bool(raw.get("block_on_daily_loss", True)),
            block_on_max_loss=bool(raw.get("block_on_max_loss", True)),
            warn_on_consistency=bool(raw.get("warn_on_consistency", True)),
            block_on_consistency=bool(raw.get("block_on_consistency", False)),
            auto_pause_on_daily_loss=bool(raw.get("auto_pause_on_daily_loss", True)),
            auto_stop_on_max_loss=bool(raw.get("auto_stop_on_max_loss", True)),
            loss_ratio=loss_ratio,
        )


def check_order_allowed(
    *,
    account: TopstepAccountInfo,
    rules_cfg: TopstepRulesConfig,
    pair_root: str,
    order_lots: int,
    open_positions: list[dict[str, Any]],
    reduce_only: bool = False,
) -> str | None:
    """Return error message if order should be blocked, else None."""
    if not rules_cfg.enabled:
        return None

    if rules_cfg.block_when_cannot_trade and not account.can_trade:
        return f"Account {account.account_id} canTrade=false — trading disabled by Topstep"

    if reduce_only:
        return None

    if not rules_cfg.enforce_max_contracts:
        return None

    used = 0
    for pos in open_positions:
        qty = abs(int(pos.get("size") or pos.get("quantity") or 0))
        if qty <= 0:
            continue
        root = str(pos.get("symbol") or pos.get("contractName") or "")
        if not root:
            contract = pos.get("contract") or {}
            root = str(contract.get("name") or contract.get("symbolId") or "")
        root = root.split(".")[0].upper() if root else pair_root
        if "." in root:
            root = root.split(".")[-1][:4]
        used += account.rules.weighted_contracts(root, qty)

    new_weight = account.rules.weighted_contracts(pair_root, order_lots)
    limit = account.rules.max_micro_contracts
    if used + new_weight > limit:
        return (
            f"Topstep max contracts exceeded: {used + new_weight} micro-equiv > "
            f"{limit} limit for {account.rules.label} account "
            f"({account.rules.max_mini_contracts} mini / {account.rules.max_micro_contracts} micro)"
        )

    per_symbol_max = account.rules.max_lots_for_root(pair_root)
    if order_lots > per_symbol_max:
        return f"Order size {order_lots} exceeds per-symbol max {per_symbol_max} for {pair_root}"

    return None


def format_accounts_table(accounts: list[dict[str, Any]]) -> str:
    lines = [
        f"{'ID':<12} {'Type':<32} {'Balance':>12} {'Trade':>6} {'Live data':>10}  Name",
        "-" * 90,
    ]
    for raw in accounts:
        info = classify_account(raw)
        lines.append(
            f"{info.account_id:<12} {info.display_type:<32} {info.balance:>12,.2f} "
            f"{'yes' if info.can_trade else 'no':>6} {'true' if info.live_data else 'false':>10}  "
            f"{info.name}"
        )
    return "\n".join(lines)
