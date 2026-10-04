# Farm node (Docker)

Run a teammate's machine as a **farm-managed exploit node** in a container — no
native Python or `farm-cli` install. The node registers with the farm, appears
under the **Nodes** tab, and runs whatever exploits the operator pushes to it,
one round loop each (the same path as `farm-cli run`). Flags flow through the
normal pipeline.

## Run it

With compose (recommended — persists the node identity across restarts):

```sh
FARM_URL=http://<farm-host>:5000 \
FARM_TOKEN=<X-Farm-Token> \
NODE_NAME=$(hostname) \
docker compose -f node/docker-compose.yml up -d
```

Or a plain `docker run`:

```sh
docker run -d --name neofarm-node --restart unless-stopped --network host \
  -e FARM_URL=http://<farm-host>:5000 \
  -e FARM_TOKEN=<X-Farm-Token> \
  -e NODE_NAME=$(hostname) \
  -v neofarm-node:/root/.config/farm-cli \
  ghcr.io/bekosa/neofarm-node:latest
```

Then open the farm UI → **Nodes**, find your node (it goes *online* within a
few seconds), expand it and **push an exploit** (name + script + optional args).

Logs / stop:

```sh
docker compose -f node/docker-compose.yml logs -f
docker compose -f node/docker-compose.yml down
```

## Notes

- **Identity.** The node id lives in the `node-state` volume
  (`/root/.config/farm-cli/node-id`). Keep the volume and a restart rejoins as
  the *same* node; delete it and you get a new one in the UI.
- **Networking.** `--network host` makes the node reach the game network just
  like the host. On Docker Desktop (mac/Windows) drop it — bridge NAT still
  reaches external target IPs, you just won't share the host's network stack.
- **Exploit dependencies.** The image ships `requests` + `pycryptodome`. For
  more, either:
  - pass them at startup: `-e PIP_PACKAGES="pwntools beautifulsoup4"`, or
  - build your own: `FROM ghcr.io/bekosa/neofarm-node:latest` + `RUN pip install …`.
- **Control from the UI.** Toggle the whole node on/off, toggle or remove
  individual exploits, and re-push a script to update it (the agent restarts
  just that exploit). A farm **pause** stops every node's rounds too.
