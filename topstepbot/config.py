from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


@dataclass
class BotConfig:
    dry_run: bool = True
    stake_amount: int = 1
    max_open_trades: int = 1
    timeframe: str = "5m"
    contract_root: str = "MNQ"
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
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, config_path: str | Path = "config.json") -> "BotConfig":
        load_dotenv()
        path = Path(config_path)
        data: dict[str, Any] = {}
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))

        account_id = data.get("account_id") or os.getenv("PROJECTX_ACCOUNT_ID")
        return cls(
            dry_run=bool(data.get("dry_run", True)),
            stake_amount=int(data.get("stake_amount", 1)),
            max_open_trades=int(data.get("max_open_trades", 1)),
            timeframe=str(data.get("timeframe", "5m")),
            contract_root=str(data.get("contract_root", "MNQ")),
            strategy=str(data.get("strategy", "SampleStrategy")),
            strategy_path=str(data.get("strategy_path", "user_data/strategies")),
            process_throttle_secs=float(data.get("process_throttle_secs", 5)),
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
            extra={k: v for k, v in data.items() if k not in cls.__dataclass_fields__},
        )

    def validate(self) -> None:
        if not self.username or not self.api_key:
            raise ValueError("Set PROJECTX_USERNAME and PROJECTX_API_KEY in .env")
