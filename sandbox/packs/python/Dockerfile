# Python language pack. The runner builds this image itself (tagged with a
# hash of this folder) and starts one locked-down container per session:
# no network, read-only root filesystem, /workspace on its own volume.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt /opt/pack/requirements.txt
RUN pip install -r /opt/pack/requirements.txt

# uid 1000 owns /workspace so a fresh volume mounted there inherits it.
RUN useradd --uid 1000 --no-create-home --shell /bin/bash candidate \
    && mkdir /workspace \
    && chown candidate:candidate /workspace

WORKDIR /workspace
USER 1000:1000
