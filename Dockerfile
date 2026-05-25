# syntax=docker/dockerfile:1.7

ARG PYTHON_VERSION=3.13

FROM ghcr.io/astral-sh/uv:0.11.16 AS uv

FROM node:24-bookworm-slim AS player-build

WORKDIR /build/player

COPY player/package.json player/package-lock.json ./
RUN npm ci

COPY player/ ./
RUN npm run build

FROM python:${PYTHON_VERSION}-slim-bookworm

ARG SERVICE_VERSION=0.0.0+dev

LABEL org.opencontainers.image.title="Sendspin Service"
LABEL org.opencontainers.image.description="Standalone Sendspin playback service with HTTP ingest API"
LABEL org.opencontainers.image.source="https://github.com/dutchdronesquad/rh-local-voice"
LABEL org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV SENDSPIN_SERVICE_VERSION=${SERVICE_VERSION}
ENV SENDSPIN_INGEST_HOST=0.0.0.0
ENV SENDSPIN_INGEST_PORT=8766
ENV SENDSPIN_HOST=0.0.0.0
ENV SENDSPIN_PORT=8927
ENV SENDSPIN_ADVERTISE=false
ENV SENDSPIN_MAX_BODY_MB=50
ENV SENDSPIN_PLAYER_DIR=/opt/sendspin-service/player
ENV SENDSPIN_API_TOKEN=

WORKDIR /opt/sendspin-service

COPY --from=uv /uv /uvx /usr/local/bin/
COPY pyproject.toml uv.lock ./

RUN python3 - <<'PY' > /tmp/sendspin-service-requirements.txt
import tomllib
from pathlib import Path
for dep in tomllib.loads(Path("pyproject.toml").read_text())["project"]["optional-dependencies"]["sendspin-service"]:
    print(dep)
PY

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --requirements /tmp/sendspin-service-requirements.txt \
    && rm /tmp/sendspin-service-requirements.txt

COPY sendspin_service ./sendspin_service
COPY --from=player-build /build/custom_plugins/local_voice/player ./player

RUN useradd --system --uid 10001 --home-dir /nonexistent --shell /usr/sbin/nologin sendspin

USER sendspin

EXPOSE 8766 8927

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=3).read()"

CMD ["python", "-m", "sendspin_service"]
