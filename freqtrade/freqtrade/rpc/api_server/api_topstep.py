"""Topstep-specific REST API endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from freqtrade.rpc import RPC
from freqtrade.rpc.api_server.deps import get_rpc, is_trading_mode


router = APIRouter()


@router.get("/topstep_risk", tags=["Topstep"])
def topstep_risk(rpc: RPC = Depends(get_rpc)) -> dict[str, Any]:
    """Topstep account risk snapshot (daily loss, max loss, consistency)."""
    exchange = rpc._freqtrade.exchange
    if exchange.id != "projectx":
        raise HTTPException(status_code=400, detail="Topstep risk is only available on projectx exchange")
    if not hasattr(exchange, "get_topstep_risk_status"):
        raise HTTPException(status_code=503, detail="Topstep risk tracker not initialized")

    return exchange.get_topstep_risk_status()
