# Development guide

## Repository layout

```
topstep-bot/
├── freqtrade/                    # Vendored Freqtrade + ProjectX patches
│   └── freqtrade/exchange/
│       ├── projectx.py           # Exchange adapter
│       ├── projectx_client.py    # TopstepX HTTP client
│       ├── topstep_accounts.py   # Account types & plan limits
│       └── topstep_risk.py       # Risk guardrails
├── user_data/strategies/         # Your Freqtrade strategies
├── scripts/                      # Helper scripts
├── docker-compose.yml
├── Dockerfile
└── config.json                   # Local config (gitignored)
```

## Docker (recommended)

Build and run from the repo root:

```bash
docker compose up -d --build
docker compose logs -f
docker compose restart topstepbot
```

Volumes:

- `./config.json` → `/app/config.json`
- `./user_data` → `/app/user_data`

## Local development

Install the vendored Freqtrade fork in editable mode:

```bash
./scripts/install-freqtrade.sh
# equivalent: pip install -e ./freqtrade && freqtrade install-ui
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
| `./scripts/install-freqtrade.sh` | `pip install -e ./freqtrade` + FreqUI |
| `./scripts/list-accounts.sh` | List TopstepX accounts |
| `./scripts/risk-status.sh` | Query `/api/v1/topstep_risk` |

`list-accounts.sh` uses local Freqtrade if installed, otherwise runs inside the Docker container.

## Modifying the exchange adapter

Edit files under **`freqtrade/freqtrade/exchange/`**, then rebuild:

```bash
docker compose up -d --build
```

Key behaviors in `projectx.py`:

- `stake_is_lots` — `stake_amount` is integer contract lots
- `contractSize = tickValue / tickSize` — correct futures P&L
- `get_max_leverage()` returns `1.0` in lot mode
- Live balance from Topstep account API

## Log messages

| Message | Meaning |
|---------|---------|
| `Missing data fillup for …` | Normal during CME closed hours |
| `lot mode (no Freqtrade leverage)` | Expected — lot-based sizing |
| `Dry run is enabled` | No real TopstepX orders |
| `Using Topstep account …` | Account resolved from config |
