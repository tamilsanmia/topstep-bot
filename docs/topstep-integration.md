# Topstep integration

This project uses a **vendored Freqtrade fork** with a custom **`projectx`** exchange for TopstepX.

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

All TopstepX-related code lives in **`freqtrade/freqtrade/`** (engine patches) plus this repo’s config, strategies, and scripts.

### Core Freqtrade patches

| File | Purpose |
|------|---------|
| `freqtrade/freqtrade/exchange/projectx.py` | **ProjectX exchange adapter** — OHLCV, orders, balances, positions, lot sizing, P&L (`contractSize`), risk hooks |
| `freqtrade/freqtrade/exchange/projectx_client.py` | **TopstepX HTTP client** — auth, accounts, contracts, bars, orders, positions |
| `freqtrade/freqtrade/exchange/topstep_accounts.py` | Account types (combine / express / live), plan limits, account selection |
| `freqtrade/freqtrade/exchange/topstep_risk.py` | Daily loss, max loss, consistency tracking; auto pause/stop |
| `freqtrade/freqtrade/rpc/api_server/api_topstep.py` | **`GET /api/v1/topstep_risk`** REST endpoint |
| `freqtrade/freqtrade/freqtradebot.py` | Calls `check_topstep_risk()` each bot loop (~lines 337–338) |

### Wiring and registration

| File | Change |
|------|--------|
| `freqtrade/freqtrade/exchange/__init__.py` | Exports `Projectx` exchange class |
| `freqtrade/freqtrade/exchange/common.py` | Registers `"projectx"` as supported exchange |
| `freqtrade/freqtrade/exchange/check_exchange.py` | ProjectX validation / startup message |
| `freqtrade/freqtrade/exchange/exchange_utils.py` | ProjectX-specific exchange utilities |
| `freqtrade/freqtrade/rpc/api_server/webserver.py` | Mounts `api_topstep` router on the API server |

**Total engine patches:** 11 Python files (6 core + 5 wiring).

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
| `scripts/install-freqtrade.sh` | Local dev: `pip install -e ./freqtrade` |
| `Dockerfile` / `docker-compose.yml` | Container build and run |
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

1. Edit files under `freqtrade/freqtrade/exchange/` or `freqtrade/freqtrade/rpc/api_server/api_topstep.py`
2. Rebuild the container:

```bash
docker compose up -d --build
```

For local dev without Docker:

```bash
./scripts/install-freqtrade.sh
freqtrade trade -c config.json --userdir user_data
```
