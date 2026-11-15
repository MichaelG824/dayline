# Rails pack. The runner builds this image itself (tagged with a hash of this
# folder) and starts one locked-down container per session: no network,
# read-only root filesystem, /workspace on its own volume.
FROM ruby:3.3-slim-bookworm AS gems

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libyaml-dev pkg-config \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/pack
COPY Gemfile Gemfile.lock ./
RUN bundle config set --global frozen true \
    && bundle install --jobs 4 \
    && rm -rf /usr/local/bundle/cache

FROM ruby:3.3-slim-bookworm

# socat carries the runner's preview traffic into the sandbox (it has no
# network); sqlite3 is the database CLI (`bin/rails dbconsole`).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libyaml-0-2 socat sqlite3 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=gems /usr/local/bundle /usr/local/bundle
COPY Gemfile Gemfile.lock /opt/pack/
COPY lib /opt/pack/lib

# uid 1000 owns /workspace so a fresh volume mounted there inherits it.
RUN useradd --uid 1000 --no-create-home --shell /bin/bash candidate \
    && mkdir /workspace \
    && chown candidate:candidate /workspace

# No network: Bundler must only ever use the gems installed above.
ENV BUNDLE_DISABLE_VERSION_CHECK=true \
    BUNDLE_IGNORE_FUNDING_REQUESTS=true

WORKDIR /workspace
USER 1000:1000
