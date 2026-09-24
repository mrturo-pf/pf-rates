#!/usr/bin/env bash
# ============================================================================
# backfill-tax-brackets.sh - backfill official income tax brackets on any
#                             pf-rates instance (local or a deployed URL)
#
# Pulls monthly income tax brackets straight from the SII (Chile's tax
# authority, https://www.sii.cl) for every year in the given range and
# upserts them via the target instance's own POST /income-tax-brackets/refresh
# endpoint -- the exact same trusted mechanism pf-rates already uses to keep
# "recent" years in sync, just looped over a wider historical range instead
# of hand-typing historical values (accuracy risk, not worth it).
#
# Bonus: upsert_income_tax_brackets() does ON CONFLICT (valid_from,
# lower_bound_utm) DO UPDATE, so re-running this for a year that already has
# a (possibly broken, e.g. open-ended valid_to=NULL) row self-heals it --
# no separate cleanup step needed.
#
# This script does NOT touch any local process -- it only calls the target's
# HTTP API. Whichever DB that instance is wired to is what gets updated:
#   - http://localhost:8001    -> your local Postgres (via pf-services.sh)
#   - the deployed Cloud Run URL -> Neon (its PF_DATABASE_URL Secret Manager
#     value), and the SII fetch happens server-side from GCP, so no VPN
#     disconnect is needed on your end for that target.
#
# Reads the target from secrets/backfill-target.env (gitignored) -- copy
# secrets/backfill-target.env.example if missing.
#
# Usage:
#   scripts/backfill-tax-brackets.sh [start_year] [end_year]
#   scripts/backfill-tax-brackets.sh              # defaults: 2010..current year
#   scripts/backfill-tax-brackets.sh 2015 2020
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PF_RATES_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SECRETS_ENV="$PF_RATES_DIR/secrets/backfill-target.env"

START_YEAR="${1:-2010}"
END_YEAR="${2:-$(date +%Y)}"

section() { printf '\n== %s ==\n' "$*"; }
log() { printf '  %s\n' "$*"; }

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
section "Pre-flight checks"

if [ ! -f "$SECRETS_ENV" ]; then
  echo ""
  echo "ERROR: missing $SECRETS_ENV"
  echo "Create it first: cp secrets/backfill-target.env.example secrets/backfill-target.env"
  echo "Then fill in PF_RATES_BASE_URL and PF_RATES_API_KEY for your target."
  exit 1
fi
# shellcheck disable=SC1090
source "$SECRETS_ENV"
if [ -z "${PF_RATES_BASE_URL:-}" ] || [ -z "${PF_RATES_API_KEY:-}" ]; then
  echo "ERROR: PF_RATES_BASE_URL and/or PF_RATES_API_KEY missing in $SECRETS_ENV"
  exit 1
fi
BASE_URL="${PF_RATES_BASE_URL%/}"

log "target: $BASE_URL"
if ! curl -sf --max-time 10 "$BASE_URL/health" >/dev/null 2>&1; then
  echo ""
  echo "ERROR: $BASE_URL/health did not respond."
  echo "Check the URL in $SECRETS_ENV, and that the target is actually up."
  exit 1
fi
log "target is healthy"

# ---------------------------------------------------------------------------
# Backfill loop
# ---------------------------------------------------------------------------
section "Backfilling income tax brackets $START_YEAR..$END_YEAR on $BASE_URL"
total_ok=0
total_fail=0
for year in $(seq "$START_YEAR" "$END_YEAR"); do
  response="$(curl -s -w '\nHTTP_STATUS:%{http_code}' -X POST "$BASE_URL/income-tax-brackets/refresh" \
    -H 'Content-Type: application/json' \
    -H "X-API-Key: $PF_RATES_API_KEY" \
    -d "{\"year\": $year}")"
  status="$(echo "$response" | grep -o 'HTTP_STATUS:[0-9]*' | cut -d: -f2)"
  body="$(echo "$response" | sed '/HTTP_STATUS:/d')"
  if [ "$status" = "200" ]; then
    log "$year: OK -- $body"
    total_ok=$((total_ok + 1))
  else
    log "$year: FAILED (HTTP $status) -- $body"
    total_fail=$((total_fail + 1))
  fi
done

section "Done"
log "Years OK: $total_ok / FAILED: $total_fail"
log "Target updated: $BASE_URL"
log ""
log "If you targeted Cloud Run (Neon): run pf-db/scripts/export-neon-dump.sh"
log "(off VPN) + restore-neon-dump.sh afterward to sync the corrected"
log "historical data into your local dev DB too."
