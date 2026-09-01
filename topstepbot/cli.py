from __future__ import annotations

import argparse
import logging
import sys
import threading
from pathlib import Path

from topstepbot.config import BotConfig
from topstepbot.engine.bot import TradingBot
from topstepbot.exchange.projectx import ProjectXClient
from topstepbot.exchange.symbols import TOPSTEP_SYMBOLS, contract_root, group_contracts_by_root
from topstepbot.rpc.server import ApiServer
from topstepbot.rpc.state import BotState
from topstepbot.strategy.loader import load_strategy_class


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def _run_bot(bot: TradingBot, state: BotState) -> None:
    try:
        bot.run()
    except Exception as exc:
        state.last_error = str(exc)
        state.add_log(f"Bot error: {exc}")
        logger.exception("Bot stopped with error")


def cmd_trade(args: argparse.Namespace) -> int:
    config = BotConfig.load(args.config)
    if args.live:
        config.dry_run = False
    if args.strategy:
        config.strategy = args.strategy

    StrategyClass = load_strategy_class(config.strategy, config.strategy_path)
    state = BotState()
    strategy = StrategyClass(config.__dict__)

    client = ProjectXClient(
        api_base=config.api_base,
        username=config.username,
        api_key=config.api_key,
        live_data=config.live_data,
    )
    bot = TradingBot(config, strategy, client, state=state)

    if config.api_server.enabled:
        bot_thread = threading.Thread(
            target=_run_bot,
            args=(bot, state),
            name="trading-bot",
            daemon=True,
        )
        bot_thread.start()
        ApiServer(config, state).run_blocking()
    else:
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
    root = config.primary_pair
    contract = client.resolve_contract(root)
    bars = client.retrieve_bars(contract["id"], config.timeframe, count=5)
    print(f"  contract: {contract.get('name')} id={contract.get('id')}")
    print(f"  latest bars: {len(bars)}")
    return 0


def cmd_list_symbols(args: argparse.Namespace) -> int:
    config = BotConfig.load(args.config)

    print("Topstep permitted symbols (reference):")
    for symbol in sorted(TOPSTEP_SYMBOLS):
        print(f"  {symbol:<5} {TOPSTEP_SYMBOLS[symbol]}")

    try:
        config.validate()
    except ValueError as exc:
        print(f"\nAPI listing skipped: {exc}")
        print("Set PROJECTX_USERNAME and PROJECTX_API_KEY in .env to list live contracts.")
        return 0

    client = ProjectXClient(
        api_base=config.api_base,
        username=config.username,
        api_key=config.api_key,
        live_data=config.live_data,
    )
    client.login()
    contracts = client.available_contracts()
    grouped = group_contracts_by_root(contracts)

    print(f"\nAvailable on your account ({len(contracts)} contract(s), {len(grouped)} root(s)):")
    for root, items in grouped.items():
        front = items[0]
        label = TOPSTEP_SYMBOLS.get(root, front.get("description", ""))
        print(f"  {root:<5} {label}")
        for item in items[:3]:
            print(f"         {item.get('name')}  id={item.get('id')}")
        if len(items) > 3:
            print(f"         ... +{len(items) - 3} more month(s)")

    if config.pairs:
        print(f"\nConfigured pairlist: {', '.join(config.pairs)}")
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

    symbols = sub.add_parser("list-symbols", help="List Topstep symbols and account contracts")
    symbols.set_defaults(func=cmd_list_symbols)

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
