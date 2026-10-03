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
git clone https://github.com/BekoSa/NeoFarm.git farm && cd farm
cp .env.example .env
# set FARM_API_TOKEN (required — the server refuses the default)
docker compose pull          # prebuilt images from ghcr.io (built by CI)
docker compose up -d         # ...or `docker compose up -d --build` to build locally
```

Open the UI at `http://<farm-host>:8080` and paste the `FARM_API_TOKEN`.
The UI proxies the API on the same origin, so the default server URL on
the login screen is already right; the API is also reachable directly on
port 5000 (`farm-cli` can use either).

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
  period: 5                   # min seconds between two submissions (jury rate limit)
  idle_period: 0.5            # how often an empty queue is polled
  batch_size: 100             # max flags per submission

teams:
  - alias: team-1
    ip: 10.60.1.2
  - from: 3                   # ranges: {i} is the team number
    to: 20
    alias: "team-{i:02d}"
    ip: "10.60.{i}.2"

exclude_teams: [team-07]      # aliases or IPs never attacked: own team, NOP team
runs_retention: 7200          # purge exploit run reports older than this (0 = keep)
```

Every service watches `config.yml`: saving from the Config tab **or**
editing the file by hand is picked up within a second or two, no restart.
A file that fails to parse or validate is ignored (logged) and the last
good config stays active, so a typo mid-game can't take the farm down.
Saving from the UI keeps the comments in the file.

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

Each round the client re-reads the config, the team list and the
exploit's on/off switch from the farm, so config edits and the toggle on
the **Exploits** tab apply to running clients. All targets run in
parallel by default and share one deadline (`round_length - 5` s, or
`--timeout`): a hanging exploit is killed — helpers included — instead of
stretching the round. Ctrl-C finishes the current round; a second Ctrl-C
kills the running exploits immediately. Found flags are shipped about
once a second while the exploit is still running.

Useful flags:

```sh
farm-cli run sploit.py --once               # one round and exit
farm-cli run sploit.py -p 4                 # at most 4 teams at a time
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
per process at startup): `docker compose restart server submitter`. The
host's `server/farm/` is mounted into the containers, so no rebuild is
needed. Modules whose name starts with `_` are helpers, not protocols. Set `protocol: <name>` in `config.yml` and add
its kwargs under `protocols.<name>:`. Done — **no imports, no
registry edits**.

## API surface

| method | path                          | purpose                                 |
|--------|-------------------------------|------------------------------------------|
| POST   | `/api/flags`                  | client-side flag intake (JSON items)     |
| POST   | `/api/flags/manual`           | extract+queue from arbitrary text        |
| GET    | `/api/flags`                  | browse with `status/sploit/team/q` filters; total in `X-Total-Count` |
| POST   | `/api/flags/requeue`          | bulk re-queue REJECTED/ERROR/EXPIRED flags still within `flag_lifetime` |
| POST   | `/api/flags/{id}/requeue`     | re-queue a single flag                   |
| DELETE | `/api/flags/{id}`             | drop a flag                              |
| POST   | `/api/exploits`               | register / heartbeat an exploit          |
| GET    | `/api/exploits`               | list exploits                            |
| PATCH  | `/api/exploits/{id}`          | partial update (e.g. `{"enabled": false}`) |
| DELETE | `/api/exploits/{id}`          | drop an exploit                          |
| POST   | `/api/runs`                   | report an exploit run                    |
| GET    | `/api/runs`                   | recent runs                              |
| GET    | `/api/teams`                  | attack targets (`teams` minus `exclude_teams`) |
| GET    | `/api/stats`                  | aggregate dashboard data                 |
| GET    | `/api/config`                 | active config                            |
| PUT    | `/api/config`                 | replace config (validated, persisted)    |
| GET    | `/api/config/protocols`       | available protocol ids                   |
| WS     | `/ws`                         | live event feed                          |

All HTTP endpoints require `X-Farm-Token: <FARM_API_TOKEN>`. WebSocket
clients send the token as their first message (it stays out of URLs and
access logs). The feed carries API events (`flags`, `run`, `exploit`,
`requeue`) and worker events relayed through Redis: `submit` (verdict
counts), `submitter_error` (the jury answered nothing — check its config)
and `expired`.

## Layout

```
.
├── docker-compose.yml
├── config.yml
├── .env.example
├── server/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── tests/
│   └── farm/
│       ├── main.py             # FastAPI app
│       ├── config.py           # YAML + env settings
│       ├── db.py               # async SQLA setup
│       ├── models.py
│       ├── schemas.py
│       ├── ws.py               # in-process pub/sub for the WebSocket
│       ├── events.py           # worker events via Redis pub/sub
│       ├── api/                # routers
│       ├── core/flag_extractor.py
│       ├── protocols/          # ← drop a *.py here
│       │   ├── base.py
│       │   ├── altayctf_http.py
│       │   ├── altayctf_tcp.py
│       │   ├── _altayctf.py    # shared reply parsing (not a protocol)
│       │   ├── ctf01d.py
│       │   ├── dummy.py
│       │   ├── forcad.py
│       │   ├── faustctf.py
│       │   └── ructf.py
│       └── workers/
│           ├── submitter.py
│           └── expirer.py
├── client/
│   ├── pyproject.toml
│   ├── farm_cli/               # `farm-cli` entrypoint
│   └── tests/
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

- The DB schema is created on startup; columns added later are patched
  in by `init_db()` (no migration framework). Wipe the `pgdata` volume to
  reset.
- A jury ERROR (unreachable, 5xx, 4xx from a wrong token/team id) is
  never final: the flag goes back to the queue and is retried until it
  expires, behind fresh flags. Fix the jury config and nothing is lost.
  REJECTED flags can be pushed again in bulk from the Flags tab.
- The submitter uses Postgres' `FOR UPDATE SKIP LOCKED` so you can run
  multiple instances safely if a single submitter is the bottleneck.
- The dashboard auto-refreshes every 4–5 seconds; on top of that, every
  flag, run and exploit registration is pushed via WebSocket.
- The submitter, expirer and api containers all read the same
  `config.yml` and re-read it whenever it changes.

## Tests & CI

```sh
make test   # server + client unit tests (needs pytest and both packages installed)
```

`.github/workflows/ci.yml` runs the tests and the frontend build on every
push and pull request. Pushes to `main` and `v*` tags also publish
`ghcr.io/bekosa/neofarm-server` and `ghcr.io/bekosa/neofarm-frontend`
(`latest`, the version for tags, and the short commit SHA). Pin a version
with `FARM_TAG=<tag>` in `.env`.
