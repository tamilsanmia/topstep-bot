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

## Source files

| File | Role |
|------|------|
| `freqtrade/freqtrade/exchange/projectx.py` | Freqtrade exchange class: OHLCV, orders, balances, positions, lot sizing |
| `freqtrade/freqtrade/exchange/projectx_client.py` | HTTP client: auth, accounts, bars, orders, positions |
| `freqtrade/freqtrade/exchange/topstep_accounts.py` | Combine / express / live detection, $50K/$100K/$150K limits |
| `freqtrade/freqtrade/exchange/topstep_risk.py` | Daily loss, max loss, consistency; auto pause/stop |
| `freqtrade/freqtrade/rpc/api_server/api_topstep.py` | `GET /api/v1/topstep_risk` |
| `freqtrade/freqtrade/freqtradebot.py` | Calls `check_topstep_risk()` each loop |

## TopstepX API

| Endpoint | Purpose |
|----------|---------|
| `POST /api/Auth/loginKey` | Authenticate (`userName`, `apiKey`) |
| `POST /api/Account/search` | List accounts |
| `POST /api/Contract/available` | Tradable contracts |
| `POST /api/History/retrieveBars` | OHLCV |
| `POST /api/Order/place` | Place order (`size` = lots, `side`: 0=BUY, 1=SELL) |
| `POST /api/Position/searchOpen` | Open positions |

## Account types

| Type | Detection | `live_data` |
|------|-----------|-------------|
| Trading Combine | name contains `TC`, simulated | `false` |
| Express Funded | simulated, not combine | `false` |
| Live Funded | not simulated | `true` |

Plan limits (max mini/micro contracts, max loss) are applied from account name and balance.

## Lot sizing & P&L

- **`stake_is_lots: true`** — config `stake_amount` is contract count
- **`contractSize`** = `tickValue / tickSize` from Topstep contract metadata
- Example **MBT**: tickSize=5, tickValue=$0.50 → $0.10 per index point per lot
- Freqtrade **leverage stays 1.0** — Topstep applies margin on the exchange

## Risk rules

Session P&L resets at **17:00 US/Central** (CME-style daily boundary).

Risk state: `user_data/topstep_risk_<account_id>.json`

| Trigger | Default action |
|---------|----------------|
| Daily loss (× `loss_ratio`) | Block entries + auto pause |
| Trailing max loss (× `loss_ratio`) | Block entries + auto stop |
| Consistency (combine) | Warning or block (configurable) |

## Account workflow

1. `./scripts/list-accounts.sh`
2. Set `account_id` and `account_filter` in `config.json`
3. Test with `dry_run: true`
4. Set `dry_run: false` for live TopstepX orders
5. After passing combine → switch to `express_funded`
