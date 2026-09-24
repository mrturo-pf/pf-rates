# Development Guide

Local development workflow, testing conventions, and contribution guidelines for pf-rates.

## Prerequisites

1. **Python 3.12+** with `uv` or `pip`
2. **pf-db running** — see [Database Setup](#database-setup)
3. **Virtual environment** — created by `make install`

## Development commands

All commands assume you're in an activated virtualenv:

```bash
source .venv/bin/activate
```

Or prefix with the virtualenv path:

```bash
PATH=.venv/bin:$PATH make <target>
```

### Common workflows

| Command | Description |
|---|---|
| `make install` | Create `.venv`, install dependencies, configure git hooks |
| `make local-up` | Check pf-db is running, write `.env`, install deps, start API |
| `make env-write` | Regenerate `.env` with default local DB values |
| `make check` | **Full validation** — lint → dead-code → typecheck → dup-check → test → test-cov |
| `make run` | Start FastAPI with auto-reload (port 8001) |

### Quality checks (individual)

| Command | Tool | Purpose |
|---|---|---|
| `make lint` | ruff | Check style + format code |
| `make dead-code` | vulture | Detect unused code |
| `make typecheck` | mypy | Static type checking |
| `make duplicate-code-src` | jscpd | Detect duplication in `src/` (fail > 0.5%) |
| `make duplicate-code-tests` | jscpd | Detect duplication in `tests/` (fail > 2%) |
| `make test` | pytest | Run all tests (unit + integration) |
| `make test-cov` | pytest | Run tests + generate coverage report (fail < 100%) |

### Database setup

pf-rates **does not manage its own database**. Start the shared PostgreSQL instance from the [pf-db](../pf-db) repository:

```bash
cd ../pf-db
make local-up        # start postgres + apply schema + load base seed
```

Then start pf-rates:

```bash
cd ../pf-rates
make local-up        # verifies pf-db is running, writes .env, runs API
```

See [Database Guide](database.md) for connection details and table ownership.

## Git hooks

Installed automatically by `make install` via `git config core.hooksPath .githooks`:

| Hook | Runs | Bypass |
|---|---|---|
| `pre-commit` | lint · dead-code · typecheck | `git commit --no-verify` |
| `pre-push` | duplicate-code-src · duplicate-code-tests | `git push --no-verify` |

**Never bypass hooks without justification.** They enforce the same checks that run in CI.

## Testing conventions

### Structure

- `tests/unit/` — no DB, no network; fast, isolated
- `tests/integration/` — live PostgreSQL via testcontainers
- `tests/conftest.py` — pytest fixtures and configuration

### No Mock library

We use **hand-rolled stub classes** per test file. See `tests/unit/application/test_refresh_rates.py` for the canonical pattern:

```python
class StubMarketDataRepository:
    def __init__(self) -> None:
        self.command: RefreshRatesCommandDTO | None = None
    
    async def refresh_rates(self, command: RefreshRatesCommandDTO) -> RefreshRatesResultDTO:
        self.command = command
        return RefreshRatesResultDTO(...)
```

**Why stubs over mocks?**
- More explicit: you see exactly what the stub does
- Type-safe: mypy catches stub mismatches
- No magic: no `MagicMock`, `patch`, or `assert_called_with`

### Test requirements

- **Verify meaningful outputs** — return values, state, errors — not just that methods were called
- **Mark async tests** — `@pytest.mark.asyncio` (`asyncio_mode = "strict"` in `pyproject.toml`)
- **100% coverage required** for `src/` — `make test-cov` fails below 100%
- **Shared fixtures** — go in `tests/conftest.py`, never duplicate

### Integration tests and pf-db

Integration tests bootstrap a throwaway PostgreSQL container via testcontainers, loading SQL fixtures **directly from the pf-db repository**:

```python
# tests/integration/conftest.py
PF_DB_PATH = os.getenv("PF_DB_PATH", "../pf-db")
schema_sql = Path(PF_DB_PATH) / "db" / "01_schema.sql"
seed_sql = Path(PF_DB_PATH) / "db" / "02_seed_base.sql"
```

**Local:** Set `PF_DB_PATH=../pf-db` in `.env` (default assumes sibling repos)

**CI:** The `test` job checks out `mrturo/pf-db` into `_pf-db/` and sets `PF_DB_PATH=_pf-db`

### Running tests

```bash
# All tests (unit + integration)
make test

# With coverage report
make test-cov

# Run specific test file
pytest tests/unit/domain/test_quantizers.py

# Run specific test
pytest tests/unit/domain/test_quantizers.py::test_quantize_clp

# Skip slow integration tests
pytest -m "not integration"
```

## Adding a new use case

Follow this sequence to add new functionality:

1. **Define or extend a port** in `application/ports/` using `Protocol`
   ```python
   from typing import Protocol
   
   class MarketDataRepository(Protocol):
       async def find_exchange_rate(self, currency: str, date: date) -> ExchangeRate | None: ...
   ```

2. **Create use case** in `application/use_cases/` — constructor takes port interfaces only
   ```python
   class GetExchangeRate:
       def __init__(self, repository: MarketDataRepository) -> None:
           self._repository = repository
   ```

3. **Add DTOs** to `application/dto.py`
   ```python
   @dataclass(frozen=True, slots=True)
   class ExchangeRateDTO:
       currency_code: str
       rate_date: date
       value_clp: Decimal
   ```

4. **Wire dependency** in `interfaces/api/dependencies.py`
   ```python
   def get_market_data_repository() -> MarketDataRepository:
       return SqlAlchemyMarketDataRepository(SessionLocal)
   ```

5. **Add route** in `interfaces/api/routes/`
   ```python
   @router.get("/exchange-rates/{currency}")
   async def get_rate(
       currency: str,
       rate_date: date,
       repository: MarketDataRepository = Depends(get_market_data_repository)
   ):
       use_case = GetExchangeRate(repository)
       return await use_case.execute(currency, rate_date)
   ```

6. **Add stub-based unit test** in `tests/unit/application/`
   ```python
   class StubMarketDataRepository:
       # ... stub implementation
   
   async def test_get_exchange_rate():
       stub_repo = StubMarketDataRepository()
       use_case = GetExchangeRate(stub_repo)
       result = await use_case.execute("USD", date(2024, 1, 15))
       assert result.currency_code == "USD"
   ```

7. **Run validation** — `make check` must pass clean

> **Note:** Schema changes (new tables/columns) are managed exclusively by [pf-db](../pf-db). Coordinate with pf-db maintainers if your use case requires database modifications.

## Code style

See [AGENTS.md](../AGENTS.md) sections:
- **Language policy** — English only (except Chilean regulatory terms)
- **Code style** — ruff configuration, docstrings, PEPs
- **Design principles** — DRY, SOLID, Clean Code, DDD
- **Financial precision** — always `Decimal`, never `float`

## Debugging

### API debugging

Start the API with auto-reload:

```bash
make run
# API available at http://localhost:8001
# Swagger UI at http://localhost:8001/docs
```

Add breakpoints in your IDE or use `breakpoint()` in the code.

### Testing external providers

pf-rates integrates with external data sources (Mindicador, BCCH). For local testing:

**Option 1: Use stubs**
```python
class StubMindicadorProvider:
    async def fetch_exchange_rates(self, date: date) -> list[ExchangeRateDTO]:
        return [ExchangeRateDTO(currency_code="USD", rate_date=date, value_clp=Decimal("900.00"))]
```

**Option 2: Use real providers with rate limiting**
```bash
# Set BCCH credentials in .env
FINANCIAL_DATA_BCCH_API_USER=your-user
FINANCIAL_DATA_BCCH_API_PASSWORD=your-password

# Start API
make run

# Test /sync endpoint (fetches real data)
curl -X POST -H "X-API-Key: your-key" http://localhost:8001/sync
```

#### Corporate network gotcha (VPN)

On a corporate-managed machine, hitting the real providers (mindicador.cl,
sii.cl) from a shell that still carries VPN leftovers usually fails in one
of two ways:

- **DNS blackhole while connected to the VPN**: the corporate resolver
  returns `NXDOMAIN` for `mindicador.cl` / `sii.cl` (`urlopen error [Errno 8]
  nodename nor servname provided, or not known`). Public DNS (`8.8.8.8`) is
  also blocked by the corporate firewall, so there's no bypass — the VPN
  needs to be disconnected.
- **TLS failure once disconnected**: if `SSL_CERT_FILE` is set in your shell
  to a corporate-only CA bundle (common on corporate-managed dev tooling),
  TLS verification fails with `CERTIFICATE_VERIFY_FAILED: unable to get
  local issuer certificate` — that bundle doesn't include the public CAs
  that sign `mindicador.cl` / `sii.cl` certificates.

Don't fight this locally. Production (the deployed Cloud Run instance)
always keeps its DB current by calling `/sync` itself, so the supported
local path is pulling that already-synced data down instead of hitting
mindicador.cl/sii.cl yourself from a corporate-managed machine:

```bash
cd ../pf-db
./scripts/export-neon-dump.sh    # run with the corporate VPN DISCONNECTED
./scripts/restore-neon-dump.sh   # run with the VPN reconnected
```

See `pf-db`'s `scripts/` for details. There is deliberately no local
script that relaunches pf-rates to call the real providers directly
anymore — an earlier version of that approach (restarting the local
process with a clean TLS/proxy env) was unreliable with `make run`'s
`uvicorn --reload` reloader/worker split, and duplicated what the
export/restore scripts already do more reliably straight from the source
of truth.

### Database inspection

See [Database Guide](database.md#inspection) for psql and Adminer usage.

## Troubleshooting

### `make check` fails

Run individual checks to isolate the issue:

```bash
make lint           # Style/formatting issues
make dead-code      # Unused code
make typecheck      # Type errors
make duplicate-code-src  # Code duplication in src/
make test           # Test failures
make test-cov       # Coverage below 100%
```

### Database connection errors

Ensure pf-db is running:

```bash
cd ../pf-db
docker ps | grep pf-db-postgres
# If not running:
make local-up
```

### Integration tests fail: "PF_DB_PATH not found"

**Cause:** Integration tests cannot find SQL fixtures from pf-db.

**Solution:**
```bash
# Set PF_DB_PATH in .env
echo "PF_DB_PATH=../pf-db" >> .env

# Or export it
export PF_DB_PATH=../pf-db
pytest
```

### Import errors after adding dependencies

```bash
make reinstall      # Wipe caches and reinstall all dependencies
```

### External provider timeout

**Cause:** Mindicador or BCCH API is slow or unavailable.

**Solution:**
1. Check provider status manually (browse to mindicador.cl)
2. Increase timeout in `infrastructure/providers/`
3. Use stub providers for local development

### `/sync` returns 0 upserted on a corporate-managed machine

**Cause:** Corporate VPN/network leftovers in the shell that launched
`pf-rates` — either DNS blackholing `mindicador.cl`/`sii.cl` (while
connected), or a corporate-only `SSL_CERT_FILE` breaking TLS verification
against those public sites (once disconnected). See
[Corporate network gotcha](#corporate-network-gotcha-vpn) above for the
full diagnosis.

**Solution:** don't sync locally — pull already-synced data from Neon
instead via `pf-db/scripts/export-neon-dump.sh` +
`pf-db/scripts/restore-neon-dump.sh`. See
[Corporate network gotcha](#corporate-network-gotcha-vpn) above.

## Continuous Integration

All PRs and pushes to `main` run `make check` in CI. See [Deployment Guide](deployment.md) for the full pipeline.
