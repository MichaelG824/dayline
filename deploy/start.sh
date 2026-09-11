#!/bin/sh
set -eu

uvicorn dayline.api.main:app --host 127.0.0.1 --port 8000 --timeout-keep-alive 300 &

cd /app/web
HOSTNAME=127.0.0.1 PORT=3000 node server.js &

exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
