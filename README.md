# 🐄 Farm — A/D CTF flag farm

A small, opinionated farm for Attack/Defense CTFs:

- runs exploits in **any** language (Python, bash, Go binaries, ...);
- collects their stdout, **extracts flags by regex**;
- deduplicates, expires (TTL), and **batches** them to the jury;
- has a **plugin system** for jury submission protocols (drop a `*.py`,
  done — no manual imports);
- a small **React UI** (dashboard, flags table, manual submit, config
  editor with hot-reload, live event feed);
- the client (`farm-cli`) talks to the farm over HTTP, so exploits can
  run on **any machine** with network reach to the farm — not only on
  the farm host.

The whole stack is one `docker compose up`.

---

## Stack

| component   | what it is                                               |
|-------------|----------------------------------------------------------|
| `server`    | FastAPI + SQLAlchemy(async) + PostgreSQL + Redis         |
| `submitter` | worker that drains queued flags via the chosen protocol  |
| `expirer`   | worker that EXPIREs flags older than `flag_lifetime`     |
| `frontend`  | React 18 + Vite + Tailwind, served by nginx              |
| `farm-cli`  | client: registers a sploit, runs it per round per team   |

Server-side: **Python 3.14** in a `python:3.14-slim` container.

## Quickstart

```sh
git clone <this-repo> farm && cd farm
cp .env.example .env
# at least set FARM_API_TOKEN and (optionally) VITE_API_BASE
docker compose up -d --build
```

Open the UI at <http://localhost:8080>. On the login screen, point it at
`http://localhost:5000` and paste the `FARM_API_TOKEN`.

By default the server uses the `dummy` protocol — every queued flag is
"accepted" so you can verify the wiring end-to-end before plugging in
your jury credentials.

## Configure your CTF

Edit `config.yml` (or via the **Config** tab in the UI):

```yaml
flag_format: "[A-Z0-9]{31}="
flag_lifetime: 900            # seconds
round_length: 60              # seconds
protocol: forcad              # one of the modules under server/farm/protocols/

protocols:
  forcad:
    url: "http://10.10.10.10:8080/flags"
    team_token: "PUT-YOUR-TEAM-TOKEN-HERE"

submitter:
  period: 5                   # seconds between submissions
  batch_size: 100             # max flags per submission

teams:
  - alias: team-1
    ip: 10.60.1.2
  - alias: team-2
    ip: 10.60.2.2
```

The Config tab saves to disk **and** hot-reloads the in-memory config
for all services. No restart.

## Run an exploit

On the **farm host** itself, or on **any other machine** that can reach
`http://farm-host:5000`:

```sh
pip install -e ./client
farm-cli login http://farm-host:5000 --token "$FARM_API_TOKEN"
farm-cli run exploits/sploit_example.py
```

The script is invoked once per team per round as

    <interpreter> <script> <team-ip> [extra-args]

with `$FARM_TARGET` also set to the IP. `farm-cli` infers the
interpreter from the file extension (`.py`, `.sh`, `.rb`, `.js`, `.ts`,
`.pl`, `.php`) — anything else with `+x` is exec'd directly. So
compiled binaries (Go, Rust, C) work without ceremony.

Useful flags:

```sh
farm-cli run sploit.py --once               # one round and exit
farm-cli run sploit.py -p 16                # 16 teams in parallel
farm-cli run sploit.py --target a=1.2.3.4   # override targets
farm-cli run sploit.py --args '--service redis'
farm-cli send 'paste flags here'            # manual submit
farm-cli watch                              # tail the event feed
```

## Add a new jury protocol

Drop a file at `server/farm/protocols/<name>.py`:

```python
from .base import BaseProtocol, FlagVerdict, SubmissionResult

class MyJuryProtocol(BaseProtocol):
    display_name = "My jury"

    def __init__(self, url: str, team_token: str = "", **kw):
        super().__init__(url=url, team_token=team_token, **kw)
        self.url = url
        self.token = team_token

    async def submit(self, flags):
        # ... HTTP/TCP/whatever; return one SubmissionResult per flag.
        return [SubmissionResult(flag=f, verdict=FlagVerdict.ACCEPTED, response="ok")
                for f in flags]
```

Restart the `server` and `submitter` containers (the loader runs once
per process at startup). Set `protocol: <name>` in `config.yml` and add
its kwargs under `protocols.<name>:`. Done — **no imports, no
registry edits**.

## API surface

| method | path                          | purpose                                 |
|--------|-------------------------------|------------------------------------------|
| POST   | `/api/flags`                  | client-side flag intake (JSON items)     |
| POST   | `/api/flags/manual`           | extract+queue from arbitrary text        |
| GET    | `/api/flags`                  | browse with `status/sploit/team` filters |
| POST   | `/api/flags/{id}/requeue`     | re-queue a single flag                   |
| DELETE | `/api/flags/{id}`             | drop a flag                              |
| POST   | `/api/exploits`               | upsert an exploit                        |
| GET    | `/api/exploits`               | list exploits                            |
| POST   | `/api/runs`                   | report an exploit run                    |
| GET    | `/api/runs`                   | recent runs                              |
| GET    | `/api/teams`                  | teams from `config.yml`                  |
| GET    | `/api/stats`                  | aggregate dashboard data                 |
| GET    | `/api/config`                 | active config                            |
| PUT    | `/api/config`                 | replace config (validated, persisted)    |
| GET    | `/api/config/protocols`       | available protocol ids                   |
| WS     | `/ws?token=…`                 | live event feed                          |

All HTTP endpoints require `X-Farm-Token: <FARM_API_TOKEN>`.

## Layout

```
.
├── docker-compose.yml
├── config.yml
├── .env.example
├── server/
│   ├── Dockerfile
│   ├── pyproject.toml
│   └── farm/
│       ├── main.py             # FastAPI app
│       ├── config.py           # YAML + env settings
│       ├── db.py               # async SQLA setup
│       ├── models.py
│       ├── schemas.py
│       ├── ws.py               # in-process pub/sub
│       ├── api/                # routers
│       ├── core/flag_extractor.py
│       ├── protocols/          # ← drop a *.py here
│       │   ├── base.py
│       │   ├── dummy.py
│       │   ├── forcad.py
│       │   ├── faustctf.py
│       │   └── ructf.py
│       └── workers/
│           ├── submitter.py
│           └── expirer.py
├── client/
│   ├── pyproject.toml
│   └── farm_cli/               # `farm-cli` entrypoint
├── frontend/
│   ├── Dockerfile
│   ├── nginx.conf
│   ├── package.json
│   └── src/                    # React UI
└── exploits/
    ├── README.md
    └── sploit_example.py
```

## Notes & limits

- The DB schema is created on startup; this is a CTF tool, no migrations.
  Wipe the `pgdata` volume to reset.
- The submitter uses Postgres' `FOR UPDATE SKIP LOCKED` so you can run
  multiple instances safely if a single submitter is the bottleneck.
- The dashboard auto-refreshes every 4–5 seconds; on top of that, every
  flag, run and exploit registration is pushed via WebSocket.
- The submitter, expirer and api containers all read the same
  `config.yml`. Saving via the UI calls `replace_config()` which
  rewrites the file; workers re-read on their next tick.
