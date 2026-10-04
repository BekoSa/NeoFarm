# =============================================================================
# Node agent image — runs `farm-cli node` in a container so a teammate can
# join the farm with one `docker run`, no native Python/farm-cli install.
#
# Build context is the repo root (it needs client/ and node/entrypoint.sh):
#   docker build -f node/Dockerfile -t neofarm-node .
#
# 3.12 (not the server's 3.14) for the widest exploit-dependency wheel
# coverage; the node is otherwise independent of the server runtime.
# =============================================================================
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# git/curl: common in exploit scripts; ca-certificates for TLS. bash ships in
# the base image already (used for .sh exploits).
RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY client /tmp/client
# farm-cli + a small set of libraries most CTF exploits reach for; anything
# heavier (pwntools, …) is added per-node via PIP_PACKAGES or a FROM-extend.
RUN pip install --upgrade pip \
 && pip install /tmp/client requests pycryptodome \
 && rm -rf /tmp/client

COPY node/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Scripts the farm pushes land here (ephemeral; re-fetched by rev on restart).
# The node identity lives under ~/.config/farm-cli — mount a volume there so a
# restarted container is the SAME node, not a new one.
ENV FARM_NODE_WORKDIR=/root/.cache/farm-cli/node

ENTRYPOINT ["entrypoint.sh"]
