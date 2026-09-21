#!/usr/bin/env bash
set -euo pipefail

# Database is now managed by pf-db (shared with pf-payroll).
# The pf-db container must be running before this script is called.
# Start it with: cd ../pf-db && make db-up

DB_CONTAINER="${DB_CONTAINER:-pf-db-db-1}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../pf-common/scripts/local_stack_common.sh
source "$SCRIPT_DIR/../../pf-common/scripts/local_stack_common.sh"
PF_DATABASE_URL="${PF_DATABASE_URL:-postgresql+asyncpg://pf_db:pf_db@localhost:5432/pf_db}"
PF_RATES_API_KEY="${PF_RATES_API_KEY:-change-me-before-use}"
APP_PORT="${APP_PORT:-8001}"
VENV="${VENV:-.venv}"
ENV_FILE="${ENV_FILE:-.env}"
CORPORATIVE_PIP_INDEX="${CORPORATIVE_PIP_INDEX:-}"
CORPORATIVE_NPM_REGISTRY="${CORPORATIVE_NPM_REGISTRY:-}"
CORPORATIVE_PROXY="${CORPORATIVE_PROXY:-}"

pf_require_db_container "$DB_CONTAINER"

pf_log "Writing environment file to $ENV_FILE"
PF_DATABASE_URL="$PF_DATABASE_URL" \
PF_RATES_API_KEY="$PF_RATES_API_KEY" \
CORPORATIVE_PIP_INDEX="$CORPORATIVE_PIP_INDEX" \
CORPORATIVE_NPM_REGISTRY="$CORPORATIVE_NPM_REGISTRY" \
CORPORATIVE_PROXY="$CORPORATIVE_PROXY" \
ENV_FILE="$ENV_FILE" \
./scripts/write_env.sh >/dev/null

pf_ensure_venv "$VENV" "import rates, fastapi, asyncpg, pydantic_settings, sqlalchemy, uvicorn"

pf_print_startup_banner "$APP_PORT" "$ENV_FILE"

exec "$VENV/bin/uvicorn" rates.interfaces.api.main:app --reload --host 127.0.0.1 --port "$APP_PORT"
