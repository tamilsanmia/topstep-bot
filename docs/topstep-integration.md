# Topstep integration

This project uses the official **Freqtrade Docker image** (`freqtradeorg/freqtrade:latest`) with a **ProjectX overlay** applied at build time — no vendored Freqtrade fork.

## Architecture

```
FreqUI (:8080)
      │
      ▼
Freqtrade engine
      ├── Strategy (user_data/strategies/)
      ├── projectx exchange adapter
      └── topstep_risk guardrails
              │
              ▼
      TopstepX Gateway API
      https://api.topstepx.com
```

---

## Integration file map

All TopstepX-related code lives in **`projectx/overlay/`** (copied in) and **`projectx/install.py`** (patches upstream Freqtrade), plus this repo’s config, strategies, and scripts.

### Overlay files (copied verbatim)

| File | Purpose |
|------|---------|
| `projectx/overlay/freqtrade/exchange/projectx.py` | **ProjectX exchange adapter** — OHLCV, orders, balances, positions, lot sizing, P&L (`contractSize`), risk hooks |
| `projectx/overlay/freqtrade/exchange/projectx_client.py` | **TopstepX HTTP client** — auth, accounts, contracts, bars, orders, positions |
| `projectx/overlay/freqtrade/exchange/projectx_signalr.py` | **SignalR market hub client** — WebSocket connect, quote/trade subscriptions |
| `projectx/overlay/freqtrade/exchange/projectx_exchange_ws.py` | **Live OHLCV websocket feed** — REST seed + real-time GatewayQuote/Trade updates |
| `projectx/overlay/freqtrade/exchange/topstep_accounts.py` | Account types (combine / express / live), plan limits, account selection |
| `projectx/overlay/freqtrade/exchange/topstep_risk.py` | Daily loss, max loss, consistency tracking; auto pause/stop |
| `projectx/overlay/freqtrade/rpc/api_server/api_topstep.py` | **`GET /api/v1/topstep_risk`** REST endpoint |

### Core Freqtrade patches (`projectx/install.py`)

| Upstream file | Change |
|------|--------|
| `freqtrade/exchange/__init__.py` | Exports `Projectx` exchange class |
| `freqtrade/exchange/common.py` | Registers `"projectx"` as supported exchange |
| `freqtrade/exchange/check_exchange.py` | ProjectX validation / startup message |
| `freqtrade/exchange/exchange_utils.py` | ProjectX-specific exchange utilities |
| `freqtrade/freqtradebot.py` | `check_topstep_risk()`, live P&L websocket push |
| `freqtrade/rpc/rpc.py` | Uses `get_trade_unrealized_profit()` for open-trade P&L |
| `freqtrade/rpc/api_server/webserver.py` | Mounts `api_topstep` router; thread-safe WS publish |
| `freqtrade/rpc/api_server/api_ws.py` | Broadcasts `trade_status` without subscription |
| `freqtrade/rpc/api_server/ws/message_stream.py` | `publish_threadsafe()` |
| `freqtrade/enums/rpcmessagetype.py` | `TRADE_STATUS` message type |
| `freqtrade/rpc/rpc_types.py` | `RPCTradeStatusMsg` |
| `freqtrade/rpc/webhook.py` | Ignore `TRADE_STATUS` webhooks |

### This repo (deployment layer)

| File | Purpose |
|------|---------|
| `user_data/strategies/topstep_mixin.py` | Forces `leverage: 1.0` — lot-only order sizing |
| `user_data/strategies/ZaratustraV13.py` | Active strategy using `TopstepMixin` |
| `user_data/strategies/indicators.py` | Shared indicators for strategies |
| `config.example.json` | ProjectX / Topstep config template |
| `scripts/list_accounts.py` | List Topstep accounts via `ProjectXClient` |
| `scripts/list-accounts.sh` | Shell wrapper (local Freqtrade or Docker exec) |
| `scripts/risk-status.sh` | Queries `GET /api/v1/topstep_risk` |
| `scripts/install-freqtrade.sh` | Local dev: `pip install freqtrade` + ProjectX overlay |
| `scripts/install-projectx.sh` | Apply overlay to existing Freqtrade install |
| `Dockerfile` / `docker-compose.yml` | Extends `freqtradeorg/freqtrade:latest` |
| `docs/configuration.md` | Config reference |
| `docs/development.md` | Dev and Docker guide |
| `docs/topstep-integration.md` | This file |

### Runtime state (gitignored)

| Path | Purpose |
|------|---------|
| `config.json` | Live credentials, account ID, pairs, risk rules |
| `user_data/freqtrade.sqlite` | Freqtrade trades and orders |
| `user_data/topstep_risk_<account_id>.json` | Risk tracker state (session P&L, peak balance) |

---

## TopstepX API

| Endpoint | Purpose |
|----------|---------|
| `POST /api/Auth/loginKey` | Authenticate (`userName`, `apiKey`) |
| `POST /api/Account/search` | List accounts |
| `POST /api/Contract/available` | Tradable contracts |
| `POST /api/History/retrieveBars` | OHLCV |
| `POST /api/Order/place` | Place order (`size` = lots, `side`: 0=BUY, 1=SELL) |
| `POST /api/Position/searchOpen` | Open positions |

Implemented in `projectx_client.py`; consumed by `projectx.py`.

### Real-time market data (WebSocket)

TopstepX streams live quotes and trades over **SignalR** (not CCXT):

| Hub | URL | Purpose |
|-----|-----|---------|
| Market | `https://rtc.topstepx.com/hubs/market` | `GatewayQuote`, `GatewayTrade` |
| User | `https://rtc.topstepx.com/hubs/user` | Account, order, position updates (REST polling today) |

When `exchange.enable_ws` is `true` (default), the bot:

1. Seeds OHLCV from `retrieveBars` (REST)
2. Subscribes via `SubscribeContractQuotes` + `SubscribeContractTrades`
3. Updates the **current candle** on every live tick (no REST polling delay)
4. Pushes **live open-trade P&L** to FreqUI over `/api/v1/message/ws` (`trade_status` events, ~150ms throttle)

FreqUI still polls `/status` every 5s as a fallback, but RP&L updates appear on each ProjectX quote when the websocket connection is active.

Config:

```json
"exchange": {
  "market_hub": "https://rtc.topstepx.com/hubs/market",
  "enable_ws": true
}
```

Set `"enable_ws": false` to fall back to REST-only candles.

---

## Account types

| Type | Detection | `live_data` |
|------|-----------|-------------|
| Trading Combine | name contains `TC`, simulated | `false` |
| Express Funded | simulated, not combine | `false` |
| Live Funded | not simulated | `true` |

Logic in `topstep_accounts.py`. Plan limits (max mini/micro contracts, max loss) are derived from account name and balance.

---

## Lot sizing and P&L

Configured in `config.json`, enforced in `projectx.py` and `topstep_mixin.py`:

- **`stake_is_lots: true`** — `stake_amount` is contract lot count (1, 2, 3…)
- **`contractSize`** = `tickValue / tickSize` from Topstep contract metadata
- Example **MBT**: tickSize=5, tickValue=$0.50 → **$0.10 per index point per lot**
- Freqtrade **leverage = 1.0** — Topstep applies account margin on the exchange
- **`tradable_balance_ratio: 1.0`** — FreqUI balance matches TopstepX BAL

---

## Risk rules

Implemented in `topstep_risk.py`, checked from `freqtradebot.py`, exposed via `api_topstep.py`.

Session P&L resets at **17:00 US/Central** (CME-style daily boundary).

State file: `user_data/topstep_risk_<account_id>.json`

| Trigger | Default action |
|---------|----------------|
| Daily loss (× `loss_ratio`) | Block entries + auto pause |
| Trailing max loss (× `loss_ratio`) | Block entries + auto stop |
| Consistency (combine) | Warning or block (configurable) |
| Max contracts exceeded | Block order (`topstep_accounts.check_order_allowed`) |

Check status:

```bash
./scripts/risk-status.sh
curl -u admin:admin http://localhost:8080/api/v1/topstep_risk
```

---

## Account workflow

1. `./scripts/list-accounts.sh` — uses `projectx_client.py` + `topstep_accounts.py`
2. Set `account_id` and `account_filter` in `config.json`
3. Test with `dry_run: true`
4. Set `dry_run: false` for live TopstepX orders
5. After passing combine → switch `account_filter` to `express_funded`

---

## Modifying the integration

1. Edit overlay files under `projectx/overlay/freqtrade/`, or patch logic in `projectx/install.py`
2. Rebuild the container:

```bash
docker compose up -d --build
```

**Update upstream Freqtrade** (pull latest official image):

```bash
docker compose build --pull --no-cache
docker compose up -d
```

For local dev without Docker:

```bash
./scripts/install-freqtrade.sh
freqtrade trade -c config.json --userdir user_data
```
