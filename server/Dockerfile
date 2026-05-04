# =============================================================================
# Build stage — produces a self-contained farm-cli.pyz that the API serves
# at GET /install/farm-cli for clients to download.
# =============================================================================
FROM python:3.14-slim AS cli-builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY client /build/client

# Install farm-cli + its runtime deps into a flat directory, then bundle the
# whole tree into a single executable zipapp. ``--main`` synthesizes a
# top-level __main__.py that calls farm_cli.cli.cli().
RUN pip install --upgrade pip \
 && pip install --target /build/pkg /build/client \
 && find /build/pkg -name '*.dist-info' -prune -exec rm -rf {} + \
 && find /build/pkg -name '__pycache__' -prune -exec rm -rf {} + \
 && python -m zipapp /build/pkg \
        --output /build/farm-cli.pyz \
        --main "farm_cli.cli:cli" \
        --python "/usr/bin/env python3" \
        --compress


# =============================================================================
# Runtime image — API / submitter / expirer share this.
# =============================================================================
FROM python:3.14-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY server/pyproject.toml /app/pyproject.toml
RUN pip install --upgrade pip && pip install .

COPY server/farm /app/farm

# CLI distributable for clients (served by GET /install/farm-cli).
COPY --from=cli-builder /build/farm-cli.pyz /app/static/farm-cli.pyz

EXPOSE 5000
CMD ["uvicorn", "farm.main:app", "--host", "0.0.0.0", "--port", "5000"]
