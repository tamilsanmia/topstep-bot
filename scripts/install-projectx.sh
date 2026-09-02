#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECTX_DIR="${PROJECTX_DIR:-$ROOT/projectx}"

if [[ ! -f "$PROJECTX_DIR/install.py" && -f "/tmp/projectx/install.py" ]]; then
  PROJECTX_DIR="/tmp/projectx"
fi

FT_ROOT="${FT_ROOT:-}"

if [[ -n "$FT_ROOT" ]]; then
  python3 "$PROJECTX_DIR/install.py" --ft-root "$FT_ROOT" --overlay "$PROJECTX_DIR/overlay"
else
  python3 "$PROJECTX_DIR/install.py" --overlay "$PROJECTX_DIR/overlay"
fi

if [[ -n "$FT_ROOT" ]]; then
  UI_ASSETS="$FT_ROOT/freqtrade/rpc/api_server/ui/installed/assets"
else
  UI_ASSETS="$(python3 -c 'import freqtrade, os; print(os.path.join(os.path.dirname(freqtrade.__file__), "rpc/api_server/ui/installed/assets"))')"
fi

PATCH_UI="${PATCH_UI:-$ROOT/scripts/patch-frequi-trade-ws.sh}"
if [[ ! -f "$PATCH_UI" && -f "/tmp/patch-frequi-trade-ws.sh" ]]; then
  PATCH_UI="/tmp/patch-frequi-trade-ws.sh"
fi

if [[ -f "$PATCH_UI" ]]; then
  chmod +x "$PATCH_UI" 2>/dev/null || true
  "$PATCH_UI" "$UI_ASSETS"
fi

echo "ProjectX integration installed."
