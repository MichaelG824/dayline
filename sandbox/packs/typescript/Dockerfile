# TypeScript language pack. The runner builds this image itself (tagged with
# a hash of this folder) and starts one locked-down container per session:
# no network, read-only root filesystem, /workspace on its own volume.
FROM node:22-bookworm-slim

ENV NPM_CONFIG_UPDATE_NOTIFIER=false \
    NPM_CONFIG_FUND=false \
    NPM_CONFIG_AUDIT=false

WORKDIR /opt/pack
COPY package.json package-lock.json ./
RUN npm ci

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
