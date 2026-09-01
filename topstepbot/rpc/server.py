from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from topstepbot.config import ApiServerConfig, BotConfig
from topstepbot.rpc.auth import (
    _basic,
    _bearer,
    create_access_token,
    create_refresh_token,
    decode_token,
    require_user,
    verify_credentials,
)
from topstepbot.rpc.state import BotRunState, BotState

logger = logging.getLogger(__name__)

WEB_ROOT = Path(__file__).resolve().parent.parent / "web" / "static"


class LoginBody(BaseModel):
    username: str
    password: str


class ForceEnterBody(BaseModel):
    pair: str
    side: str = "long"
    ordertype: str = "market"
    stakeamount: float | None = None


class ForceExitBody(BaseModel):
    tradeid: int | str
    ordertype: str = "market"


def create_app(config: BotConfig, state: BotState) -> FastAPI:
    api_config = config.api_server
    app = FastAPI(title="TopstepBot API", docs_url="/docs" if api_config.enable_openapi else None)

    if api_config.CORS_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=api_config.CORS_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def make_auth():
        def auth_user(
            credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
            basic: HTTPBasicCredentials | None = Depends(_basic),
        ) -> str:
            return require_user(api_config, credentials, basic)

        return auth_user

    auth_user = make_auth()

    @app.get("/")
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/trade")

    @app.get("/api/v1/ping")
    async def ping() -> dict[str, str]:
        return {"status": "pong"}

    @app.get("/api/v1/version")
    async def version(user: str = Depends(auth_user)) -> dict[str, str]:
        return {"version": "0.1.0"}

    @app.post("/api/v1/token/login")
    async def token_login(body: LoginBody | None = None) -> dict[str, str]:
        if body is None:
            raise HTTPException(status_code=401, detail="Credentials required")
        if not verify_credentials(body.username, body.password, api_config):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        return {
            "access_token": create_access_token(body.username, api_config.jwt_secret_key),
            "refresh_token": create_refresh_token(body.username, api_config.jwt_secret_key),
        }

    @app.post("/api/v1/token/refresh")
    async def token_refresh(body: dict[str, str]) -> dict[str, str]:
        token = body.get("refresh_token") or body.get("access_token", "")
        payload = decode_token(token, api_config.jwt_secret_key)
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        identity = str(payload.get("identity", {}).get("u", api_config.username))
        return {"access_token": create_access_token(identity, api_config.jwt_secret_key)}

    @app.get("/api/v1/show_config")
    async def show_config(user: str = Depends(auth_user)) -> dict[str, Any]:
        return {
            "bot_name": config.bot_name,
            "dry_run": config.dry_run,
            "strategy": config.strategy,
            "timeframe": config.timeframe,
            "stake_amount": config.stake_amount,
            "max_open_trades": config.max_open_trades,
            "pair_whitelist": config.pairs,
            "state": state.run_state.value,
            "force_entry_enable": config.force_entry_enable,
            "process_throttle_secs": config.process_throttle_secs,
        }

    @app.get("/api/v1/status")
    async def status_endpoint(user: str = Depends(auth_user)) -> list[dict[str, Any]]:
        if state.position_qty == 0 and not state.open_trades:
            return []
        results: list[dict[str, Any]] = []
        for trade in state.open_trades:
            results.append(trade.to_dict())
        if not results and state.position_qty != 0:
            results.append(
                {
                    "trade_id": 0,
                    "pair": state.primary_pair,
                    "is_open": True,
                    "is_short": state.position_qty < 0,
                    "amount": abs(state.position_qty),
                    "stake_amount": config.stake_amount,
                    "open_rate": state.last_close,
                    "current_rate": state.last_close,
                    "profit_abs": 0.0,
                    "profit_ratio": 0.0,
                }
            )
        return results

    @app.get("/api/v1/count")
    async def count(user: str = Depends(auth_user)) -> dict[str, int]:
        open_count = len(state.open_trades) or (1 if state.position_qty else 0)
        return {
            "current": open_count,
            "max": config.max_open_trades,
            "total_stake": open_count * config.stake_amount,
        }

    @app.get("/api/v1/trades")
    async def trades(limit: int = 500, user: str = Depends(auth_user)) -> list[dict[str, Any]]:
        items = list(reversed(state.trades[-limit:]))
        return [t.to_dict() for t in items]

    @app.get("/api/v1/profit")
    async def profit(user: str = Depends(auth_user)) -> dict[str, Any]:
        summary = state.total_profit()
        return {
            **summary,
            "profit_all_coin": summary["profit_closed_coin"],
            "profit_all_percent": summary["profit_closed_percent"],
            "best_pair": state.primary_pair,
            "worst_pair": state.primary_pair,
        }

    @app.get("/api/v1/balance")
    async def balance(user: str = Depends(auth_user)) -> dict[str, Any]:
        return {
            "currencies": [
                {
                    "currency": "USD",
                    "free": 0.0,
                    "balance": 0.0,
                    "used": 0.0,
                    "bot_owned": 0.0,
                    "est_stake": config.stake_amount,
                    "est_stake_bot": config.stake_amount,
                }
            ],
            "total": 0.0,
            "symbol": state.primary_pair,
            "value": state.last_close,
            "note": "Balance sync from Topstep account can be added via ProjectX API",
        }

    @app.get("/api/v1/whitelist")
    async def whitelist(user: str = Depends(auth_user)) -> dict[str, list[str]]:
        return {"whitelist": config.pairs}

    @app.get("/api/v1/logs")
    async def logs(limit: int = 50, user: str = Depends(auth_user)) -> dict[str, list[str]]:
        return {"logs": list(state.logs)[:limit]}

    @app.get("/api/v1/health")
    async def health(user: str = Depends(auth_user)) -> dict[str, Any]:
        return {
            "last_process": state.last_loop,
            "last_process_ts": state.last_loop,
            "bot_state": state.run_state.value,
            "last_signal": state.last_signal,
            "position_qty": state.position_qty,
            "last_close": state.last_close,
            "last_error": state.last_error,
        }

    @app.get("/api/v1/daily")
    async def daily(timescale: int = 7, user: str = Depends(auth_user)) -> list[dict[str, Any]]:
        return [{"date": "summary", "abs_profit": state.total_profit()["profit_closed_coin"], "fiat_value": 0.0}]

    @app.get("/api/v1/performance")
    async def performance(user: str = Depends(auth_user)) -> list[dict[str, Any]]:
        by_pair: dict[str, float] = {}
        for trade in state.closed_trades:
            by_pair[trade.pair] = by_pair.get(trade.pair, 0.0) + trade.profit_abs
        return [{"pair": pair, "profit": profit} for pair, profit in by_pair.items()]

    @app.post("/api/v1/start")
    async def start(user: str = Depends(auth_user)) -> dict[str, str]:
        state.run_state = BotRunState.RUNNING
        state.add_log("Bot started via API")
        return {"status": "running"}

    @app.post("/api/v1/stop")
    async def stop(user: str = Depends(auth_user)) -> dict[str, str]:
        state.run_state = BotRunState.STOPPED
        state.add_log("Bot stopped via API")
        if state._bot:
            state._bot.stop()
        return {"status": "stopped"}

    @app.post("/api/v1/pause")
    async def pause(user: str = Depends(auth_user)) -> dict[str, str]:
        state.run_state = BotRunState.PAUSED
        state.add_log("Bot paused via API")
        return {"status": "paused"}

    @app.post("/api/v1/stopbuy")
    async def stopbuy(user: str = Depends(auth_user)) -> dict[str, str]:
        state.run_state = BotRunState.STOPBUY
        state.add_log("Bot stopbuy via API — no new entries")
        return {"status": "stopbuy"}

    @app.post("/api/v1/forceenter")
    async def forceenter(body: ForceEnterBody, user: str = Depends(auth_user)) -> dict[str, Any]:
        if not config.force_entry_enable:
            raise HTTPException(status_code=403, detail="force_entry_enable is false in config")
        if not state._bot:
            raise HTTPException(status_code=503, detail="Bot not ready")
        side_label = body.side.lower()
        from topstepbot.exchange.projectx import SIDE_BUY, SIDE_SELL

        side = SIDE_SELL if side_label == "short" else SIDE_BUY
        state._bot._open_position(side, side_label)
        return {"status": "forced entry", "pair": body.pair, "side": side_label}

    @app.post("/api/v1/forceexit")
    async def forceexit(body: ForceExitBody, user: str = Depends(auth_user)) -> dict[str, Any]:
        if not state._bot:
            raise HTTPException(status_code=503, detail="Bot not ready")
        qty = state.position_qty
        if qty == 0:
            return {"status": "no open position"}
        label = "short" if qty < 0 else "long"
        state._bot._close_position(label, qty)
        return {"status": "forced exit", "tradeid": body.tradeid}

    @app.websocket("/api/v1/message/ws")
    async def message_ws(websocket: WebSocket, token: str = "") -> None:
        if token != api_config.ws_token:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        state.ws_subscribers.append(websocket)
        try:
            while True:
                data = await websocket.receive_json()
                if data.get("type") == "subscribe":
                    await websocket.send_json({"type": "subscribed", "data": data.get("data", [])})
        except WebSocketDisconnect:
            pass
        finally:
            if websocket in state.ws_subscribers:
                state.ws_subscribers.remove(websocket)

    if WEB_ROOT.exists():
        app.mount("/static", StaticFiles(directory=WEB_ROOT), name="static")

        @app.get("/trade")
        async def trade_ui() -> FileResponse:
            return FileResponse(WEB_ROOT / "index.html")

    return app


class ApiServer:
    """Uvicorn server for the Freqtrade-compatible API."""

    def __init__(self, config: BotConfig, state: BotState) -> None:
        self.config = config
        self.state = state
        self._thread: threading.Thread | None = None
        self._app = create_app(config, state)

    def _uvicorn_kwargs(self) -> dict[str, Any]:
        api = self.config.api_server
        log_level = "error" if api.verbosity == "error" else api.verbosity
        return {
            "host": api.listen_ip_address,
            "port": api.listen_port,
            "log_level": log_level,
            "access_log": log_level != "error",
        }

    def start(self) -> None:
        """Start API server in a background thread."""
        if not self.config.api_server.enabled:
            return

        def run() -> None:
            uvicorn.run(self._app, **self._uvicorn_kwargs())

        self._thread = threading.Thread(target=run, name="api-server", daemon=True)
        self._thread.start()
        self._log_started()

    def run_blocking(self) -> None:
        """Run API server in the current thread (keeps process alive for Docker)."""
        if not self.config.api_server.enabled:
            return
        self._log_started()
        uvicorn.run(self._app, **self._uvicorn_kwargs())

    def _log_started(self) -> None:
        api = self.config.api_server
        logger.info(
            "API server listening on http://%s:%s (dashboard: /trade)",
            api.listen_ip_address,
            api.listen_port,
        )
