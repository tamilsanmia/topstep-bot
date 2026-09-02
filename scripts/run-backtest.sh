#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

IMAGE="${TOPSTEP_IMAGE:-topstep-bot:latest}"
CONFIG_FILE="${CONFIG:-user_data/config-futures-backtest.json}"
USERDIR="${USERDIR:-user_data}"
CONFIG_BASENAME="$(basename "$CONFIG_FILE")"
CONTAINER_CONFIG="/freqtrade/user_data/$CONFIG_BASENAME"
STRATEGY="${STRATEGY:-ZaratustraV13}"
TIMERANGE="${TIMERANGE:-20250728-20260801}"
STARTING_BALANCE="${STARTING_BALANCE:-}"
EXTRA_ARGS=()
if [[ -n "$STARTING_BALANCE" ]]; then
  EXTRA_ARGS+=(--starting-balance "$STARTING_BALANCE")
fi

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Building $IMAGE ..."
  docker compose build
fi

docker run --rm \
  --entrypoint freqtrade \
  -v "$PWD/$USERDIR:/freqtrade/user_data" \
  "$IMAGE" \
  backtesting \
  --config "$CONTAINER_CONFIG" \
  --userdir /freqtrade/user_data \
  --strategy "$STRATEGY" \
  --timerange "$TIMERANGE" \
  "${EXTRA_ARGS[@]}"
