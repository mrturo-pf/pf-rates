#!/usr/bin/env bash
set -euo pipefail

# Database is now managed by pf-db (shared with pf-payroll).
# The pf-db container must be running before this script is called.
# Start it with: cd ../pf-db && make db-up

APP_PORT="${APP_PORT:-8001}"
VENV="${VENV:-.venv}"
ENV_FILE="${ENV_FILE:-.env}"
CORPORATIVE_PIP_INDEX="${CORPORATIVE_PIP_INDEX:-}"
CORPORATIVE_NPM_REGISTRY="${CORPORATIVE_NPM_REGISTRY:-}"

log() {
  printf '[local-up] %s\n' "$1"
}

venv_ready() {
  [[ -x "$VENV/bin/python" ]] && [[ -x "$VENV/bin/uvicorn" ]] && \
    "$VENV/bin/python" -c "import financial_data, fastapi, asyncpg, pydantic_settings, sqlalchemy, uvicorn" >/dev/null 2>&1
}

# Verify the shared pf-db container is running.
log "Checking shared pf-db container (pf-db-db-1)"
if ! docker inspect --format '{{.State.Status}}' pf-db-db-1 2>/dev/null | grep -q "^running$"; then
  echo ""
  echo "ERROR: pf-db container 'pf-db-db-1' is not running."
  echo ""
  echo "Start the shared database first:"
  echo "  cd ../pf-db && make db-up"
  echo ""
  exit 1
fi
log "pf-db container is running"

log "Writing environment file to $ENV_FILE"
{
  printf '# Database managed by pf-db (shared with pf-payroll)\n'
  printf 'PF_DATABASE_URL=postgresql+asyncpg://pf_db:pf_db@localhost:5432/pf_db\n'
  printf '\n# Tooling — corporate pip/npm registries (used by make install/check on VPN)\n'
  printf 'CORPORATIVE_PIP_INDEX=%s\n' "$CORPORATIVE_PIP_INDEX"
  printf 'CORPORATIVE_NPM_REGISTRY=%s\n' "$CORPORATIVE_NPM_REGISTRY"
} > "$ENV_FILE"

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

exec "$VENV/bin/uvicorn" financial_data.interfaces.api.app:app --reload --host 127.0.0.1 --port "$APP_PORT"
