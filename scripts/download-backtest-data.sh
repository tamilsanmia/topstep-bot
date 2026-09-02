#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

IMAGE="${TOPSTEP_IMAGE:-topstep-bot:latest}"
CONFIG_FILE="${CONFIG:-user_data/config-futures-backtest.json}"
USERDIR="${USERDIR:-user_data}"
CONFIG_BASENAME="$(basename "$CONFIG_FILE")"
CONTAINER_CONFIG="/freqtrade/user_data/$CONFIG_BASENAME"

# TopstepX sim history depth is limited — intraday ~30-90d, higher TFs longer.
intraday_tfs=("1m" "3m" "5m" "15m" "30m")
higher_tfs=("1h" "4h" "1d" "1w")

END_DATE="${END_DATE:-$(date -u +%Y%m%d)}"
INTRADAY_START="${INTRADAY_START:-$(date -u -d '90 days ago' +%Y%m%d 2>/dev/null || date -u -v-90d +%Y%m%d)}"
YEAR_START="${YEAR_START:-$(date -u -d '365 days ago' +%Y%m%d 2>/dev/null || date -u -v-365d +%Y%m%d)}"
INTRADAY_RANGE="${INTRADAY_START}-${END_DATE}"
YEAR_RANGE="${YEAR_START}-${END_DATE}"

PAIRS="${PAIRS:-MBT/USD MET/USD MNQ/USD MES/USD MGC/USD}"

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "Missing $CONFIG_FILE — copy exchange.username/api_key from config.json first." >&2
  exit 1
fi

if grep -q '"username": ""' "$CONFIG_FILE" 2>/dev/null; then
  echo "Set exchange.username and exchange.api_key in $CONFIG_FILE (copy from config.json)." >&2
  exit 1
fi

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Building $IMAGE ..."
  docker compose build
fi

download_tf() {
  local tf="$1"
  local range="$2"
  echo "=== timeframe: $tf | range: $range ==="
  # shellcheck disable=SC2086
  docker run --rm \
    --entrypoint freqtrade \
    -v "$PWD/$USERDIR:/freqtrade/user_data" \
    "$IMAGE" \
    download-data \
    --config "$CONTAINER_CONFIG" \
    --userdir /freqtrade/user_data \
    --trading-mode futures \
    --candle-types futures \
    --timeframes "$tf" \
    --timerange "$range" \
    -p $PAIRS
}

echo "Downloading ProjectX backtest data"
echo "Pairs: $PAIRS"
echo "Intraday ($INTRADAY_RANGE): ${intraday_tfs[*]}"
echo "Higher TF ($YEAR_RANGE): ${higher_tfs[*]}"
echo "Note: TopstepX may not store a full year of 1m/5m sim bars — you get whatever the API returns."
echo

for tf in "${intraday_tfs[@]}"; do
  download_tf "$tf" "$INTRADAY_RANGE"
done

for tf in "${higher_tfs[@]}"; do
  download_tf "$tf" "$YEAR_RANGE"
done

echo
echo "Done. Data directory: $USERDIR/data/projectx/"
docker run --rm \
  --entrypoint freqtrade \
  -v "$PWD/$USERDIR:/freqtrade/user_data" \
  "$IMAGE" \
  list-data \
  --config "$CONTAINER_CONFIG" \
  --userdir /freqtrade/user_data
