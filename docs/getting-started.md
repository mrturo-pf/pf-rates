# Getting Started

Quick installation and setup guide for pf-rates local development.

## Prerequisites

- **Python 3.12+** with `uv` or `pip`
- **Docker Desktop** (for pf-db PostgreSQL)
- **Git** (for cloning the repository)

## Step 1: Clone the repository

```bash
git clone <repository-url> pf-rates
cd pf-rates
```

## Step 2: Install dependencies

```bash
make install
```

This will:
- Create a virtual environment in `.venv/`
- Install all dependencies from `pyproject.toml`
- Configure git hooks (pre-commit, pre-push)

## Step 3: Start the database

pf-rates does not manage its own database. Start the shared PostgreSQL instance from [pf-db](../../pf-db):

```bash
cd ../pf-db
make local-up        # start postgres + apply schema + load base seed
```

See [Database Guide](database.md) for more details.

## Step 4: Configure environment

Generate `.env` with default local values:

```bash
cd ../pf-rates
make env-write
```

This creates `.env` from `.env.example`. **Important:** Edit `.env` and set a secure API key:

```bash
# Edit .env
PF_RATES_API_KEY=your-secure-api-key-here
```

The API key is required for all authenticated endpoints (all except `/health`).

## Step 5: Run the service

```bash
make run
```

The FastAPI service starts on **port 8001** with auto-reload enabled.

## Step 6: Verify installation

### Option A: Swagger UI (Browser)

Open your browser and navigate to:

```
http://localhost:8001/docs
```

1. Click **Authorize** button (top right)
2. Enter your `PF_RATES_API_KEY` from `.env`
3. Click **Authorize** then **Close**
4. Try the `GET /currencies` endpoint

### Option B: curl (Terminal)

```bash
# Health check (no auth required)
curl http://localhost:8001/health

# List currencies (requires API key)
curl -H "X-API-Key: your-api-key-here" http://localhost:8001/currencies

# Get UF value for a specific month
curl -H "X-API-Key: your-api-key-here" \
  "http://localhost:8001/economic-indices/value?code=UF&year=2024&month=1"
```

Expected response for `/currencies`:

```json
[
  {"code": "USD", "name": "United States Dollar"},
  {"code": "EUR", "name": "Euro"}
]
```

## Step 7: Run tests

```bash
make test
```

This runs all unit and integration tests. For coverage:

```bash
make test-cov
```

Expected output: 100% coverage on `src/`.

## Next steps

- [Development Guide](development.md) - Make commands, testing, git hooks
- [API Reference](api.md) - Complete endpoint documentation
- [Database Guide](database.md) - Schema, tables, local setup
- [Deployment Guide](deployment.md) - CI/CD, Cloud Run deployment

## Troubleshooting

### `make install` fails

**Error:** `uv not found` or `pip install fails`

**Solution:**
```bash
# Option 1: Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Option 2: Use pip directly
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Database connection error

**Error:** `could not connect to server`

**Solution:** Ensure pf-db postgres is running:
```bash
cd ../pf-db
docker ps | grep pf-db-postgres
# If not running:
make local-up
```

### Port 8001 already in use

**Error:** `Address already in use`

**Solution:**
```bash
# Find process using port 8001
lsof -i :8001
# Kill it
kill -9 <PID>
# Or use a different port
uvicorn financial_data.interfaces.api.main:app --port 8002 --reload
```

### API key not working

**Error:** `403 Forbidden` when calling endpoints

**Solution:**
1. Check `.env` file contains `PF_RATES_API_KEY=...`
2. Restart the service after editing `.env`
3. In Swagger UI, use the **Authorize** button (not query param)
4. In curl, use header: `-H "X-API-Key: your-key"`

## Interactive Documentation

Once running, access:

- **Swagger UI:** `http://localhost:8001/docs` (interactive API explorer)
- **ReDoc:** `http://localhost:8001/redoc` (alternative documentation view)

Both provide the same API specification but with different UIs.
