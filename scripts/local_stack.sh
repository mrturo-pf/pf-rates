#!/usr/bin/env bash
set -euo pipefail

# Database is now managed by pf-db (shared with pf-payroll).
# The pf-db container must be running before this script is called.
# Start it with: cd ../pf-db && make db-up

DB_CONTAINER="${DB_CONTAINER:-pf-db-db-1}"
PF_DATABASE_URL="${PF_DATABASE_URL:-postgresql+asyncpg://pf_db:pf_db@localhost:5432/pf_db}"
PF_RATES_API_KEY="${PF_RATES_API_KEY:-change-me-before-use}"
APP_PORT="${APP_PORT:-8001}"
VENV="${VENV:-.venv}"
ENV_FILE="${ENV_FILE:-.env}"
CORPORATIVE_PIP_INDEX="${CORPORATIVE_PIP_INDEX:-}"
CORPORATIVE_NPM_REGISTRY="${CORPORATIVE_NPM_REGISTRY:-}"
CORPORATIVE_PROXY="${CORPORATIVE_PROXY:-}"

log() {
  printf '[local-up] %s\n' "$1"
}

venv_ready() {
  [[ -x "$VENV/bin/python" ]] && [[ -x "$VENV/bin/uvicorn" ]] && \
    "$VENV/bin/python" -c "import rates, fastapi, asyncpg, pydantic_settings, sqlalchemy, uvicorn" >/dev/null 2>&1
}

# Verify the shared pf-db container is running.
log "Checking shared pf-db container ($DB_CONTAINER)"
if ! docker inspect --format '{{.State.Status}}' "$DB_CONTAINER" 2>/dev/null | grep -q "^running$"; then
  echo ""
  echo "ERROR: pf-db container '$DB_CONTAINER' is not running."
  echo ""
  echo "Start the shared database first:"
  echo "  cd ../pf-db && make db-up"
  echo ""
  exit 1
fi
log "pf-db container is running"

log "Writing environment file to $ENV_FILE"
PF_DATABASE_URL="$PF_DATABASE_URL" \
PF_RATES_API_KEY="$PF_RATES_API_KEY" \
CORPORATIVE_PIP_INDEX="$CORPORATIVE_PIP_INDEX" \
CORPORATIVE_NPM_REGISTRY="$CORPORATIVE_NPM_REGISTRY" \
CORPORATIVE_PROXY="$CORPORATIVE_PROXY" \
ENV_FILE="$ENV_FILE" \
./scripts/write_env.sh >/dev/null

if venv_ready; then
  log "Reusing existing virtual environment in $VENV"
else
  log "Installing project dependencies"
  if [[ ! -x "$VENV/bin/python" ]]; then
    python3 -m venv "$VENV"
  fi
  "$VENV/bin/python" -m ensurepip --upgrade
  "$VENV/bin/python" -m pip install -e ".[dev]"
fi

printf '\n'
printf 'API  : http://127.0.0.1:%s\n' "$APP_PORT"
printf 'Docs : http://127.0.0.1:%s/docs\n' "$APP_PORT"
printf 'Env  : %s\n' "$ENV_FILE"
printf '\n'

exec "$VENV/bin/uvicorn" rates.interfaces.api.main:app --reload --host 127.0.0.1 --port "$APP_PORT"
