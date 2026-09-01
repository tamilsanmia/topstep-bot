# Topstep + Freqtrade

Trade **TopstepX / ProjectX** CME futures with a vendored **[Freqtrade](https://www.freqtrade.io/)** fork and a custom **`projectx`** exchange adapter.

Everything lives in **one repository**:

```
topstep-bot/
├── freqtrade/          # Freqtrade engine + ProjectX / Topstep patches
├── user_data/          # Strategies, SQLite DB, risk state
├── config.json         # Your settings (copy from config.example.json)
├── docker-compose.yml
└── docs/               # Detailed guides
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

## Helper scripts

```bash
./scripts/list-accounts.sh     # Topstep accounts (needs Freqtrade install or running container)
./scripts/risk-status.sh       # Risk JSON from running bot
./scripts/install-freqtrade.sh   # Local dev: pip install -e ./freqtrade
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
| [docs/topstep-integration.md](docs/topstep-integration.md) | **Full file map** (11 engine patches + scripts), API, risk rules |

TopstepX integration spans **`freqtrade/freqtrade/exchange/projectx*.py`**, **`topstep_*.py`**, **`api_topstep.py`**, plus `user_data/strategies/topstep_mixin.py`. See [docs/topstep-integration.md](docs/topstep-integration.md) for the complete list.

## Disclaimer

Automated trading carries risk. Test on combine accounts before live funded trading.
