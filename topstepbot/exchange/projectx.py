from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

# ProjectX History API bar units
TIMEFRAME_UNITS: dict[str, tuple[int, int]] = {
    "1s": (1, 1),
    "5s": (1, 5),
    "15s": (1, 15),
    "30s": (1, 30),
    "1m": (2, 1),
    "3m": (2, 3),
    "5m": (2, 5),
    "15m": (2, 15),
    "30m": (2, 30),
    "1h": (3, 1),
    "4h": (3, 4),
    "1d": (4, 1),
    "1w": (5, 1),
    "1M": (6, 1),
}

# Order side: 0=BUY, 1=SELL
SIDE_BUY = 0
SIDE_SELL = 1

# Order type
ORDER_LIMIT = 1
ORDER_MARKET = 2
ORDER_STOP = 4


class ProjectXError(RuntimeError):
    pass


class ProjectXClient:
    """Direct TopstepX / ProjectX gateway client."""

    def __init__(
        self,
        *,
        api_base: str,
        username: str,
        api_key: str,
        live_data: bool = False,
        timeout: float = 30.0,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.username = username
        self.api_key = api_key
        self.live_data = live_data
        self.timeout = timeout
        self._token: str | None = None
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json", "Accept": "application/json"})

    def _post(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        url = f"{self.api_base}{path}"
        headers = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        resp = self._session.post(url, json=payload or {}, headers=headers, timeout=self.timeout)
        if resp.status_code == 401 and self._token:
            self._token = None
            return self._post(path, payload)
        if not resp.ok:
            raise ProjectXError(f"{path} failed ({resp.status_code}): {resp.text[:500]}")
        if not resp.text.strip():
            return {}
        return resp.json()

    def login(self) -> str:
        data = self._post("/api/Auth/loginKey", {"userName": self.username, "apiKey": self.api_key})
        token = data.get("token") or data.get("accessToken")
        if not token:
            raise ProjectXError(f"Auth failed: {data}")
        self._token = token
        logger.info("ProjectX authenticated")
        return token

    def ensure_auth(self) -> None:
        if not self._token:
            self.login()

    def search_accounts(self, only_active: bool = True) -> list[dict[str, Any]]:
        self.ensure_auth()
        data = self._post("/api/Account/search", {"onlyActiveAccounts": only_active})
        return list(data if isinstance(data, list) else data.get("accounts", data.get("results", [])))

    def resolve_account_id(self, preferred: int | None = None) -> int:
        if preferred:
            return preferred
        accounts = self.search_accounts()
        if not accounts:
            raise ProjectXError("No active ProjectX accounts found")
        acct = accounts[0]
        account_id = acct.get("id") or acct.get("accountId")
        if account_id is None:
            raise ProjectXError(f"Could not parse account id from {acct}")
        logger.info("Using account %s (%s)", account_id, acct.get("name", acct.get("accountName", "?")))
        return int(account_id)

    def available_contracts(self, *, live: bool | None = None) -> list[dict[str, Any]]:
        self.ensure_auth()
        data = self._post("/api/Contract/available", {"live": self.live_data if live is None else live})
        return list(data if isinstance(data, list) else data.get("contracts", data.get("results", [])))

    def resolve_contract(self, root: str) -> dict[str, Any]:
        root_upper = root.upper()
        contracts = self.available_contracts()
        matches = [
            c for c in contracts
            if str(c.get("name", "")).upper().startswith(root_upper)
            or str(c.get("symbolId", "")).upper().startswith(root_upper)
            or str(c.get("description", "")).upper().startswith(root_upper)
        ]
        if not matches:
            raise ProjectXError(f"No contract found for root '{root}'. Available: {[c.get('name') for c in contracts[:8]]}")
        # Prefer active front month (smallest id/name heuristic)
        matches.sort(key=lambda c: str(c.get("name", "")))
        contract = matches[0]
        logger.info("Resolved contract %s -> id=%s", root, contract.get("id"))
        return contract

    def retrieve_bars(
        self,
        contract_id: str | int,
        timeframe: str,
        *,
        count: int = 500,
    ) -> list[dict[str, Any]]:
        self.ensure_auth()
        if timeframe not in TIMEFRAME_UNITS:
            raise ProjectXError(f"Unsupported timeframe '{timeframe}'. Supported: {list(TIMEFRAME_UNITS)}")
        unit, unit_number = TIMEFRAME_UNITS[timeframe]
        end = datetime.now(timezone.utc)
        # Estimate lookback — gateway expects startTime/endTime
        minutes_per_bar = {
            1: unit_number,
            2: unit_number,
            3: unit_number * 60,
            4: unit_number * 24 * 60,
            5: unit_number * 7 * 24 * 60,
            6: unit_number * 30 * 24 * 60,
        }
        bar_minutes = minutes_per_bar.get(unit, 5)
        span = timedelta(minutes=bar_minutes * count * 1.5)
        start = end - span
        payload = {
            "contractId": contract_id,
            "live": self.live_data,
            "startTime": start.isoformat().replace("+00:00", "Z"),
            "endTime": end.isoformat().replace("+00:00", "Z"),
            "unit": unit,
            "unitNumber": unit_number,
            "limit": min(max(count, 1), 20000),
            "includePartialBar": True,
        }
        data = self._post("/api/History/retrieveBars", payload)
        bars = data if isinstance(data, list) else data.get("bars", data.get("results", []))
        return list(bars)

    def search_open_orders(self, account_id: int) -> list[dict[str, Any]]:
        self.ensure_auth()
        data = self._post("/api/Order/searchOpen", {"accountId": account_id})
        return list(data if isinstance(data, list) else data.get("orders", data.get("results", [])))

    def search_positions(self, account_id: int) -> list[dict[str, Any]]:
        self.ensure_auth()
        data = self._post("/api/Position/searchOpen", {"accountId": account_id})
        return list(data if isinstance(data, list) else data.get("positions", data.get("results", [])))

    def place_order(
        self,
        *,
        account_id: int,
        contract_id: str | int,
        side: int,
        size: int,
        order_type: int = ORDER_MARKET,
        limit_price: float | None = None,
        stop_price: float | None = None,
    ) -> dict[str, Any]:
        self.ensure_auth()
        payload: dict[str, Any] = {
            "accountId": account_id,
            "contractId": contract_id,
            "type": order_type,
            "side": side,
            "size": size,
        }
        if limit_price is not None:
            payload["limitPrice"] = limit_price
        if stop_price is not None:
            payload["stopPrice"] = stop_price
        return self._post("/api/Order/place", payload)

    def cancel_order(self, account_id: int, order_id: int | str) -> dict[str, Any]:
        self.ensure_auth()
        return self._post("/api/Order/cancel", {"accountId": account_id, "orderId": order_id})

    def flatten_position(self, account_id: int, contract_id: str | int) -> dict[str, Any]:
        positions = self.search_positions(account_id)
        for pos in positions:
            pid = pos.get("contractId") or pos.get("contract", {}).get("id")
            if str(pid) != str(contract_id):
                continue
            qty = int(pos.get("size") or pos.get("quantity") or 0)
            if qty == 0:
                continue
            side = SIDE_SELL if qty > 0 else SIDE_BUY
            return self.place_order(
                account_id=account_id,
                contract_id=contract_id,
                side=side,
                size=abs(qty),
                order_type=ORDER_MARKET,
            )
        return {}
