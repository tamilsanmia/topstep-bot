from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from topstepbot.exchange.symbols import resolve_pairlist


@dataclass
class ApiServerConfig:
    enabled: bool = False
    listen_ip_address: str = "127.0.0.1"
    listen_port: int = 8080
    verbosity: str = "error"
    enable_openapi: bool = False
    jwt_secret_key: str = "change-me-in-config"
    ws_token: str = "change-me-in-config"
    CORS_origins: list[str] = field(default_factory=list)
    username: str = "admin"
    password: str = "admin"

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ApiServerConfig":
        if not data:
            return cls()
        return cls(
            enabled=bool(data.get("enabled", False)),
            listen_ip_address=str(data.get("listen_ip_address", "127.0.0.1")),
            listen_port=int(data.get("listen_port", 8080)),
            verbosity=str(data.get("verbosity", "error")),
            enable_openapi=bool(data.get("enable_openapi", False)),
            jwt_secret_key=str(data.get("jwt_secret_key", "change-me-in-config")),
            ws_token=str(data.get("ws_token", "change-me-in-config")),
            CORS_origins=list(data.get("CORS_origins", [])),
            username=str(data.get("username", "admin")),
            password=str(data.get("password", "admin")),
        )


@dataclass
class BotConfig:
    dry_run: bool = True
    stake_amount: int = 1
    max_open_trades: int = 1
    timeframe: str = "5m"
    contract_root: str = "MNQ"
    pair_whitelist: list[str] = field(default_factory=lambda: ["MNQ"])
    pairlists: list[dict[str, Any]] = field(default_factory=lambda: [{"method": "StaticPairList"}])
    strategy: str = "SampleStrategy"
    strategy_path: str = "user_data/strategies"
    process_throttle_secs: float = 5.0
    startup_candle_count: int = 200
    order_type: str = "market"
    stoploss_ticks: int | None = 20
    takeprofit_ticks: int | None = 40
    account_id: int | None = None
    api_base: str = "https://api.topstepx.com"
    market_hub: str = "https://rtc.topstepx.com/hubs/market"
    username: str = ""
    api_key: str = ""
    live_data: bool = False
    bot_name: str = "topstepbot"
    initial_state: str = "running"
    force_entry_enable: bool = False
    api_server: ApiServerConfig = field(default_factory=ApiServerConfig)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def pairs(self) -> list[str]:
        """Active trading pairs (Freqtrade-style), resolved from pairlists."""
        return resolve_pairlist(self.pair_whitelist, self.pairlists)

    @property
    def primary_pair(self) -> str:
        """Primary pair — first entry in the resolved pairlist."""
        pairs = self.pairs
        return pairs[0] if pairs else self.contract_root.upper()

    @classmethod
    def load(cls, config_path: str | Path = "config.json") -> "BotConfig":
        load_dotenv()
        path = Path(config_path)
        data: dict[str, Any] = {}
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))

        contract_root = str(data.get("contract_root", "MNQ")).upper()
        raw_whitelist = data.get("pair_whitelist") or data.get("pairs")
        if raw_whitelist:
            pair_whitelist = [str(p).upper() for p in raw_whitelist]
        else:
            pair_whitelist = [contract_root]

        raw_pairlists = data.get("pairlists")
        if raw_pairlists is None:
            pairlists = [{"method": "StaticPairList"}]
        else:
            pairlists = list(raw_pairlists)

        internals = data.get("internals") or {}
        throttle = internals.get("process_throttle_secs", data.get("process_throttle_secs", 5))

        account_id = data.get("account_id") or os.getenv("PROJECTX_ACCOUNT_ID")
        known_fields = set(cls.__dataclass_fields__) - {"extra", "api_server"}
        return cls(
            dry_run=bool(data.get("dry_run", True)),
            stake_amount=int(data.get("stake_amount", 1)),
            max_open_trades=int(data.get("max_open_trades", 1)),
            timeframe=str(data.get("timeframe", "5m")),
            contract_root=contract_root,
            pair_whitelist=pair_whitelist,
            pairlists=pairlists,
            strategy=str(data.get("strategy", "SampleStrategy")),
            strategy_path=str(data.get("strategy_path", "user_data/strategies")),
            process_throttle_secs=float(throttle),
            startup_candle_count=int(data.get("startup_candle_count", 200)),
            order_type=str(data.get("order_type", "market")),
            stoploss_ticks=data.get("stoploss_ticks"),
            takeprofit_ticks=data.get("takeprofit_ticks"),
            account_id=int(account_id) if account_id else None,
            api_base=os.getenv("PROJECTX_API_BASE", data.get("api_base", "https://api.topstepx.com")),
            market_hub=os.getenv("PROJECTX_MARKET_HUB", data.get("market_hub", "https://rtc.topstepx.com/hubs/market")),
            username=os.getenv("PROJECTX_USERNAME", ""),
            api_key=os.getenv("PROJECTX_API_KEY", ""),
            live_data=str(os.getenv("PROJECTX_LIVE_DATA", data.get("live_data", False))).lower() in ("1", "true", "yes"),
            bot_name=str(data.get("bot_name", "topstepbot")),
            initial_state=str(data.get("initial_state", "running")),
            force_entry_enable=bool(data.get("force_entry_enable", False)),
            api_server=ApiServerConfig.from_dict(data.get("api_server")),
            extra={k: v for k, v in data.items() if k not in known_fields and k not in ("internals", "api_server")},
        )

    def validate(self) -> None:
        if not self.username or not self.api_key:
            raise ValueError("Set PROJECTX_USERNAME and PROJECTX_API_KEY in .env")
        if not self.pairs:
            raise ValueError("pair_whitelist / pairlists must define at least one symbol")
