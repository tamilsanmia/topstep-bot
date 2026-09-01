"""TopstepX / ProjectX gateway client (used by the ProjectX freqtrade exchange)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from freqtrade.exchange.topstep_accounts import (
    AccountFilter,
    TopstepAccountInfo,
    select_account,
)

logger = logging.getLogger(__name__)

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

SIDE_BUY = 0
SIDE_SELL = 1
ORDER_MARKET = 2


class ProjectXError(RuntimeError):
    pass


class ProjectXClient:
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

    def search_positions(self, account_id: int) -> list[dict[str, Any]]:
        self.ensure_auth()
        data = self._post("/api/Position/searchOpen", {"accountId": account_id})
        return list(data if isinstance(data, list) else data.get("positions", data.get("results", [])))

    def resolve_account(
        self,
        preferred: int | None = None,
        account_filter: AccountFilter | None = "any",
    ) -> TopstepAccountInfo:
        accounts = self.search_accounts()
        info = select_account(accounts, preferred_id=preferred, account_filter=account_filter)
        logger.info(
            "Using Topstep account %s (%s) — %s | live_data=%s",
            info.account_id,
            info.name,
            info.display_type,
            info.live_data,
        )
        return info

    def resolve_account_id(self, preferred: int | None = None) -> int:
        return self.resolve_account(preferred=preferred).account_id

    def fetch_account(self, account_id: int) -> dict[str, Any]:
        self.ensure_auth()
        for acct in self.search_accounts(only_active=False):
            aid = acct.get("id") or acct.get("accountId")
            if aid is not None and int(aid) == int(account_id):
                return acct
        raise ProjectXError(f"Account {account_id} not found")

    def fetch_account_balance(self, account_id: int) -> float:
        acct = self.fetch_account(account_id)
        return float(acct.get("balance") or acct.get("accountBalance") or 0)

    def available_contracts(self, *, live: bool | None = None) -> list[dict[str, Any]]:
        self.ensure_auth()
        data = self._post("/api/Contract/available", {"live": self.live_data if live is None else live})
        return list(data if isinstance(data, list) else data.get("contracts", data.get("results", [])))

    def resolve_contract(self, root: str) -> dict[str, Any]:
        root_upper = root.upper()
        contracts = self.available_contracts()
        matches = [
            c
            for c in contracts
            if str(c.get("name", "")).upper().startswith(root_upper)
            or str(c.get("symbolId", "")).upper().startswith(root_upper)
            or str(c.get("description", "")).upper().startswith(root_upper)
        ]
        if not matches:
            raise ProjectXError(
                f"No contract found for root '{root}'. "
                f"Available: {[c.get('name') for c in contracts[:8]]}"
            )
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
        minutes_per_bar = {
            1: unit_number,
            2: unit_number,
            3: unit_number * 60,
            4: unit_number * 24 * 60,
            5: unit_number * 7 * 24 * 60,
            6: unit_number * 30 * 24 * 60,
        }
        bar_minutes = minutes_per_bar.get(unit, 5)
        span = timedelta(minutes=bar_minutes * count * 2.0)
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

    def place_order(
        self,
        *,
        account_id: int,
        contract_id: str | int,
        side: int,
        size: int,
        order_type: int = ORDER_MARKET,
        limit_price: float | None = None,
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
        return self._post("/api/Order/place", payload)
