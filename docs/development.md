# Development guide

## Repository layout

```
topstep-bot/
├── projectx/
│   ├── overlay/freqtrade/          # ProjectX exchange files (copied at build)
│   └── install.py                  # Patches official Freqtrade in-place
├── user_data/strategies/
│   ├── topstep_mixin.py            # leverage: 1.0 for lot sizing
│   └── ZaratustraV13.py            # Active strategy
├── scripts/                        # list-accounts, install-projectx, FreqUI patch
├── docker-compose.yml
├── Dockerfile                      # FROM freqtradeorg/freqtrade:latest
└── config.json                     # Local config (gitignored)
```

Full file list: [docs/topstep-integration.md](topstep-integration.md#integration-file-map)

## Docker (recommended)

Build and run from the repo root:

```bash
docker compose up -d --build
docker compose logs -f
docker compose restart topstepbot
```

The image extends **`freqtradeorg/freqtrade:latest`**. ProjectX is installed at build time via `./scripts/install-projectx.sh`.

**Update Freqtrade** (new upstream release):

```bash
docker compose build --pull --no-cache
docker compose up -d
```

Pin a specific tag with `FREQTRADE_IMAGE=freqtradeorg/freqtrade:2025.1 docker compose build --pull`.

Volumes:

- `./config.json` → `/freqtrade/config.json`
- `./user_data` → `/freqtrade/user_data`

## Local development

Install official Freqtrade, then apply the ProjectX overlay:

```bash
./scripts/install-freqtrade.sh
# equivalent: pip install freqtrade && ./scripts/install-projectx.sh
```

Run the bot:

```bash
cp config.example.json config.json   # if needed
freqtrade trade -c config.json --userdir user_data
```

## Writing strategies

Use Freqtrade `IStrategy` plus **`TopstepMixin`** (forces leverage 1.0):

```python
from freqtrade.strategy import IStrategy
from topstep_mixin import TopstepMixin

class MyStrategy(TopstepMixin, IStrategy):
    timeframe = "5m"
    startup_candle_count = 200

    def populate_indicators(self, dataframe, metadata):
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        dataframe["enter_long"] = False
        dataframe["enter_short"] = False
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        dataframe["exit_long"] = False
        dataframe["exit_short"] = False
        return dataframe
```

Reference: `user_data/strategies/ZaratustraV13.py`

## Helper scripts

| Script | Purpose |
|--------|---------|
| `./scripts/install-freqtrade.sh` | `pip install freqtrade` + ProjectX overlay + FreqUI |
| `./scripts/install-projectx.sh` | Apply overlay to existing Freqtrade (`FT_ROOT` optional) |
| `./scripts/list-accounts.sh` | List TopstepX accounts |
| `./scripts/risk-status.sh` | Query `/api/v1/topstep_risk` |

`list-accounts.sh` uses local Freqtrade if installed, otherwise runs inside the Docker container.

## Modifying the exchange adapter

Edit files under `projectx/overlay/freqtrade/`, or core patch logic in `projectx/install.py`, then rebuild:

```bash
docker compose up -d --build
```

Primary overlay files:

| File | When to edit |
|------|----------------|
| `projectx/overlay/freqtrade/exchange/projectx.py` | Orders, balances, lot sizing, P&L |
| `projectx/overlay/freqtrade/exchange/projectx_client.py` | TopstepX API calls |
| `projectx/overlay/freqtrade/exchange/topstep_accounts.py` | Account types, contract limits |
| `projectx/overlay/freqtrade/exchange/topstep_risk.py` | Daily/max loss, consistency rules |
| `projectx/overlay/freqtrade/rpc/api_server/api_topstep.py` | Risk REST endpoint |

Core Freqtrade hooks (patched by `projectx/install.py`): `freqtradebot.py`, `rpc/rpc.py`, websocket/RPC message types, API server wiring.

Key behaviors in `projectx.py`:

- `stake_is_lots` — `stake_amount` is integer contract lots
- `contractSize = tickValue / tickSize` — correct futures P&L
- `get_max_leverage()` returns `1.0` in lot mode
- Live balance from Topstep account API

## Backtest / webserver

1. Copy Topstep credentials into `user_data/config-futures-backtest.json` (`exchange.username`, `exchange.api_key`, optional `"account_id": "26448079"` as a **string**).

2. Download OHLCV from TopstepX:

```bash
./scripts/download-backtest-data.sh
# optional: START_DATE=20250101 END_DATE=20250601 ./scripts/download-backtest-data.sh
```

3. Run a CLI backtest:

```bash
./scripts/run-backtest.sh
# optional: TIMERANGE=20250101-20250601 STRATEGY=ZaratustraV13 ./scripts/run-backtest.sh
```

4. Or use FreqUI backtest webserver (port **8081** so live bot can keep 8080):

```bash
docker compose -f docker-compose-webserver.yml up -d --build
# http://localhost:8081
```

Data is stored under `user_data/data/projectx/`. Topstep history is limited per API request; very long timeranges may need multiple downloads.


| Message | Meaning |
|---------|---------|
| `Missing data fillup for …` | Normal during CME closed hours |
| `lot mode (no Freqtrade leverage)` | Expected — lot-based sizing |
| `Dry run is enabled` | No real TopstepX orders |
| `Using Topstep account …` | Account resolved from config |
