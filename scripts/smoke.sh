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

step "GET /health"
curl -sf "$URL/health"; echo

step "GET /api/config"
curl -sf $H "$URL/api/config" | head -c 400; echo

step "GET /api/config/protocols"
curl -sf $H "$URL/api/config/protocols"; echo

step "POST /api/flags (one valid + one bogus)"
curl -sf $H -X POST "$URL/api/flags" \
  -d '{"items":[{"flag":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=","sploit":"smoke","team":"team-1","target_ip":"10.60.1.2"},{"output":"junk\nBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=\nmore junk\n","sploit":"smoke","team":"team-2","target_ip":"10.60.2.2"},{"flag":"not-a-flag","sploit":"smoke"}]}'
echo

step "POST /api/flags/manual"
curl -sf $H -X POST "$URL/api/flags/manual" \
  -d '{"text":"here is a flag CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC= and another DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD=","sploit":"manual"}'
echo

step "GET /api/flags?limit=10"
curl -sf $H "$URL/api/flags?limit=10" | head -c 600; echo

step "GET /api/stats"
curl -sf $H "$URL/api/stats" | head -c 400; echo

echo
echo "smoke ok — head over to the UI (http://localhost:8080) to see the flags."
