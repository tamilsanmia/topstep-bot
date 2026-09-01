from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, HTTPBasic, HTTPBasicCredentials

from topstepbot.config import ApiServerConfig

_bearer = HTTPBearer(auto_error=False)
_basic = HTTPBasic(auto_error=False)


def create_token(*, identity: str, secret: str, token_type: str, minutes: int) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(minutes=minutes),
        "identity": {"u": identity},
        "type": token_type,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def create_access_token(identity: str, secret: str) -> str:
    return create_token(identity=identity, secret=secret, token_type="access", minutes=15)


def create_refresh_token(identity: str, secret: str) -> str:
    return create_token(identity=identity, secret=secret, token_type="refresh", minutes=60 * 24 * 30)


def decode_token(token: str, secret: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc


def verify_credentials(username: str, password: str, api_config: ApiServerConfig) -> bool:
    return username == api_config.username and password == api_config.password


def require_user(
    api_config: ApiServerConfig,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    basic: HTTPBasicCredentials | None = Depends(_basic),
) -> str:
    if credentials and credentials.credentials:
        payload = decode_token(credentials.credentials, api_config.jwt_secret_key)
        if payload.get("type") != "access":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
        identity = payload.get("identity", {})
        return str(identity.get("u", ""))

    if basic and verify_credentials(basic.username, basic.password, api_config):
        return basic.username

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
