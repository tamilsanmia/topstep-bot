"""Topstep / ProjectX exchange for Freqtrade (non-CCXT gateway)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal

from freqtrade.constants import BuySell, Config
from freqtrade.enums import CandleType, MarginMode, TradingMode
from freqtrade.exceptions import OperationalException, TemporaryError
from freqtrade.exchange import Exchange
from freqtrade.exchange.common import retrier
from freqtrade.exchange.exchange_types import CcxtBalances, CcxtOrder, CcxtPosition, FtHas, OHLCVResponse, OrderBook, Ticker
from freqtrade.exchange.projectx_client import (
    ORDER_MARKET,
    SIDE_BUY,
    SIDE_SELL,
    TIMEFRAME_UNITS,
    ProjectXClient,
    ProjectXError,
)
from freqtrade.exchange.topstep_accounts import (
    AccountFilter,
    TopstepAccountInfo,
    TopstepRulesConfig,
    check_order_allowed,
)
from freqtrade.exchange.topstep_risk import TopstepRiskTracker, handle_topstep_risk_violation
from freqtrade.util.datetime_helpers import dt_ts


logger = logging.getLogger(__name__)


class _ProjectXApiStub:
    """Minimal CCXT-shaped stub so the base Exchange class can initialize."""

    id = "projectx"
    name = "projectx"
    precisionMode = 2
    timeframes = {tf: tf for tf in TIMEFRAME_UNITS}
    options: dict[str, Any] = {"timeframes": {"swap": {tf: tf for tf in TIMEFRAME_UNITS}}}
    has = {
        "fetchOHLCV": True,
        "createOrder": True,
        "createMarketOrder": True,
        "cancelOrder": True,
        "fetchBalance": True,
        "fetchOrder": True,
        "fetchPositions": True,
        "fetchOpenOrders": True,
        "fetchClosedOrders": True,
        "fetchTicker": True,
        "fetchL2OrderBook": True,
    }
    markets: dict[str, Any] = {}
    session = None
    socks_proxy_sessions = None
    features: dict[str, Any] = {"swap": {"linear": {"fetchOHLCV": {"limit": 1000}}}}

    def set_markets_from_exchange(self, other) -> None:
        self.markets = other.markets

    async def close(self) -> None:
        return None

    def calculate_fee(
        self,
        symbol: str,
        type: str,
        side: str,
        amount: float,
        price: float,
        takerOrMaker: str = "maker",
        params: dict | None = None,
    ) -> dict[str, Any]:
        return {"rate": 0.0, "cost": 0.0, "currency": "USD"}


class Projectx(Exchange):
    """TopstepX / ProjectX CME futures via the gateway API."""

    _ft_has: FtHas = {
        "ohlcv_has_history": True,
        "ohlcv_candle_limit": 1000,
        "stoploss_on_exchange": False,
        "trades_has_history": False,
        "always_require_api_keys": True,
        "tickers_have_bid_ask": True,
        "tickers_have_price": True,
        "marketOrderRequiresPrice": False,
        "ws_enabled": False,
        "ccxt_futures_name": "swap",
    }
    _ft_has_futures: FtHas = {
        "stoploss_on_exchange": False,
        "order_props_in_contracts": ["amount", "filled", "remaining"],
        "uses_leverage_tiers": False,
    }
    _supported_trading_mode_margin_pairs: list[tuple[TradingMode, MarginMode]] = [
        (TradingMode.FUTURES, MarginMode.ISOLATED),
        (TradingMode.FUTURES, MarginMode.CROSS),
    ]

    def __init__(self, *args, **kwargs) -> None:
        config: Config = args[0] if args else kwargs["config"]
        ex = kwargs.get("exchange_config") or config.get("exchange", {})
        self._px_username = str(ex.get("username") or "")
        self._px_api_key = str(ex.get("api_key") or ex.get("apiKey") or "")
        self._px_api_base = str(ex.get("api_base") or "https://api.topstepx.com")
        self._px_live_data_raw = ex.get("live_data", "auto")
        self._px_account_pref = ex.get("account_id")
        self._px_account_filter: AccountFilter | None = ex.get("account_filter", "any")
        self._px_rules = TopstepRulesConfig.from_exchange_config(ex)
        self._px: ProjectXClient | None = None
        self._account_id: int | None = None
        self._account_info: TopstepAccountInfo | None = None
        self._risk_tracker: TopstepRiskTracker | None = None
        self._contract_by_pair: dict[str, dict[str, Any]] = {}
        self._last_prices: dict[str, float] = {}
        self._order_cache: dict[str, CcxtOrder] = {}
        super().__init__(*args, **kwargs)

    def _init_ccxt(self, exchange_config: dict[str, Any], sync: bool, ccxt_kwargs: dict[str, Any]) -> _ProjectXApiStub:
        return _ProjectXApiStub()

    @staticmethod
    def _pair_root(pair: str) -> str:
        return pair.split("/")[0].split(":")[0].upper()

    @staticmethod
    def _bar_ts_ms(raw: Any) -> int | None:
        if raw is None:
            return None
        if isinstance(raw, (int, float)):
            ts = int(raw)
            return ts if ts > 10_000_000_000 else ts * 1000
        text = str(raw)
        try:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            return int(datetime.fromisoformat(text).timestamp() * 1000)
        except ValueError:
            return None

    def _resolve_live_data(self) -> bool:
        setting = self._px_live_data_raw
        if isinstance(setting, str) and setting.lower() == "auto":
            if self._account_info:
                return self._account_info.live_data
            return False
        if isinstance(setting, str):
            return setting.lower() in ("1", "true", "yes")
        return bool(setting)

    def _ensure_client(self) -> ProjectXClient:
        if self._px is None:
            if not self._px_username or not self._px_api_key:
                raise OperationalException(
                    "ProjectX credentials missing. Set exchange.username and exchange.api_key in config.json"
                )
            live_data = False
            if not (isinstance(self._px_live_data_raw, str) and self._px_live_data_raw.lower() == "auto"):
                live_data = self._resolve_live_data()
            self._px = ProjectXClient(
                api_base=self._px_api_base,
                username=self._px_username,
                api_key=self._px_api_key,
                live_data=live_data,
            )
            self._px.login()
            preferred = int(self._px_account_pref) if self._px_account_pref else None
            self._account_info = self._px.resolve_account(
                preferred=preferred,
                account_filter=self._px_account_filter,
            )
            self._account_id = self._account_info.account_id
            if isinstance(self._px_live_data_raw, str) and self._px_live_data_raw.lower() == "auto":
                self._px.live_data = self._account_info.live_data
            logger.info(
                "Topstep rules: %s | max %s mini / %s micro | live_data=%s | lot mode (no Freqtrade leverage)",
                self._account_info.display_type,
                self._account_info.rules.max_mini_contracts,
                self._account_info.rules.max_micro_contracts,
                self._px.live_data,
            )
            self._init_risk_tracker()
        return self._px

    def _risk_state_path(self) -> Path:
        from pathlib import Path

        user_dir = Path(self._config.get("user_data_dir", "user_data"))
        return user_dir / f"topstep_risk_{self._account_id}.json"

    def _init_risk_tracker(self) -> None:
        if not self._account_info or not self._px_rules.enabled:
            return
        balance = self._px.fetch_account_balance(int(self._account_id)) if self._px else self._account_info.balance
        self._account_info.balance = balance
        self._risk_tracker = TopstepRiskTracker(
            account=self._account_info,
            rules_cfg=self._px_rules,
            state_path=self._risk_state_path(),
        )
        snap = self._risk_tracker.refresh(balance)
        logger.info(
            "Topstep risk: balance=$%s daily_pnl=$%s drawdown=$%s floor=$%s",
            f"{snap.balance:,.2f}",
            f"{snap.daily_pnl:,.2f}",
            f"{snap.drawdown_from_peak:,.2f}",
            f"{snap.max_loss_floor:,.2f}",
        )
        if snap.warning:
            logger.warning(snap.warning)

    def get_topstep_risk_status(self) -> dict[str, Any]:
        if not self._risk_tracker or not self._account_info:
            return {"enabled": False, "reason": "Topstep risk tracker not initialized"}
        client = self._ensure_client()
        balance = client.fetch_account_balance(int(self._account_id))
        snap = self._risk_tracker.refresh(balance)
        payload = snap.to_dict()
        payload.update(
            {
                "enabled": True,
                "account_id": self._account_id,
                "account_name": self._account_info.name,
                "account_type": self._account_info.display_type,
                "bot_state": self._bot_state_label(),
            }
        )
        return payload

    @staticmethod
    def _bot_state_label() -> str | None:
        try:
            from freqtrade.rpc.api_server.webserver import ApiServer

            if ApiServer._has_rpc and ApiServer._rpc:
                return str(ApiServer._rpc._freqtrade.state)
        except Exception:
            pass
        return None

    def check_topstep_risk(self) -> None:
        """Called each bot loop — refresh risk and auto-pause/stop if limits hit."""
        if not self._risk_tracker or not self._px_rules.enabled:
            return
        try:
            client = self._ensure_client()
            balance = client.fetch_account_balance(int(self._account_id))
            snap = self._risk_tracker.refresh(balance)
            if snap.block_reason:
                handle_topstep_risk_violation(snap, self._px_rules)
        except Exception as exc:
            logger.debug("Topstep risk check skipped: %s", exc)

    def _handle_risk_block(self, snap: Any) -> None:
        handle_topstep_risk_violation(snap, self._px_rules)

    def _pair_for_contract(self, contract_id: Any, pos: dict[str, Any] | None = None) -> str:
        cid = str(contract_id or "")
        for pair, contract in self._contract_by_pair.items():
            if str(contract.get("id")) == cid:
                return pair
        root = ""
        if pos:
            root = str(pos.get("symbol") or pos.get("contractName") or "")
            if not root:
                contract = pos.get("contract") or {}
                root = str(contract.get("name") or contract.get("symbolId") or "")
        if root:
            root = root.split(".")[0].upper()
            for pair in self._config["exchange"].get("pair_whitelist") or []:
                if self._pair_root(pair) == root[:4] or root.startswith(self._pair_root(pair)):
                    return pair
        return root or cid

    @retrier
    def get_balances(self, params: dict | None = None) -> CcxtBalances:
        client = self._ensure_client()
        balance = client.fetch_account_balance(int(self._account_id))
        stake = str(self._config.get("stake_currency", "USD"))
        balances: CcxtBalances = {
            stake: {
                "free": balance,
                "used": 0.0,
                "total": balance,
            }
        }
        self._log_exchange_response("fetch_balance", balances, add_info=params)
        return balances

    def balance_includes_unrealized_pnl(self) -> bool:
        """Topstep account balance from the API matches the platform BAL display."""
        return False

    def fetch_positions(
        self, pair: str | None = None, params: dict | None = None
    ) -> list[CcxtPosition]:
        if self._config["dry_run"] or self.trading_mode != TradingMode.FUTURES:
            return []
        client = self._ensure_client()
        positions: list[CcxtPosition] = []
        for pos in client.search_positions(int(self._account_id)):
            qty = int(pos.get("size") or pos.get("quantity") or 0)
            if qty == 0:
                continue
            contract_id = pos.get("contractId") or (pos.get("contract") or {}).get("id")
            symbol = self._pair_for_contract(contract_id, pos)
            if pair and symbol != pair:
                continue
            lots = abs(qty)
            positions.append(
                {
                    "symbol": symbol,
                    "side": "short" if qty < 0 else "long",
                    "contracts": float(lots),
                    "leverage": self.get_max_leverage(symbol, lots),
                    "collateral": 0.0,
                    "initialMargin": 0.0,
                    "liquidationPrice": None,
                }
            )
        self._log_exchange_response("fetch_positions", positions)
        return positions

    @retrier(retries=3)
    def fetch_order(self, order_id: str, pair: str, params: dict | None = None) -> CcxtOrder:
        if self._config["dry_run"]:
            return self.fetch_dry_run_order(order_id)
        cached = self._order_cache.get(order_id)
        if cached:
            return cached
        contract_size = self.get_contract_size(pair) or 1.0
        ticker = self.fetch_ticker(pair)
        rate = float(ticker.get("last") or ticker.get("ask") or 0)
        return {
            "id": order_id,
            "symbol": pair,
            "type": "market",
            "side": "sell",
            "amount": contract_size,
            "price": rate,
            "average": rate,
            "cost": contract_size * rate,
            "filled": contract_size,
            "remaining": 0.0,
            "status": "closed",
            "fee": {"cost": 0.0, "currency": self._config.get("stake_currency", "USD")},
            "info": {},
        }

    def additional_exchange_init(self) -> None:
        self._ensure_client()

    def validate_timeframes(self, timeframe: str | None) -> None:
        if timeframe and timeframe not in TIMEFRAME_UNITS:
            raise OperationalException(
                f"Timeframe {timeframe} not supported on ProjectX. "
                f"Supported: {', '.join(TIMEFRAME_UNITS)}"
            )

    def reload_markets(self, force: bool = False, *, load_leverage_tiers: bool = True) -> None:
        if (
            not force
            and self._last_markets_refresh > 0
            and (self._last_markets_refresh + self.markets_refresh_interval > dt_ts())
        ):
            return

        client = self._ensure_client()
        markets: dict[str, Any] = {}
        whitelist = self._config["exchange"].get("pair_whitelist") or []

        for pair in whitelist:
            root = self._pair_root(pair)
            contract = client.resolve_contract(root)
            self._contract_by_pair[pair] = contract
            tick = float(contract.get("tickSize") or 0.25) or 0.25
            contract_size = self._contract_size_from_api(contract)
            max_lots = 100
            if self._account_info:
                max_lots = self._account_info.rules.max_lots_for_root(root)
            markets[pair] = {
                "id": pair,
                "symbol": pair,
                "base": root,
                "quote": pair.split("/")[1].split(":")[0] if "/" in pair else "USD",
                "active": True,
                "spot": False,
                "swap": True,
                "type": "swap",
                "future": True,
                "contract": True,
                "linear": True,
                "maker": 0.0,
                "taker": 0.0,
                "precision": {"amount": 0, "price": len(str(tick).split(".")[-1]) if "." in str(tick) else 0},
                "limits": {
                    "amount": {"min": 1, "max": max_lots},
                    "cost": {"min": 0, "max": None},
                },
                "contractSize": contract_size,
                "info": contract,
            }
            logger.info(
                "  %s contractSize=%s ($/point) tickSize=%s tickValue=%s",
                pair,
                contract_size,
                tick,
                float(contract.get("tickValue") or 0),
            )

        self._markets = markets
        self._api.markets = markets
        self._api_async.markets = markets
        self._last_markets_refresh = dt_ts()
        logger.info("Loaded %s ProjectX market(s)", len(markets))

    @staticmethod
    def _contract_size_from_api(contract: dict[str, Any]) -> float:
        """Dollar P&L per index point for one contract (tickValue / tickSize)."""
        tick_size = float(contract.get("tickSize") or 0)
        tick_value = float(contract.get("tickValue") or 0)
        if tick_size > 0 and tick_value > 0:
            return tick_value / tick_size
        return 1.0

    async def _async_get_candle_history(
        self,
        pair: str,
        timeframe: str,
        candle_type: CandleType,
        since_ms: int | None = None,
    ) -> OHLCVResponse:
        if candle_type not in (CandleType.SPOT, CandleType.FUTURES):
            self.verify_candle_type_support(candle_type)

        client = self._ensure_client()
        contract = self._contract_by_pair.get(pair)
        if not contract:
            contract = client.resolve_contract(self._pair_root(pair))
            self._contract_by_pair[pair] = contract

        limit = self.ohlcv_candle_limit(timeframe, candle_type, since_ms)
        try:
            bars = client.retrieve_bars(contract["id"], timeframe, count=limit)
        except ProjectXError as exc:
            raise TemporaryError(str(exc)) from exc

        ohlcv: list[list[float]] = []
        for bar in bars:
            ts = self._bar_ts_ms(bar.get("t") or bar.get("timestamp") or bar.get("time"))
            if ts is None:
                continue
            if since_ms is not None and ts < since_ms:
                continue
            open_ = float(bar.get("o") or bar.get("open") or 0)
            high = float(bar.get("h") or bar.get("high") or 0)
            low = float(bar.get("l") or bar.get("low") or 0)
            close = float(bar.get("c") or bar.get("close") or 0)
            volume = float(bar.get("v") or bar.get("volume") or 0)
            if open_ <= 0 or close <= 0 or high < low:
                continue
            ohlcv.append([ts, open_, high, low, close, volume])

        ohlcv.sort(key=lambda row: row[0])
        if ohlcv:
            self._last_prices[pair] = float(ohlcv[-1][4])
        return (pair, timeframe, candle_type, ohlcv, self._ohlcv_partial_candle)

    def _stake_is_lots(self) -> bool:
        """TopstepX sizes orders in integer contract lots, not USD stake."""
        return bool(self._config.get("exchange", {}).get("stake_is_lots", True))

    def _lot_limits(self, pair: str) -> tuple[int, int]:
        market = self.markets.get(pair) or {}
        limits = market.get("limits", {}).get("amount", {})
        min_lots = int(limits.get("min") or 1)
        max_lots = int(limits.get("max") or 100)
        return min_lots, max_lots

    def _clamp_lots(self, pair: str, lots: float) -> int:
        min_lots, max_lots = self._lot_limits(pair)
        return max(min_lots, min(max_lots, int(round(lots))))

    def _lots_from_freqtrade_amount(self, pair: str, amount: float) -> int:
        """
        Freqtrade computes ``amount = stake / price * leverage`` (USD stake model).
        On ProjectX, ``stake_amount`` in config is the number of contracts to trade.
        """
        if amount >= 1:
            return self._clamp_lots(pair, amount)

        stake_lots = self._config.get("stake_amount", 1)
        if isinstance(stake_lots, (int, float)):
            return self._clamp_lots(pair, float(stake_lots))

        return self._clamp_lots(pair, 1)

    def _get_stake_amount_limit(
        self,
        pair: str,
        price: float,
        stoploss: float,
        limit: Literal["min", "max"],
        leverage: float = 1.0,
    ) -> float | None:
        if not self._stake_is_lots():
            return super()._get_stake_amount_limit(pair, price, stoploss, limit, leverage)

        min_lots, max_lots = self._lot_limits(pair)
        if limit == "min":
            return float(min_lots)

        cfg = self._config.get("stake_amount", min_lots)
        if isinstance(cfg, (int, float)):
            return float(min(max_lots, max(min_lots, cfg)))
        return float(max_lots)

    def _get_stake_amount_considering_leverage(self, stake_amount: float, leverage: float) -> float:
        if self._stake_is_lots():
            return stake_amount
        return super()._get_stake_amount_considering_leverage(stake_amount, leverage)

    def create_dry_run_order(
        self,
        pair: str,
        ordertype: str,
        side: BuySell,
        amount: float,
        rate: float,
        leverage: float,
        params: dict | None = None,
        stop_loss: bool = False,
        stop_price: float | None = None,
    ) -> CcxtOrder:
        if self._stake_is_lots():
            lots = self._lots_from_freqtrade_amount(pair, amount)
            contract_size = self.get_contract_size(pair) or 1.0
            amount = float(lots) * float(contract_size)
        return super().create_dry_run_order(
            pair,
            ordertype,
            side,
            amount,
            rate,
            leverage,
            params=params,
            stop_loss=stop_loss,
            stop_price=stop_price,
        )

    def fetch_l2_order_book(self, pair: str, limit: int = 100) -> OrderBook:
        ticker = self.fetch_ticker(pair)
        rate = float(ticker.get("last") or ticker.get("ask") or 0)
        if rate <= 0:
            rate = 1.0
        return {
            "bids": [[rate, 100.0]],
            "asks": [[rate, 100.0]],
            "timestamp": dt_ts(),
            "datetime": None,
            "nonce": None,
        }

    def fetch_ticker(self, pair: str, params: dict | None = None) -> Ticker:
        rate = self._last_prices.get(pair)
        if not rate:
            contract = self._contract_by_pair.get(pair)
            if contract:
                bars = self._ensure_client().retrieve_bars(contract["id"], self._config["timeframe"], count=2)
                if bars:
                    rate = float(bars[-1].get("c") or bars[-1].get("close") or 0)
                    self._last_prices[pair] = rate
        if not rate:
            rate = 0.0
        return {
            "symbol": pair,
            "last": rate,
            "bid": rate,
            "ask": rate,
            "baseVolume": 0,
            "quoteVolume": 0,
        }

    def _validate_topstep_order(
        self,
        pair: str,
        amount: float,
        reduce_only: bool,
    ) -> int:
        client = self._ensure_client()
        size = self._lots_from_freqtrade_amount(pair, amount)
        if not self._account_info or not self._px_rules.enabled:
            return size

        root = self._pair_root(pair)
        positions = client.search_positions(int(self._account_id))
        block_reason = check_order_allowed(
            account=self._account_info,
            rules_cfg=self._px_rules,
            pair_root=root,
            order_lots=size,
            open_positions=positions,
            reduce_only=reduce_only,
        )
        if block_reason:
            raise OperationalException(block_reason)

        if self._risk_tracker and not reduce_only:
            balance = client.fetch_account_balance(int(self._account_id))
            risk = self._risk_tracker.check_entry(balance)
            if risk.block_reason:
                self._handle_risk_block(risk)
                raise OperationalException(risk.block_reason)

        return size

    def create_order(
        self,
        *,
        pair: str,
        ordertype: str,
        side: BuySell,
        amount: float,
        rate: float,
        leverage: float,
        time_in_force: str = "GTC",
        reduceOnly: bool = False,
        initial_order: bool = True,
    ) -> CcxtOrder:
        size = self._validate_topstep_order(pair, amount, reduceOnly)

        if self._config["dry_run"]:
            return self.create_dry_run_order(
                pair, ordertype, side, float(size), self.price_to_precision(pair, rate), leverage
            )

        client = self._ensure_client()
        contract = self._contract_by_pair.get(pair)
        if not contract:
            contract = client.resolve_contract(self._pair_root(pair))
            self._contract_by_pair[pair] = contract

        px_side = SIDE_BUY if side == "buy" else SIDE_SELL
        try:
            result = client.place_order(
                account_id=int(self._account_id),
                contract_id=contract["id"],
                side=px_side,
                size=size,
                order_type=ORDER_MARKET,
            )
        except ProjectXError as exc:
            raise TemporaryError(str(exc)) from exc

        fill_rate = float(
            result.get("averagePrice")
            or result.get("price")
            or result.get("fillPrice")
            or rate
        )
        if not fill_rate or fill_rate == rate:
            try:
                for pos in client.search_positions(int(self._account_id)):
                    cid = pos.get("contractId") or (pos.get("contract") or {}).get("id")
                    if str(cid) == str(contract.get("id")):
                        fill_rate = float(pos.get("averagePrice") or fill_rate or rate)
                        break
            except ProjectXError:
                pass

        order_id = str(result.get("orderId") or result.get("id") or result.get("order_id") or dt_ts())
        px_rate = self.price_to_precision(pair, fill_rate or rate)
        contract_size = self.get_contract_size(pair) or 1.0
        order: CcxtOrder = {
            "id": order_id,
            "symbol": pair,
            "type": ordertype,
            "side": side,
            "amount": float(size),
            "price": px_rate,
            "average": px_rate,
            "cost": float(size) * float(px_rate),
            "filled": float(size),
            "remaining": 0.0,
            "status": "closed",
            "fee": {"cost": 0.0, "currency": self._config.get("stake_currency", "USD")},
            "info": result,
        }
        order = self._order_contracts_to_amount(order)
        self._order_cache[order_id] = order
        if self._risk_tracker:
            try:
                balance = client.fetch_account_balance(int(self._account_id))
                self._risk_tracker.refresh(balance)
            except ProjectXError:
                pass
        return order

    def get_funding_fees(
        self,
        pair: str,
        amount: float,
        is_short: bool,
        open_date: datetime,
    ) -> float:
        """CME futures on TopstepX have no crypto-style funding fees."""
        return 0.0

    def get_max_leverage(self, pair: str, stake_amount: float) -> float:
        """TopstepX margin is applied by the exchange; size is always in integer lots."""
        if self._stake_is_lots():
            return 1.0
        ex = self._config.get("exchange", {})
        return float(ex.get("max_leverage", ex.get("leverage", 1)))

    def get_fee(
        self,
        symbol: str,
        order_type: str = "",
        side: str = "",
        amount: float = 1,
        price: float = 1,
        taker_or_maker: str = "maker",
    ) -> float:
        if self._config.get("fee") is not None:
            return float(self._config["fee"])
        return 0.0

    def fill_leverage_tiers(self) -> None:
        self._leverage_tiers = {}

    def ws_connection_reset(self) -> None:
        return None
