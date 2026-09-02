#!/bin/sh
set -e
cd "$(dirname "$0")/.."

if python3 -c "import freqtrade" 2>/dev/null; then
  exec python3 scripts/list_accounts.py "$@"
fi

if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx topstepbot; then
  exec docker exec topstepbot python3 /freqtrade/scripts/list_accounts.py -c /freqtrade/config.json "$@"
fi

echo "Install Freqtrade first: ./scripts/install-freqtrade.sh" >&2
echo "Or start the bot: docker compose up -d" >&2
exit 1
