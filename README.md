# Topstep + Freqtrade

Trade **TopstepX / ProjectX** CME futures with the official **[Freqtrade](https://www.freqtrade.io/)** Docker image plus a **ProjectX overlay** (no vendored Freqtrade fork).

```
topstep-bot/
├── projectx/           # ProjectX exchange + Topstep patches (applied at build)
├── user_data/          # Strategies, SQLite DB, risk state
├── config.json         # Your settings (copy from config.example.json)
├── docker-compose.yml
└── docs/
```

## Quick start

```bash
cp config.example.json config.json
# Edit config.json — exchange.username, exchange.api_key, account_id

docker compose up -d --build
```

| URL | Purpose |
|-----|---------|
| http://localhost:8080 | FreqUI (`admin` / `admin` from config) |
| http://localhost:8080/api/v1/topstep_risk | Topstep risk snapshot |

```bash
docker compose logs -f
docker compose restart topstepbot
docker compose down
```

**Live trading:** set `"dry_run": false` in `config.json`, then `docker compose up -d --build`.

## Update Freqtrade

Pull the latest official image and rebuild:

```bash
docker compose build --pull --no-cache
docker compose up -d
```

Or pin a version:

```bash
FREQTRADE_IMAGE=freqtradeorg/freqtrade:2025.1 docker compose build --pull
docker compose up -d
```

## Helper scripts

```bash
./scripts/list-accounts.sh       # Topstep accounts (container or local install)
./scripts/risk-status.sh         # Risk JSON from running bot
./scripts/install-freqtrade.sh   # Local dev: pip install freqtrade + ProjectX overlay
./scripts/install-projectx.sh    # Apply overlay to an existing Freqtrade install
```

## Key settings

| Setting | Value | Notes |
|---------|-------|-------|
| `exchange.name` | `projectx` | TopstepX gateway |
| `exchange.stake_is_lots` | `true` | Orders in contract lots |
| `stake_amount` | `1` | 1 lot per trade (use 2, 3, … for more) |
| `tradable_balance_ratio` | `1.0` | Match TopstepX BAL in FreqUI |
| `dry_run` | `false` | Send real orders to TopstepX |

Pairs use Freqtrade format: `MNQ/USD`, `MBT/USD`, `MET/USD`.

## Documentation

| Guide | Contents |
|-------|----------|
| [docs/configuration.md](docs/configuration.md) | Full `config.json` reference |
| [docs/development.md](docs/development.md) | Local setup, Docker, strategies |
| [docs/topstep-integration.md](docs/topstep-integration.md) | ProjectX overlay, API, risk rules |

## Disclaimer

Automated trading carries risk. Test on combine accounts before live funded trading.
