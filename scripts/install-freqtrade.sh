#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FREQTRADE_SRC="${FREQTRADE_SRC:-$ROOT/freqtrade}"

if [[ ! -d "$FREQTRADE_SRC" ]]; then
  echo "freqtrade source not found at $FREQTRADE_SRC" >&2
  exit 1
fi

python3 -m pip install -e "$FREQTRADE_SRC"
freqtrade install-ui
echo "Installed editable freqtrade from $FREQTRADE_SRC and FreqUI"
