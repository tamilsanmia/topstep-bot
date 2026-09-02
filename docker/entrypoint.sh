#!/bin/sh
set -e

cd /freqtrade

if [ ! -f /freqtrade/config.json ]; then
  cp /freqtrade/config.example.json /freqtrade/config.json
  echo "Created /freqtrade/config.json from config.example.json"
fi

exec freqtrade "$@" -c /freqtrade/config.json --userdir /freqtrade/user_data
