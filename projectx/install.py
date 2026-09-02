#!/usr/bin/env python3
"""Install ProjectX / Topstep integration onto an official Freqtrade install."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


MARKER = "projectx-integration"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _replace_once(content: str, old: str, new: str, label: str) -> str:
    if old in content:
        return content.replace(old, new, 1)
    if new.split("\n", 1)[0] in content:
        return content
    raise RuntimeError(f"Patch anchor not found for {label}")


def copy_overlay(overlay_root: Path, ft_root: Path) -> None:
    src = overlay_root / "freqtrade"
    dst = ft_root / "freqtrade"
    if not src.is_dir():
        raise SystemExit(f"Overlay not found: {src}")
    for path in src.rglob("*"):
        if path.is_file():
            target = dst / path.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            print(f"Copied {path.relative_to(overlay_root)} -> {target}")


def patch_exchange_init(ft_pkg: Path) -> None:
    path = ft_pkg / "exchange" / "__init__.py"
    content = _read(path)
    needle = "from freqtrade.exchange.projectx import Projectx"
    if needle in content:
        return
    anchor = "from freqtrade.exchange.okx import Myokx, Okx, Okxus"
    if anchor not in content:
        raise RuntimeError("exchange/__init__.py anchor missing")
    _write(path, content.replace(anchor, f"{anchor}\nfrom freqtrade.exchange.projectx import Projectx"))
    print("Patched exchange/__init__.py")


def patch_common(ft_pkg: Path) -> None:
    path = ft_pkg / "exchange" / "common.py"
    content = _read(path)
    if '"projectx"' in content:
        return
    content = _replace_once(
        content,
        'SUPPORTED_EXCHANGES = [\n    "binance",',
        'SUPPORTED_EXCHANGES = [\n    "projectx",\n    "binance",',
        "common.SUPPORTED_EXCHANGES",
    )
    _write(path, content)
    print("Patched exchange/common.py")


def patch_check_exchange(ft_pkg: Path) -> None:
    path = ft_pkg / "exchange" / "check_exchange.py"
    content = _read(path)
    if 'exchange == "projectx"' in content:
        return
    block = (
        '    if exchange == "projectx":\n'
        '        logger.info(\'Exchange "projectx" is supported via Topstep/ProjectX gateway.\')\n'
        "        return True\n\n"
    )
    content = _replace_once(
        content,
        "    if not is_exchange_known_ccxt(exchange):",
        block + "    if not is_exchange_known_ccxt(exchange):",
        "check_exchange.projectx",
    )
    _write(path, content)
    print("Patched exchange/check_exchange.py")


def patch_exchange_utils(ft_pkg: Path) -> None:
    path = ft_pkg / "exchange" / "exchange_utils.py"
    content = _read(path)
    if 'exchange_name.lower() == "projectx"' in content:
        return
    content = _replace_once(
        content,
        "def is_exchange_known_ccxt(exchange_name: str, ccxt_module: CcxtModuleType | None = None) -> bool:\n",
        "def is_exchange_known_ccxt(exchange_name: str, ccxt_module: CcxtModuleType | None = None) -> bool:\n"
        '    if exchange_name.lower() == "projectx":\n'
        "        return True\n",
        "exchange_utils.is_exchange_known_ccxt",
    )
    _write(path, content)
    print("Patched exchange/exchange_utils.py")


def patch_freqtradebot(ft_pkg: Path) -> None:
    path = ft_pkg / "freqtradebot.py"
    content = _read(path)
    if "register_trade_status_callback" in content:
        pass
    else:
        content = _replace_once(
            content,
            "            self.rpc: RPCManager = RPCManager(self)\n\n            self.dataprovider = DataProvider",
            "            self.rpc: RPCManager = RPCManager(self)\n\n"
            '            if hasattr(self.exchange, "register_trade_status_callback"):\n'
            "                self.exchange.register_trade_status_callback(self._push_ws_trade_status)\n"
            '                if hasattr(self.exchange, "sync_open_trade_ids"):\n'
            "                    self.exchange.sync_open_trade_ids(\n"
            "                        {t.pair: t.id for t in Trade.get_open_trades()}\n"
            "                    )\n\n"
            "            self.dataprovider = DataProvider",
            "freqtradebot.register_trade_status_callback",
        )
    if "check_topstep_risk" not in content:
        content = _replace_once(
            content,
            "        self._schedule.run_pending()\n        Trade.commit()\n        self.rpc.process_msg_queue",
            "        self._schedule.run_pending()\n        Trade.commit()\n"
            '        if hasattr(self.exchange, "check_topstep_risk"):\n'
            "            self.exchange.check_topstep_risk(self)\n"
            "        self.rpc.process_msg_queue",
            "freqtradebot.check_topstep_risk",
        )
    if "def _push_ws_trade_status" not in content:
        content = _replace_once(
            content,
            "        self.last_process = datetime.now(UTC)\n\n    def process_stopped(self) -> None:",
            "        self.last_process = datetime.now(UTC)\n\n"
            "    def _push_ws_trade_status(self, rows: list[dict[str, Any]]) -> None:\n"
            '        """Push live open-trade P&L to FreqUI websocket subscribers."""\n'
            "        if not rows:\n"
            "            return\n"
            '        self.rpc.send_msg({"type": RPCMessageType.TRADE_STATUS, "data": rows})\n\n'
            "    def process_stopped(self) -> None:",
            "freqtradebot._push_ws_trade_status",
        )
    _write(path, content)
    print("Patched freqtradebot.py")


def patch_freqtradebot_order_timestamp(ft_pkg: Path) -> None:
    path = ft_pkg / "freqtradebot.py"
    content = _read(path)
    old = """                    order_obj.order_filled_date = dt_from_ts(
                        safe_value_fallback(order, "lastTradeTimestamp", "timestamp")
                    )"""
    new = """                    _filled_ts = safe_value_fallback(order, "lastTradeTimestamp", "timestamp")
                    if _filled_ts is not None:
                        order_obj.order_filled_date = dt_from_ts(_filled_ts)"""
    if old in content:
        _write(path, content.replace(old, new, 1))
        print("Patched freqtradebot.py order timestamp")
        return
    if "_filled_ts is not None" in content:
        return
    raise RuntimeError("Patch anchor not found for freqtradebot order timestamp")


def patch_rpc_trade_status(ft_pkg: Path) -> None:
    path = ft_pkg / "rpc" / "rpc.py"
    content = _read(path)
    if "get_trade_unrealized_profit" in content:
        return
    old_block = """                    try:
                        current_rate: float = self._freqtrade.exchange.get_rate(
                            trade.pair, side="exit", is_short=trade.is_short, refresh=False
                        )
                    except (ExchangeError, PricingError):
                        current_rate = nan
                    if len(trade.select_filled_orders(trade.entry_side)) > 0:
                        current_profit = current_profit_abs = current_profit_fiat = nan
                        if not isnan(current_rate):
                            prof = trade.calculate_profit(current_rate)
                            current_profit = prof.profit_ratio
                            current_profit_abs = prof.profit_abs
                            total_profit_abs = prof.total_profit
                            total_profit_ratio = prof.total_profit_ratio"""
    new_block = """                    try:
                        use_px_pnl = hasattr(self._freqtrade.exchange, "get_trade_unrealized_profit")
                        current_rate: float = self._freqtrade.exchange.get_rate(
                            trade.pair,
                            side="exit",
                            is_short=trade.is_short,
                            refresh=use_px_pnl,
                        )
                    except (ExchangeError, PricingError):
                        current_rate = nan
                    if len(trade.select_filled_orders(trade.entry_side)) > 0:
                        current_profit = current_profit_abs = current_profit_fiat = nan
                        if not isnan(current_rate):
                            px_upnl = None
                            if hasattr(self._freqtrade.exchange, "get_trade_unrealized_profit"):
                                px_upnl = self._freqtrade.exchange.get_trade_unrealized_profit(trade)
                            prof = trade.calculate_profit(current_rate)
                            if px_upnl is not None:
                                current_profit_abs = px_upnl
                                total_profit_abs = px_upnl + (trade.realized_profit or 0.0)
                                if trade.max_stake_amount:
                                    current_profit = px_upnl / trade.max_stake_amount
                                    total_profit_ratio = total_profit_abs / trade.max_stake_amount
                                else:
                                    current_profit = prof.profit_ratio
                                    total_profit_ratio = prof.total_profit_ratio
                            else:
                                current_profit = prof.profit_ratio
                                current_profit_abs = prof.profit_abs
                                total_profit_abs = prof.total_profit
                                total_profit_ratio = prof.total_profit_ratio"""
    content = _replace_once(content, old_block, new_block, "rpc._rpc_trade_status")
    old_stats = """                try:
                    current_rate = self._freqtrade.exchange.get_rate(
                        trade.pair, side="exit", is_short=trade.is_short, refresh=False
                    )
                except (PricingError, ExchangeError):
                    current_rate = nan
                    profit_ratio = nan
                    profit_abs = nan
                else:
                    _profit = trade.calculate_profit(trade.close_rate or current_rate)
                    profit_ratio = _profit.profit_ratio
                    profit_abs = _profit.total_profit"""
    new_stats = """                try:
                    use_px_pnl = hasattr(self._freqtrade.exchange, "get_trade_unrealized_profit")
                    current_rate = self._freqtrade.exchange.get_rate(
                        trade.pair, side="exit", is_short=trade.is_short, refresh=use_px_pnl
                    )
                except (PricingError, ExchangeError):
                    current_rate = nan
                    profit_ratio = nan
                    profit_abs = nan
                else:
                    px_upnl = None
                    if hasattr(self._freqtrade.exchange, "get_trade_unrealized_profit"):
                        px_upnl = self._freqtrade.exchange.get_trade_unrealized_profit(trade)
                    _profit = trade.calculate_profit(trade.close_rate or current_rate)
                    if px_upnl is not None:
                        profit_abs = px_upnl + (trade.realized_profit or 0.0)
                        if trade.max_stake_amount:
                            profit_ratio = px_upnl / trade.max_stake_amount
                        else:
                            profit_ratio = _profit.profit_ratio
                    else:
                        profit_ratio = _profit.profit_ratio
                        profit_abs = _profit.total_profit"""
    content = _replace_once(content, old_stats, new_stats, "rpc.profit_stats")
    _write(path, content)
    print("Patched rpc/rpc.py")


def patch_webserver(ft_pkg: Path) -> None:
    path = ft_pkg / "rpc" / "api_server" / "webserver.py"
    content = _read(path)
    if "publish_threadsafe" not in content:
        content = _replace_once(
            content,
            "        if ApiServer._message_stream:\n            ApiServer._message_stream.publish(msg)",
            "        if ApiServer._message_stream:\n"
            "            stream = ApiServer._message_stream\n"
            "            try:\n"
            "                import asyncio\n\n"
            "                if asyncio.get_running_loop() is stream._loop:\n"
            "                    stream.publish(msg)\n"
            "                else:\n"
            "                    stream.publish_threadsafe(msg)\n"
            "            except RuntimeError:\n"
            "                stream.publish_threadsafe(msg)",
            "webserver.send_msg",
        )
    if "api_topstep" not in content:
        content = _replace_once(
            content,
            "        from freqtrade.rpc.api_server.api_pairlists import router as api_pairlists\n"
            "        from freqtrade.rpc.api_server.api_trading import router as api_trading",
            "        from freqtrade.rpc.api_server.api_pairlists import router as api_pairlists\n"
            "        from freqtrade.rpc.api_server.api_topstep import router as api_topstep\n"
            "        from freqtrade.rpc.api_server.api_trading import router as api_trading",
            "webserver.import_api_topstep",
        )
        content = _replace_once(
            content,
            "        app.include_router(\n            api_v1,\n            prefix=\"/api/v1\",\n"
            "            dependencies=[Depends(http_basic_or_jwt_token)],\n        )\n"
            "        app.include_router(\n            api_trading,",
            "        app.include_router(\n            api_v1,\n            prefix=\"/api/v1\",\n"
            "            dependencies=[Depends(http_basic_or_jwt_token)],\n        )\n"
            "        app.include_router(\n            api_topstep,\n            prefix=\"/api/v1\",\n"
            '            tags=["Topstep"],\n'
            "            dependencies=[Depends(http_basic_or_jwt_token), Depends(is_trading_mode)],\n"
            "        )\n        app.include_router(\n            api_trading,",
            "webserver.include_api_topstep",
        )
    _write(path, content)
    print("Patched rpc/api_server/webserver.py")


def patch_api_ws(ft_pkg: Path) -> None:
    path = ft_pkg / "rpc" / "api_server" / "api_ws.py"
    content = _read(path)
    if "RPCMessageType.TRADE_STATUS" in content:
        return
    content = _replace_once(
        content,
        "        if channel.subscribed_to(message.get(\"type\")):",
        "        msg_type = message.get(\"type\")\n"
        "        if msg_type == RPCMessageType.TRADE_STATUS or channel.subscribed_to(msg_type):",
        "api_ws.channel_broadcaster",
    )
    _write(path, content)
    print("Patched rpc/api_server/api_ws.py")


def patch_message_stream(ft_pkg: Path) -> None:
    path = ft_pkg / "rpc" / "api_server" / "ws" / "message_stream.py"
    content = _read(path)
    if "publish_threadsafe" in content:
        return
    content = _replace_once(
        content,
        "        waiter.set_result((message, time.time(), self._waiter))\n\n    async def __aiter__(self):",
        "        waiter.set_result((message, time.time(), self._waiter))\n\n"
        "    def publish_threadsafe(self, message) -> None:\n"
        '        """Publish from a non-asyncio thread (e.g. exchange websocket workers)."""\n'
        "        try:\n"
        "            running = asyncio.get_running_loop()\n"
        "        except RuntimeError:\n"
        "            running = None\n"
        "        if running is self._loop:\n"
        "            self.publish(message)\n"
        "        else:\n"
        "            self._loop.call_soon_threadsafe(self.publish, message)\n\n"
        "    async def __aiter__(self):",
        "message_stream.publish_threadsafe",
    )
    _write(path, content)
    print("Patched rpc/api_server/ws/message_stream.py")


def patch_rpcmessagetype(ft_pkg: Path) -> None:
    path = ft_pkg / "enums" / "rpcmessagetype.py"
    content = _read(path)
    if "TRADE_STATUS" in content:
        return
    content = _replace_once(
        content,
        "    NEW_CANDLE = \"new_candle\"\n",
        '    NEW_CANDLE = "new_candle"\n    TRADE_STATUS = "trade_status"\n',
        "rpcmessagetype.TRADE_STATUS",
    )
    content = _replace_once(
        content,
        "NO_ECHO_MESSAGES = (RPCMessageType.ANALYZED_DF, RPCMessageType.WHITELIST, RPCMessageType.NEW_CANDLE)",
        "NO_ECHO_MESSAGES = (\n    RPCMessageType.ANALYZED_DF,\n    RPCMessageType.WHITELIST,\n"
        "    RPCMessageType.NEW_CANDLE,\n    RPCMessageType.TRADE_STATUS,\n)",
        "rpcmessagetype.NO_ECHO_MESSAGES",
    )
    _write(path, content)
    print("Patched enums/rpcmessagetype.py")


def patch_rpc_types(ft_pkg: Path) -> None:
    path = ft_pkg / "rpc" / "rpc_types.py"
    content = _read(path)
    if "RPCTradeStatusMsg" in content:
        return
    content = _replace_once(
        content,
        "class RPCNewCandleMsg(RPCSendMsgBase):\n"
        '    """New candle ping message, issued once per new candle/pair"""\n\n'
        "    type: Literal[RPCMessageType.NEW_CANDLE]\n"
        "    data: PairWithTimeframe\n\n\n"
        "RPCOrderMsg = RPCEntryMsg | RPCExitMsg | RPCExitCancelMsg | RPCCancelMsg",
        "class RPCNewCandleMsg(RPCSendMsgBase):\n"
        '    """New candle ping message, issued once per new candle/pair"""\n\n'
        "    type: Literal[RPCMessageType.NEW_CANDLE]\n"
        "    data: PairWithTimeframe\n\n\n"
        "class RPCTradeStatusMsg(RPCSendMsgBase):\n"
        '    """Live open-trade status pushed over websocket (profit/rate updates)."""\n\n'
        "    type: Literal[RPCMessageType.TRADE_STATUS]\n"
        "    data: list[dict[str, Any]]\n\n\n"
        "RPCOrderMsg = RPCEntryMsg | RPCExitMsg | RPCExitCancelMsg | RPCCancelMsg",
        "rpc_types.RPCTradeStatusMsg",
    )
    content = _replace_once(
        content,
        "    | RPCNewCandleMsg\n)",
        "    | RPCNewCandleMsg\n    | RPCTradeStatusMsg\n)",
        "rpc_types.RPCSendMsg",
    )
    _write(path, content)
    print("Patched rpc/rpc_types.py")


def patch_backtesting(ft_pkg: Path) -> None:
    path = ft_pkg / "optimize" / "backtesting.py"
    content = _read(path)

    old_mark = (
        "                self.futures_data[pair] = self.exchange.combine_funding_and_mark(\n"
        "                    funding_rates=funding_rates_dict[pair],\n"
        "                    mark_rates=mark_rates_dict[pair],\n"
        "                    futures_funding_rate=self.config.get(\"futures_funding_rate\", None),\n"
        "                )"
    )
    new_mark = (
        "                self.futures_data[pair] = self.exchange.combine_funding_and_mark(\n"
        "                    funding_rates=funding_rates_dict.get(pair, DataFrame()),\n"
        "                    mark_rates=mark_rates_dict.get(pair, DataFrame()),\n"
        "                    futures_funding_rate=self.config.get(\"futures_funding_rate\", None),\n"
        "                )"
    )
    if old_mark in content:
        content = content.replace(old_mark, new_mark, 1)
    elif "mark_rates_dict.get(pair, DataFrame())" not in content:
        raise RuntimeError("Patch anchor not found for optimize/backtesting.py mark rates")

    old_amount = (
        "            amount_p = (stake_amount / propose_rate) * leverage\n\n"
        "            contract_size = self.exchange.get_contract_size(pair)"
    )
    new_amount = (
        "            contract_size = self.exchange.get_contract_size(pair)\n"
        "            if hasattr(self.exchange, \"stake_to_amount\"):\n"
        "                amount_p = self.exchange.stake_to_amount(\n"
        "                    pair, stake_amount, propose_rate, leverage\n"
        "                )\n"
        "            else:\n"
        "                amount_p = (stake_amount / propose_rate) * leverage"
    )
    if old_amount in content:
        content = content.replace(old_amount, new_amount, 1)
    elif "stake_to_amount" not in content:
        raise RuntimeError("Patch anchor not found for optimize/backtesting.py stake amount")

    old_stake = "            stake_amount = amount * propose_rate / leverage"
    new_stake = (
        "            if hasattr(self.exchange, \"stake_from_amount\"):\n"
        "                stake_amount = self.exchange.stake_from_amount(\n"
        "                    pair, amount, propose_rate, leverage\n"
        "                )\n"
        "            else:\n"
        "                stake_amount = amount * propose_rate / leverage"
    )
    if old_stake in content:
        content = content.replace(old_stake, new_stake, 1)
    elif "stake_from_amount" not in content:
        raise RuntimeError("Patch anchor not found for optimize/backtesting.py stake backcalc")

    _write(path, content)
    print("Patched optimize/backtesting.py")


def patch_webhook(ft_pkg: Path) -> None:
    path = ft_pkg / "rpc" / "webhook.py"
    content = _read(path)
    if "RPCMessageType.TRADE_STATUS" in content:
        return
    content = _replace_once(
        content,
        "            RPCMessageType.NEW_CANDLE,\n            RPCMessageType.STRATEGY_MSG,",
        "            RPCMessageType.NEW_CANDLE,\n            RPCMessageType.TRADE_STATUS,\n"
        "            RPCMessageType.STRATEGY_MSG,",
        "webhook.TRADE_STATUS",
    )
    _write(path, content)
    print("Patched rpc/webhook.py")


def install(ft_root: Path, overlay_root: Path) -> None:
    ft_pkg = ft_root / "freqtrade"
    if not ft_pkg.is_dir():
        raise SystemExit(f"Freqtrade package not found under {ft_root}")
    copy_overlay(overlay_root, ft_root)
    patch_exchange_init(ft_pkg)
    patch_common(ft_pkg)
    patch_check_exchange(ft_pkg)
    patch_exchange_utils(ft_pkg)
    patch_freqtradebot(ft_pkg)
    patch_freqtradebot_order_timestamp(ft_pkg)
    patch_rpc_trade_status(ft_pkg)
    patch_webserver(ft_pkg)
    patch_api_ws(ft_pkg)
    patch_message_stream(ft_pkg)
    patch_rpcmessagetype(ft_pkg)
    patch_rpc_types(ft_pkg)
    patch_webhook(ft_pkg)
    patch_backtesting(ft_pkg)
    print(f"{MARKER}: install complete")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ft-root",
        default=None,
        help="Freqtrade repo root (parent of freqtrade/ package). Default: detect from import.",
    )
    parser.add_argument(
        "--overlay",
        default=None,
        help="Path to projectx/overlay directory. Default: sibling of this script.",
    )
    args = parser.parse_args()
    script_dir = Path(__file__).resolve().parent
    overlay_root = Path(args.overlay or script_dir / "overlay")
    if args.ft_root:
        ft_root = Path(args.ft_root)
    else:
        import freqtrade

        ft_root = Path(freqtrade.__file__).resolve().parent.parent
    install(ft_root, overlay_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
