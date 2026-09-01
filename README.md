# Topstep Bot

Python trading bot for **Topstep / ProjectX** accounts, inspired by [Freqtrade](https://www.freqtrade.io/) strategy structure. Write strategies as Python classes with `populate_indicators`, `populate_entry_trend`, and `populate_exit_trend`.

## Features

- Direct TopstepX gateway API (no dashboard proxy required)
- Freqtrade-like `IStrategy` interface
- Dry-run mode by default
- Sample EMA crossover strategy for MNQ
- CLI: `trade`, `test-connection`, `list-symbols`
- Freqtrade-compatible REST API + web dashboard on port 8080

## Quick start

### Docker (recommended)

```bash
cd /root/topstep-bot
cp .env.example .env
cp config.example.json config.json
# Edit .env with PROJECTX_USERNAME and PROJECTX_API_KEY

docker compose up -d --build
# Dashboard: http://localhost:8080/trade  (login: admin / admin)
docker compose logs -f
```

Live trading (disables dry-run):

```bash
docker compose -f docker-compose.yml -f docker-compose.live.yml up -d --build
```

Stop:

```bash
docker compose down
```

### Local Python

```bash
cd /root/topstep-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
cp config.example.json config.json
# Edit .env with PROJECTX_USERNAME and PROJECTX_API_KEY from TopstepX Settings -> API

python -m topstepbot test-connection
python -m topstepbot list-symbols
python -m topstepbot trade --strategy SampleStrategy
# Dashboard: http://localhost:8080/trade  (login: admin / admin)
```

## Web dashboard (Freqtrade-style)

Enable the API server in `config.json`:

```json
{
  "bot_name": "topstepbot",
  "initial_state": "running",
  "force_entry_enable": false,
  "internals": {
    "process_throttle_secs": 5
  },
  "api_server": {
    "enabled": true,
    "listen_ip_address": "0.0.0.0",
    "listen_port": 8080,
    "verbosity": "error",
    "enable_openapi": false,
    "jwt_secret_key": "your-random-secret",
    "ws_token": "your-ws-token",
    "CORS_origins": [],
    "username": "admin",
    "password": "admin"
  }
}
```

When you run `python -m topstepbot trade`, the dashboard starts automatically:

- **Dashboard:** http://localhost:8080/trade
- **API ping:** http://localhost:8080/api/v1/ping
- **OpenAPI docs:** http://localhost:8080/docs (if `enable_openapi: true`)

REST endpoints match Freqtrade: `/status`, `/trades`, `/profit`, `/balance`, `/start`, `/stop`, `/pause`, `/stopbuy`, `/forceenter`, `/forceexit`, and more.

## Configuration

**`.env`** — credentials and gateway hosts:

| Variable | Description |
|----------|-------------|
| `PROJECTX_USERNAME` | TopstepX username |
| `PROJECTX_API_KEY` | API key from TopstepX |
| `PROJECTX_LIVE_DATA` | `false` for combine/sim, `true` for funded live |

**`config.json`** — bot behavior:

| Key | Default | Description |
|-----|---------|-------------|
| `dry_run` | `true` | Log orders without sending |
| `pair_whitelist` | `["MNQ"]` | Symbols to trade (Freqtrade-style), e.g. `MNQ`, `MES`, `ES`, `NQ` |
| `pairlists` | `[{"method": "StaticPairList"}]` | Pairlist plugins; `StaticPairList` uses `pair_whitelist` |
| `contract_root` | `MNQ` | Legacy single-symbol alias (used if `pair_whitelist` is omitted) |
| `timeframe` | `5m` | Bar interval |
| `stake_amount` | `1` | Contract size per order |
| `strategy` | `SampleStrategy` | Module name in `user_data/strategies/` |

### Freqtrade-style pairs config

```json
{
  "pair_whitelist": ["MNQ", "MES", "NQ"],
  "pairlists": [
    {"method": "StaticPairList"}
  ]
}
```

List all Topstep symbols:

```bash
python -m topstepbot list-symbols
```

Common symbols: `ES`, `MES`, `NQ`, `MNQ`, `RTY`, `M2K`, `YM`, `MYM`, `CL`, `MCL`, `GC`, `MGC`, `SI`, `NG`, `6E`, `6B`, `MBT`, `MET`, and treasuries `ZT`, `ZF`, `ZN`, `ZB`.

## Writing a strategy

Create `user_data/strategies/MyStrategy.py`:

```python
import pandas as pd
from topstepbot.strategy.interface import IStrategy

class MyStrategy(IStrategy):
    timeframe = "5m"
    startup_candle_count = 200

    def populate_indicators(self, dataframe, metadata):
        df = dataframe.copy()
        df["rsi"] = ...  # your indicators
        return df

    def populate_entry_trend(self, dataframe, metadata):
        df = dataframe.copy()
        df["enter_long"] = df["rsi"] < 30
        df["enter_short"] = df["rsi"] > 70
        return df

    def populate_exit_trend(self, dataframe, metadata):
        df = dataframe.copy()
        df["exit_long"] = df["rsi"] > 55
        df["exit_short"] = df["rsi"] < 45
        return df
```

Run it:

```bash
python -m topstepbot trade --strategy MyStrategy
```

## Live trading

1. Set `"dry_run": false` in `config.json` **or** pass `--live`
2. Confirm account and contract in logs
3. Start with `stake_amount: 1`

```bash
python -m topstepbot trade --strategy SampleStrategy --live
```

## Project layout

```
topstep-bot/
├── config.example.json
├── requirements.txt
├── topstepbot/
│   ├── cli.py              # CLI entry
│   ├── config.py           # Config loader
│   ├── engine/bot.py       # Main trading loop
│   ├── rpc/                # REST API + dashboard server
│   ├── web/static/         # Dashboard UI (/trade)
│   ├── exchange/projectx.py # TopstepX API client
│   ├── data/history.py     # Bars -> pandas
│   └── strategy/
│       ├── interface.py    # IStrategy base class
│       └── loader.py       # Dynamic strategy import
└── user_data/strategies/
    └── SampleStrategy.py
```

## API notes

This bot talks directly to the TopstepX gateway (`https://api.topstepx.com`), same as the ProjectX integration in the dashboard. Auth uses `POST /api/Auth/loginKey`. Orders use `POST /api/Order/place` with side `0=BUY`, `1=SELL`.

## Disclaimer

Automated trading carries risk. Test thoroughly in dry-run and combine accounts before live use.
