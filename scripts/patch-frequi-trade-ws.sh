#!/bin/sh
# Patch installed FreqUI to consume live trade_status websocket updates (ProjectX RP&L).
set -e

UI_ASSETS="${1:-/tmp/freqtrade/freqtrade/rpc/api_server/ui/installed/assets}"

ENUM_FILE=$(grep -rl 'new_candle' "$UI_ASSETS"/*.js 2>/dev/null | head -1)
WRAP_FILE=$(grep -rl 'refreshFrequent' "$UI_ASSETS"/*.js 2>/dev/null | head -1)

if [ -z "$ENUM_FILE" ] || [ -z "$WRAP_FILE" ]; then
  echo "FreqUI patch skipped: installed UI assets not found in $UI_ASSETS" >&2
  exit 0
fi

if ! grep -q 'trade_status' "$ENUM_FILE"; then
  sed -i 's/e.newCandle=`new_candle`,e}/e.newCandle=`new_candle`,e.tradeStatus=`trade_status`,e}/' "$ENUM_FILE"
  echo "Patched FreqUI enum: $ENUM_FILE"
fi

if ! grep -q 'u.tradeStatus' "$WRAP_FILE"; then
  sed -i 's/default:console.log(`Received event ${n.type}`)/case u.tradeStatus:{if(Array.isArray(n.data))for(const r of n.data){const i=T.value.findIndex(e=>e.trade_id===r.trade_id);i>=0?T.value[i]={...T.value[i],...r}:T.value.push(r)}break}default:console.log(`Received event ${n.type}`)/' "$WRAP_FILE"
  sed -i 's/u.entryCancel,u.exitCancel\]/u.entryCancel,u.exitCancel,u.tradeStatus]/' "$WRAP_FILE"
  echo "Patched FreqUI websocket handler: $WRAP_FILE"
fi
