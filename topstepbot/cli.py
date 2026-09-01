from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from topstepbot.config import BotConfig
from topstepbot.engine.bot import TradingBot
from topstepbot.exchange.projectx import ProjectXClient
from topstepbot.strategy.loader import load_strategy_class


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_trade(args: argparse.Namespace) -> int:
    config = BotConfig.load(args.config)
    if args.live:
        config.dry_run = False
    if args.strategy:
        config.strategy = args.strategy

    StrategyClass = load_strategy_class(config.strategy, config.strategy_path)
    strategy = StrategyClass(config.__dict__)

    client = ProjectXClient(
        api_base=config.api_base,
        username=config.username,
        api_key=config.api_key,
        live_data=config.live_data,
    )
    bot = TradingBot(config, strategy, client)
    bot.run()
    return 0


def cmd_test_connection(args: argparse.Namespace) -> int:
    config = BotConfig.load(args.config)
    config.validate()
    client = ProjectXClient(
        api_base=config.api_base,
        username=config.username,
        api_key=config.api_key,
        live_data=config.live_data,
    )
    client.login()
    accounts = client.search_accounts()
    contracts = client.available_contracts()
    print(f"OK — {len(accounts)} account(s), {len(contracts)} contract(s)")
    for acct in accounts[:3]:
        print(f"  account: {acct.get('id')} {acct.get('name', acct.get('accountName'))}")
    root = config.contract_root
    contract = client.resolve_contract(root)
    bars = client.retrieve_bars(contract["id"], config.timeframe, count=5)
    print(f"  contract: {contract.get('name')} id={contract.get('id')}")
    print(f"  latest bars: {len(bars)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="topstepbot", description="Topstep / ProjectX Python trading bot")
    parser.add_argument("-c", "--config", default="config.json", help="Path to config.json")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    trade = sub.add_parser("trade", help="Run the strategy loop")
    trade.add_argument("--strategy", help="Strategy class module name (without .py)")
    trade.add_argument("--live", action="store_true", help="Disable dry_run and send real orders")
    trade.set_defaults(func=cmd_trade)

    test = sub.add_parser("test-connection", help="Verify ProjectX credentials and data access")
    test.set_defaults(func=cmd_test_connection)

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
