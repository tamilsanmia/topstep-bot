#!/usr/bin/env python3
"""List TopstepX accounts using the Freqtrade ProjectX client."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from freqtrade.exchange.projectx_client import ProjectXClient
from freqtrade.exchange.topstep_accounts import format_accounts_table


def load_exchange_config(config_path: Path) -> dict:
    data = json.loads(config_path.read_text(encoding="utf-8"))
    exchange = data.get("exchange") or {}
    username = str(exchange.get("username") or "").strip()
    api_key = str(exchange.get("api_key") or exchange.get("apiKey") or "").strip()
    if not username or not api_key:
        raise SystemExit(
            f"Set exchange.username and exchange.api_key in {config_path} before listing accounts."
        )
    return exchange


def main() -> int:
    parser = argparse.ArgumentParser(description="List TopstepX accounts")
    parser.add_argument("-c", "--config", default="config.json", help="Path to Freqtrade config.json")
    parser.add_argument("--all", action="store_true", help="Include inactive accounts")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_file():
        raise SystemExit(f"Config not found: {config_path}")

    exchange = load_exchange_config(config_path)
    client = ProjectXClient(
        api_base=str(exchange.get("api_base") or "https://api.topstepx.com"),
        username=str(exchange.get("username") or ""),
        api_key=str(exchange.get("api_key") or exchange.get("apiKey") or ""),
        live_data=False,
    )
    client.login()
    accounts = client.search_accounts(only_active=not args.all)
    if not accounts:
        print("No accounts found.")
        return 1

    print(format_accounts_table(accounts))
    print()

    preferred = exchange.get("account_id")
    account_filter = exchange.get("account_filter", "any")
    info = client.resolve_account(
        preferred=int(preferred) if preferred else None,
        account_filter=account_filter,
    )
    print("Suggested config for selected account:")
    print(
        f'  "account_id": {info.account_id},\n'
        f'  "account_filter": "{info.kind.value}",\n'
        f'  "live_data": "auto",'
    )
    print()
    print(
        f"Plan limits ({info.rules.label}): "
        f"max {info.rules.max_mini_contracts} mini / {info.rules.max_micro_contracts} micro, "
        f"max loss ${info.rules.max_loss_limit:,.0f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
