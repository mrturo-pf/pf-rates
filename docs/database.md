# Database Guide

Database connection, schema ownership, and local development workflow for pf-rates.

## Overview

pf-rates **does not manage its own database**. Schema and migrations are owned by **[pf-db](../../pf-db)** - a separate repository that serves as the single source of truth for all PostgreSQL objects shared across the PF ecosystem.

**Key facts:**
- pf-rates only holds **SQLAlchemy ORM models** and **repositories**
- Schema changes require a migration in **pf-db** (coordinate with pf-db maintainers)
- Local development uses a shared PostgreSQL instance managed by pf-db
- Production uses the same shared database (Neon, Supabase, or Cloud SQL)

## Connection

### Environment variable

The database connection is configured via the `PF_DATABASE_URL` environment variable:

```bash
# Local (default in .env.example)
PF_DATABASE_URL=postgresql+asyncpg://pf_db:pf_db@localhost:5432/pf_db

# Production (injected via Secret Manager)
PF_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname
```

### Session management

All database access uses **async sessions** via `infrastructure/db/session.py`:

```python
from financial_data.infrastructure.db.session import SessionLocal

async with SessionLocal() as session:
    # Use session here
    result = await session.execute(select(Currency))
```

**Never create sessions manually** - always use `SessionLocal()` context manager.

## Local database setup

### Step 1: Start pf-db

Navigate to the pf-db repository and start the PostgreSQL container:

```bash
cd ../pf-db
make local-up        # start postgres + apply schema + load base seed
```

This starts a PostgreSQL 16 container on `localhost:5432` with:
- All tables created
- Base seed data loaded (currencies, institutions, caps, brackets, concepts)

### Step 2: Start pf-rates

Navigate back to pf-rates and start the service:

```bash
cd ../pf-rates
make local-up        # verifies pf-db is running, writes .env, runs API
```

The `make local-up` target:
1. Checks if pf-db postgres is running (fails if not)
2. Writes `.env` with default local values if it doesn't exist
3. Installs dependencies if `.venv` is missing
4. Starts the FastAPI server

## Table ownership

pf-rates **owns** the following tables (writes allowed):

| Table | Description |
|---|---|
| `currencies` | Supported currencies (USD, EUR) |
| `exchange_rates` | Historical exchange rates (CLP value) |
| `economic_indices` | Economic indices (UF, UTM, IPC) |
| `income_tax_brackets` | Tax brackets for payroll calculation |

**Ownership means:**
- pf-rates can INSERT, UPDATE, DELETE on these tables
- Other services (e.g., pf-payroll) access this data via **pf-rates HTTP API** (never direct SQL)

## ORM models

SQLAlchemy models live in `infrastructure/db/models/financial_data.py`:

### Example: Currency model

```python
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from financial_data.infrastructure.db.models.base import Base

class Currency(Base):
    __tablename__ = "currencies"
    
    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
```

### Example: ExchangeRate model

```python
from decimal import Decimal
from datetime import date
from sqlalchemy import String, Date, Numeric, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

class ExchangeRate(Base):
    __tablename__ = "exchange_rates"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    currency_code: Mapped[str] = mapped_column(String(3), ForeignKey("currencies.code"))
    rate_date: Mapped[date] = mapped_column(Date, nullable=False)
    value_clp: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
```

## Repositories

Repositories implement **port Protocols** from `application/ports/` and live in `infrastructure/db/repositories/`.

### Example: MarketDataRepository

```python
from financial_data.application.ports.market_data_repository import MarketDataRepository
from financial_data.infrastructure.db.session import SessionLocal

class SqlAlchemyMarketDataRepository:
    """Implementation of MarketDataRepository using SQLAlchemy."""
    
    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory
    
    async def find_exchange_rate(self, currency: str, rate_date: date) -> ExchangeRate | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ExchangeRateModel).where(
                    ExchangeRateModel.currency_code == currency,
                    ExchangeRateModel.rate_date == rate_date
                )
            )
            model = result.scalar_one_or_none()
            return self._to_entity(model) if model else None
```

## Schema changes

**Never edit ORM models without a corresponding pf-db migration.**

To add a new column or table:

1. **Coordinate with pf-db maintainers** (or create the migration yourself if you own both repos)
2. **Add migration** in `pf-db/alembic/versions/NNNN_description.py`:
   ```python
   def upgrade() -> None:
       op.execute("""
           ALTER TABLE currencies 
           ADD COLUMN symbol VARCHAR(5);
       """)
   
   def downgrade() -> None:
       op.execute("""
           ALTER TABLE currencies 
           DROP COLUMN symbol;
       """)
   ```
3. **Apply migration** locally:
   ```bash
   cd ../pf-db
   make migrate
   ```
4. **Update ORM model** in pf-rates:
   ```python
   class Currency(Base):
       # ...
       symbol: Mapped[str | None] = mapped_column(String(5), nullable=True)
   ```
5. **Run tests** - ensure integration tests pass
6. **Commit both repos** - pf-db migration first, then pf-rates model change

## Inspection

### Using psql

Connect to the local database:

```bash
docker exec -it pf-db-postgres psql -U pf_db -d pf_db
```

Common queries:

```sql
-- List all tables
\dt

-- Describe a table
\d currencies

-- Count exchange rates
SELECT COUNT(*) FROM exchange_rates;

-- Show recent rates
SELECT * FROM exchange_rates ORDER BY rate_date DESC LIMIT 10;

-- Get UF value for a specific month
SELECT * FROM economic_indices 
WHERE code = 'UF' AND year = 2024 AND month = 1;
```

### Using Adminer

Start the Adminer web UI (from pf-db):

```bash
cd ../pf-db
make adminer-up
# Open http://localhost:8081
```

Login:
- System: `PostgreSQL`
- Server: `pf-db-postgres`
- Username: `pf_db`
- Password: `pf_db`
- Database: `pf_db`

## SQL test fixtures

Integration tests read SQL fixtures **directly from the pf-db repository**:

```python
# tests/conftest.py
PF_DB_PATH = os.getenv("PF_DB_PATH", "../pf-db")

schema_sql = Path(PF_DB_PATH) / "db" / "01_schema.sql"
seed_sql = Path(PF_DB_PATH) / "db" / "02_seed_base.sql"
```

**Local development:**
- Set `PF_DB_PATH=../pf-db` in `.env` (default assumes sibling repos)

**CI:**
- The `test` job checks out `mrturo/pf-db` into `_pf-db/`
- Sets `PF_DB_PATH=_pf-db` environment variable

This ensures integration tests always use the **same schema and seed data** as production.

## Troubleshooting

### Connection errors: "could not connect to server"

**Cause:** pf-db postgres container is not running.

**Solution:**
```bash
cd ../pf-db
docker ps | grep pf-db-postgres
# If not running:
make local-up
```

### Migration errors: "relation does not exist"

**Cause:** pf-db migrations not applied.

**Solution:**
```bash
cd ../pf-db
make migrate  # applies all pending migrations
```

### Integration tests fail: "testcontainers timeout"

**Cause:** Docker daemon not running or resource constraints.

**Solution:**
1. Ensure Docker Desktop is running
2. Increase Docker memory limit (Preferences to Resources to Memory to 4 GB+)
3. Check Docker logs: `docker ps -a`

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

### ORM model out of sync with database

**Cause:** Database schema changed without updating ORM model.

**Solution:**
1. Check latest pf-db migrations: `cd ../pf-db && git log --oneline alembic/versions/`
2. Update ORM model to match schema
3. Run `make typecheck` to catch type errors

## Production database

In production, pf-rates connects to the same shared database instance managed by pf-db.

**Database options:**
- **External** (Neon, Supabase): Set `PF_DATABASE_URL` secret in Secret Manager
- **Cloud SQL**: Set `PF_DATABASE_URL` + `GCP_CLOUD_SQL_INSTANCE` secret

**Migrations:** The `pf-db` Cloud Run Job applies `alembic upgrade head` before any service receives traffic. See [Deployment Guide](deployment.md#pipeline-invariants) for details.

## Data flow

```
External Sources (Mindicador, BCCH)
  |
  v
pf-rates (/refresh endpoints)
  |
  v
PostgreSQL (pf-db tables: currencies, exchange_rates, economic_indices, income_tax_brackets)
  |
  v
pf-rates (GET /currencies, /exchange-rates, /economic-indices, /income-tax-brackets)
  |
  v
pf-payroll (HTTP client, never direct SQL)
```

pf-rates is the **single writer** to its owned tables. Other services are **read-only consumers via HTTP API**.

## See also

- [pf-db README](../../pf-db/README.md) - Database repository overview
- [pf-db AGENTS.md](../../pf-db/AGENTS.md) - Migration workflow and invariants
- [Development Guide](development.md#database-setup) - Local database setup
- [Deployment Guide](deployment.md#github-secrets) - Production database configuration
- [API Reference](api.md) - Endpoints for accessing financial data
