#!/bin/sh
set -e
cd "$(dirname "$0")/.."

API_URL="${TOPSTEP_API_URL:-http://127.0.0.1:8080/api/v1/topstep_risk}"
API_USER="${FREQTRADE_API_USER:-admin}"
API_PASS="${FREQTRADE_API_PASS:-admin}"

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required" >&2
  exit 1
fi

curl -fsS -u "${API_USER}:${API_PASS}" "$API_URL" | python3 -m json.tool
