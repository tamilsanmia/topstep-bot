#!/bin/sh
set -e

cd /app

if [ ! -f /app/config.json ]; then
  cp /app/config.example.json /app/config.json
  echo "Created /app/config.json from config.example.json"
fi

exec freqtrade "$@" -c /app/config.json --userdir /app/user_data
