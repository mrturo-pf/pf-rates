#!/usr/bin/env bash
# ============================================================================
# sync_market_data.sh - one-shot: relaunch pf-rates with a clean TLS/proxy
#                        env and trigger a market-data sync for the last N
#                        days + M forward days.
#
# Why this exists: pf-rates is normally launched from a shell that carries
# Corporative-VPN leftovers (a corporate-only SSL_CERT_FILE bundle + proxy env
# vars). Those work fine for Corporative-internal hosts, but break TLS/DNS for
# the public Chilean data providers pf-rates talks to (mindicador.cl,
# sii.cl). This script relaunches pf-rates with those wiped, so it can
# actually reach the providers -- meant to be run with the Corporative VPN
# DISCONNECTED.
#
# Usage (from the pf-rates module root):
#   ./scripts/sync_market_data.sh                  # defaults: 365 days back, 35 forward
#   ./scripts/sync_market_data.sh 1095 30          # e.g. 3 years back + 30 days forward
#
# Notes:
#   - Only restarts pf-rates -- does not touch pf-db or pf-payroll.
#   - Does NOT connect/disconnect VPN -- that's on you, this only checks it.
#   - Assumes the standard local ecosystem layout (this repo checked out at
#     <pf-root>/modules/pf-rates), matching the sibling-repo convention
#     already used by scripts/local_stack.sh (../../pf-common) and
#     tests/integration (../pf-db). Logs go to the same shared location
#     scripts/pf-services.sh uses at the ecosystem root, so `tail -f` habits
#     keep working no matter which script (re)started pf-rates.
# ============================================================================
set -euo pipefail

LOOKBACK_DAYS="${1:-365}"
FORWARD_DAYS="${2:-35}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PF_RATES_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PF_ROOT_DIR="$(cd "$PF_RATES_DIR/../.." && pwd)"
LOG_FILE="$PF_ROOT_DIR/scripts/logs/pf-rates.log"
MODULE="rates.interfaces.api.main:app"
PORT=8001

# DNS search-domain substring that indicates the corporate VPN is still
# connected. Kept out of source as a placeholder default -- override with
# the real value via env var (e.g. in your shell profile or .env), same
# pattern as CORPORATIVE_PROXY / CORPORATIVE_PIP_INDEX in this repo's
# Makefile, so no real corporate domain ever needs to be committed.
VPN_DNS_MARKER="${VPN_DNS_MARKER:-corporative.com}"

section() { printf '\n== %s ==\n' "$*"; }
log() { printf '  %s\n' "$*"; }

section "Pre-flight: VPN check"
if scutil --dns 2>/dev/null | grep -q "$VPN_DNS_MARKER"; then
  log "WARNING: looks like the corporate VPN might still be connected"
  log "(DNS search domain includes $VPN_DNS_MARKER). This script needs the VPN"
  log "DISCONNECTED to reach mindicador.cl / sii.cl. Continuing anyway --"
  log "if the sync comes back empty, disconnect the VPN and re-run."
else
  log "no $VPN_DNS_MARKER DNS search domain detected -- looks disconnected, good."
fi

if [ ! -f "$PF_RATES_DIR/.env" ]; then
  echo ""
  echo "ERROR: missing $PF_RATES_DIR/.env"
  echo "Create it first: (cd $PF_RATES_DIR && make env-write), then fill in real values."
  exit 1
fi

API_KEY="$(grep -m1 '^PF_RATES_API_KEY=' "$PF_RATES_DIR/.env" | cut -d'=' -f2-)"
if [ -z "$API_KEY" ]; then
  echo ""
  echo "ERROR: PF_RATES_API_KEY not found in $PF_RATES_DIR/.env"
  exit 1
fi

section "Restarting pf-rates with a clean TLS/proxy env"
pkill -f "uvicorn $MODULE" >/dev/null 2>&1 || true
sleep 1

CERTIFI_BUNDLE="$("$PF_RATES_DIR/.venv/bin/python" -c 'import certifi; print(certifi.where())')"
log "using certifi bundle: $CERTIFI_BUNDLE"

mkdir -p "$PF_ROOT_DIR/scripts/logs"
: >"$LOG_FILE"

(
  cd "$PF_RATES_DIR"
  env -u SSL_CERT_FILE -u SSL_CERT_DIR \
      -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
      -u no_proxy -u NO_PROXY \
      SSL_CERT_FILE="$CERTIFI_BUNDLE" \
      nohup make run >"$LOG_FILE" 2>&1 &
)
disown 2>/dev/null || true

section "Waiting for pf-rates to come up healthy"
healthy=""
for _ in $(seq 1 20); do
  if curl -sf "http://localhost:$PORT/health" >/dev/null 2>&1; then
    healthy="yes"
    break
  fi
  sleep 0.5
done
if [ -z "$healthy" ]; then
  echo ""
  echo "ERROR: pf-rates did not become healthy. Check $LOG_FILE"
  exit 1
fi
log "pf-rates healthy -> http://localhost:$PORT/health"

section "Triggering /sync (lookback_days=$LOOKBACK_DAYS forward_days=$FORWARD_DAYS)"
curl -s -X POST "http://localhost:$PORT/sync" \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $API_KEY" \
  -d "{\"lookback_days\": $LOOKBACK_DAYS, \"forward_days\": $FORWARD_DAYS}" \
  --max-time 300 \
  -w '\nHTTP_STATUS:%{http_code}\nTIME_TOTAL:%{time_total}s\n'

section "Last 60 lines of pf-rates.log (provider detail)"
tail -n 60 "$LOG_FILE"

section "Done"
log "Remember to reconnect the Corporative VPN now if you disconnected it for this."
