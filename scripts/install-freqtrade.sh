#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

python3 -m pip install --upgrade "freqtrade"
freqtrade install-ui
FT_ROOT="$(python3 -c 'import freqtrade, os; print(os.path.dirname(os.path.dirname(freqtrade.__file__)))')"
FT_ROOT="$FT_ROOT" "$ROOT/scripts/install-projectx.sh"
echo "Installed freqtrade from PyPI/image source and applied ProjectX overlay"
