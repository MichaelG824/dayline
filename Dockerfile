# Single image: Next.js + FastAPI behind Caddy so the public origin is one URL
# (cookies stay simple) and the host can scale to zero.

FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=caddy:2 /usr/bin/caddy /usr/bin/caddy
COPY --from=node:22-bookworm-slim /usr/local/bin/node /usr/local/bin/node

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e '.[google]'

COPY --from=web /web/.next/standalone ./web
COPY --from=web /web/.next/static ./web/.next/static

COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY deploy/start.sh /app/start.sh
RUN chmod +x /app/start.sh

ENV PYTHONUNBUFFERED=1
ENV PORT=8080
ENV HOSTNAME=0.0.0.0
ENV API_INTERNAL_URL=http://127.0.0.1:8000

EXPOSE 8080
CMD ["/app/start.sh"]
