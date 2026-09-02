# Configuration reference

All bot settings are in **`config.json`**. Copy from **`config.example.json`**.

## Credentials

Generate an API key in TopstepX: **Settings → API → API Key**.

```json
{
  "exchange": {
    "name": "projectx",
    "username": "your@email.com",
    "api_key": "your_api_key",
    "api_base": "https://api.topstepx.com",
    "account_id": 26448079,
    "account_filter": "combine",
    "market_hub": "https://rtc.topstepx.com/hubs/market",
    "enable_ws": true,
    "live_data": "auto"
  }
}
```

| Key | Description |
|-----|-------------|
| `account_id` | Pin one account (from `./scripts/list-accounts.sh`) |
| `account_filter` | `combine`, `express_funded`, `live_funded`, or `any` |
| `live_data` | `"auto"` picks live/sim data from account type |
| `market_hub` | SignalR market hub URL for live quotes/trades |
| `enable_ws` | `true` = live websocket candles; `false` = REST only |

## Order sizing (lots)

Topstep applies **account leverage on the exchange**. Freqtrade must **not** use leverage scaling.

```json
{
  "stake_amount": 1,
  "exchange": {
    "stake_is_lots": true
  }
}
```

| `stake_amount` | Order size |
|----------------|------------|
| `1` | 1 contract lot |
| `2` | 2 lots |
| `3` | 3 lots |

Do **not** set `exchange.leverage`. The strategy mixin forces `leverage: 1.0`.

## Balance display

```json
"tradable_balance_ratio": 1.0
```

Use **`1.0`** so FreqUI balance matches TopstepX **BAL**. The default Freqtrade value `0.99` hides 1% of equity.

## Trading pairs

```json
"pair_whitelist": ["MBT/USD", "MNQ/USD", "MET/USD"],
"pairlists": [{ "method": "StaticPairList" }]
```

Common roots: `ES`, `MES`, `NQ`, `MNQ`, `RTY`, `M2K`, `MBT`, `MET`, `CL`, `GC`, …

## Dry run vs live

| `dry_run` | Behavior |
|-----------|----------|
| `true` | Simulated trades only — nothing sent to TopstepX |
| `false` | Real market orders via TopstepX API |

## Risk guardrails

Enable with `exchange.topstep_rules_enabled: true`.

```json
"topstep_rules": {
  "loss_ratio": 0.8,
  "enforce_max_contracts": true,
  "block_on_daily_loss": true,
  "block_on_max_loss": true,
  "auto_pause_on_daily_loss": true,
  "auto_stop_on_max_loss": true,
  "warn_on_consistency": true,
  "block_on_consistency": false
}
```

| Key | Meaning |
|-----|---------|
| `loss_ratio` | Trigger at fraction of plan limit (0.8 × $1K daily → stop at −$800) |
| `auto_pause_on_daily_loss` | Bot pauses when daily loss trigger hit |
| `auto_stop_on_max_loss` | Bot stops when trailing max-loss floor hit |

State file: `user_data/topstep_risk_<account_id>.json` (see [topstep-integration.md](topstep-integration.md#runtime-state-gitignored))

Check status:

```bash
./scripts/risk-status.sh
curl -u admin:admin http://localhost:8080/api/v1/topstep_risk
```

## Strategy

```json
"strategy": "ZaratustraV13",
"strategy_path": "user_data/strategies"
```

## API server (FreqUI)

```json
"api_server": {
  "enabled": true,
  "listen_ip_address": "0.0.0.0",
  "listen_port": 8080,
  "username": "admin",
  "password": "admin"
}
```

Change default credentials before exposing port 8080 publicly.

## Persistence

| Path | Purpose |
|------|---------|
| `user_data/freqtrade.sqlite` | Trades and orders |
| `user_data/topstep_risk_*.json` | Risk tracker state |

**Reset bot state** (does not close TopstepX positions):

```bash
docker compose stop
rm -f user_data/freqtrade.sqlite user_data/freqtrade.sqlite-* user_data/topstep_risk_*.json
docker compose up -d
```
