#!/bin/sh
set -eu

python -m uvicorn dayline.api.main:app --host 127.0.0.1 --port 8000 --timeout-keep-alive 300 &

cd /app/web
HOSTNAME=0.0.0.0 PORT=3000 node server.js &

wait_http() {
  url=$1
  i=0
  while [ "$i" -lt 60 ]; do
    if python -c "import urllib.request; urllib.request.urlopen('$url', timeout=1)" 2>/dev/null; then
      return 0
    fi
    i=$((i + 1))
    sleep 0.5
  done
  echo "timeout waiting for $url" >&2
  return 1
}

wait_http http://127.0.0.1:8000/api/health
wait_http http://127.0.0.1:3000/

exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
