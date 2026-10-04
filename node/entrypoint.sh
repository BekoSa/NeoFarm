#!/usr/bin/env sh
# Launch the farm node agent. Credentials come from FARM_URL / FARM_TOKEN
# (read by farm-cli directly), so no `farm-cli login` is needed.
set -e

# Optional: install extra exploit dependencies at startup without rebuilding
# the image, e.g. -e PIP_PACKAGES="pwntools beautifulsoup4".
if [ -n "$PIP_PACKAGES" ]; then
    echo "[entrypoint] installing extra packages: $PIP_PACKAGES"
    pip install --no-cache-dir $PIP_PACKAGES
fi

# "$@" is whatever was passed after the image name in `docker run`; prepend the
# options derived from env so both work together.
[ -n "$FARM_NODE_WORKDIR" ] && set -- --workdir "$FARM_NODE_WORKDIR" "$@"
[ -n "$NODE_NAME" ] && set -- --name "$NODE_NAME" "$@"

exec farm-cli node "$@"
