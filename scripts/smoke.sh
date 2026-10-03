#!/usr/bin/env bash
# Smoke test for a freshly-started farm.
#
# Usage:  scripts/smoke.sh [URL] [TOKEN]
#   URL   defaults to http://localhost:5000
#   TOKEN defaults to the FARM_API_TOKEN from .env (or "change-me-please")
#
# Exits non-zero on the first failure. Prints what it submitted and what
# the farm reports back.

set -euo pipefail

URL=${1:-http://localhost:5000}
if [ -z "${2:-}" ]; then
  if [ -f .env ]; then
    # shellcheck disable=SC1091
    set -a; . ./.env; set +a
  fi
  TOKEN=${FARM_API_TOKEN:-change-me-please}
else
  TOKEN=$2
fi

H="-H X-Farm-Token:$TOKEN -H Content-Type:application/json"

step() { printf "\n\033[1;36m▶ %s\033[0m\n" "$*"; }

# Fresh random sample flags in the default "[A-Z0-9]{31}=" format, so a
# re-run doesn't report everything as duplicate.
rnd() { { LC_ALL=C tr -dc 'A-Z0-9' </dev/urandom | head -c 31; } || true; printf '='; }
F1=$(rnd); F2=$(rnd); F3=$(rnd); F4=$(rnd)

step "GET /health"
curl -sf "$URL/health"; echo

step "GET /api/config"
curl -sf $H "$URL/api/config" | head -c 400; echo
if ! curl -sf $H "$URL/api/config" | grep -q '"flag_format":"\[A-Z0-9\]{31}="'; then
  printf '\033[1;33m! flag_format is not the default — the sample flags below will be\n'
  printf '  counted as invalid (new=0), the endpoints are still exercised.\033[0m\n'
fi

step "GET /api/config/protocols"
curl -sf $H "$URL/api/config/protocols"; echo

step "POST /api/flags (one valid + one bogus)"
curl -sf $H -X POST "$URL/api/flags" \
  -d '{"items":[{"flag":"'"$F1"'","sploit":"smoke","team":"team-1","target_ip":"10.60.1.2"},{"output":"junk\n'"$F2"'\nmore junk\n","sploit":"smoke","team":"team-2","target_ip":"10.60.2.2"},{"flag":"not-a-flag","sploit":"smoke"}]}'
echo

step "POST /api/flags/manual"
curl -sf $H -X POST "$URL/api/flags/manual" \
  -d '{"text":"here is a flag '"$F3"' and another '"$F4"'","sploit":"manual"}'
echo

step "GET /api/flags?limit=10"
curl -sf -D - -o /dev/null $H "$URL/api/flags?limit=10" | grep -i x-total-count
curl -sf $H "$URL/api/flags?limit=10" | head -c 600; echo

step "GET /api/flags?q=<part of a sample flag>"
curl -sf $H "$URL/api/flags?q=${F1:0:10}" | head -c 300; echo

step "GET /api/teams"
curl -sf $H "$URL/api/teams" | head -c 300; echo

step "GET /api/stats"
curl -sf $H "$URL/api/stats" | head -c 400; echo

echo
echo "smoke ok — head over to the UI (http://localhost:8080) to see the flags."
