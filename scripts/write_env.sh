#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${ENV_FILE:-.env}"
PF_DATABASE_URL="${PF_DATABASE_URL:-postgresql+asyncpg://pf_db:pf_db@localhost:5432/pf_db}"
PF_RATES_API_KEY="${PF_RATES_API_KEY:-change-me-before-use}"
CORPORATIVE_PIP_INDEX="${CORPORATIVE_PIP_INDEX:-}"
CORPORATIVE_NPM_REGISTRY="${CORPORATIVE_NPM_REGISTRY:-}"
CORPORATIVE_PROXY="${CORPORATIVE_PROXY:-}"

{
  printf '# Database managed by pf-db (shared with pf-payroll)\n'
  printf 'PF_DATABASE_URL=%s\n' "$PF_DATABASE_URL"
  printf '\n# API key that clients must supply as X-API-Key header to access this service.\n'
  printf 'PF_RATES_API_KEY=%s\n' "$PF_RATES_API_KEY"
  printf '\n# Tooling — corporate pip/npm registries (used by make install/check on VPN)\n'
  printf 'CORPORATIVE_PIP_INDEX=%s\n' "$CORPORATIVE_PIP_INDEX"
  printf 'CORPORATIVE_NPM_REGISTRY=%s\n' "$CORPORATIVE_NPM_REGISTRY"
  printf 'CORPORATIVE_PROXY=%s\n' "$CORPORATIVE_PROXY"
} > "$ENV_FILE"

printf '%s\n' "$ENV_FILE"
