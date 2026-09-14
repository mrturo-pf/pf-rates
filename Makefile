# ============================================================================
# pf-rates - Chilean financial reference data microservice
# ============================================================================

# Service configuration (REQUIRED by common.mk)
APP_PORT := 8001
APP_MODULE := rates.interfaces.api.main:app

# Include shared targets from pf-common/
include ../pf-common/make/common.mk

# ============================================================================
# Service-specific variables
# ============================================================================

DB_CONTAINER ?= pf-db-db-1
PF_DATABASE_URL ?= postgresql+asyncpg://pf_db:pf_db@localhost:5432/pf_db
PF_RATES_API_KEY ?= change-me-before-use

# ============================================================================
# Service-specific targets
# ============================================================================

.PHONY: env-write
env-write: ## Write .env file with service-specific defaults
	@printf 'PF_DATABASE_URL=$(PF_DATABASE_URL)\n' > $(ENV_FILE)
	@printf '\n# API key that clients must supply as X-API-Key header to access this service.\n' >> $(ENV_FILE)
	@printf 'PF_RATES_API_KEY=$(PF_RATES_API_KEY)\n' >> $(ENV_FILE)
	@printf '\n# Tooling — corporate pip/npm registries (used by make install/check on VPN)\n' >> $(ENV_FILE)
	@printf 'CORPORATIVE_PIP_INDEX=https://pypi.ci.artifacts.corporative.com/artifactory/api/pypi/pythonhosted-pypi-release-remote/simple\n' >> $(ENV_FILE)
	@printf 'CORPORATIVE_NPM_REGISTRY=https://npm.ci.artifacts.corporative.com/artifactory/api/npm/external-npm\n' >> $(ENV_FILE)
	@printf 'CORPORATIVE_PROXY=http://sysproxy.corpo-rative.com:8080\n' >> $(ENV_FILE)
	@printf '\n# Rate provider HTTP proxy (optional — leave unset for direct connections).\n' >> $(ENV_FILE)
	@printf '# Set to the corporate proxy when the external APIs are only reachable via VPN proxy.\n' >> $(ENV_FILE)
	@printf '#FINANCIAL_DATA_HTTP_PROXY=http://proxy.corpo-rative.com:8080\n' >> $(ENV_FILE)
	@echo "  $(ENV_FILE) written"

.PHONY: local-up
local-up: ## Start full local stack (DB verification, env, deps, API)
	APP_PORT="$(APP_PORT)" \
		VENV="$(VENV)" ENV_FILE="$(ENV_FILE)" \
		DB_CONTAINER="$(DB_CONTAINER)" \
		PF_DATABASE_URL="$(PF_DATABASE_URL)" \
		PF_RATES_API_KEY="$(PF_RATES_API_KEY)" \
		CORPORATIVE_PIP_INDEX="$(CORPORATIVE_PIP_INDEX)" \
		CORPORATIVE_NPM_REGISTRY="$(CORPORATIVE_NPM_REGISTRY)" \
		CORPORATIVE_PROXY="$(CORPORATIVE_PROXY)" \
		./scripts/local_stack.sh
