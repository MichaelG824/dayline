# Next.js + NestJS pack. The runner builds this image itself (tagged with a
# hash of this folder) and starts one locked-down container per session:
# no network, read-only root filesystem, /workspace on its own volume.
FROM node:22-bookworm-slim

ENV NPM_CONFIG_UPDATE_NOTIFIER=false \
    NPM_CONFIG_FUND=false \
    NPM_CONFIG_AUDIT=false \
    NEXT_TELEMETRY_DISABLED=1

# socat carries the runner's preview traffic into the sandbox (it has no network).
RUN apt-get update \
    && apt-get install -y --no-install-recommends socat \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/pack
COPY package.json package-lock.json ./
# The root filesystem is read-only at run time, so Vite writes its bundled
# config (node_modules/.vite-temp) and Vitest its module cache to /tmp
# instead. @swc/core stays on 1.16.2: later releases unpack their native
# addon on first load, which needs a writable, executable folder (and /tmp
# is noexec).
RUN npm ci \
    && ln -s /tmp node_modules/.vite-temp \
    && ln -s /tmp node_modules/.vitest-cache
COPY hidden.vitest.config.mjs hidden.vitest.setup.mjs ./

# uid 1000 (the image's "node" user, renamed to match every other pack) owns
# /workspace, so a fresh volume mounted there inherits it. Dependencies stay
# in the image; the workspace links to them.
RUN usermod --login candidate node \
    && groupmod --new-name candidate node \
    && mkdir /workspace \
    && ln -s /opt/pack/node_modules /workspace/node_modules \
    && chown -h candidate:candidate /workspace /workspace/node_modules

ENV PATH=/opt/pack/node_modules/.bin:$PATH
WORKDIR /workspace
USER 1000:1000
