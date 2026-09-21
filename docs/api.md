# API Reference

Complete endpoint documentation for pf-rates: authentication, endpoints, request/response formats, and examples.

## Base URL

**Local development:**
```
http://localhost:8001
```

**Production:**
```
https://pf-rates-<hash>-uc.a.run.app
```

## Authentication

All endpoints except `GET /health` require the `X-API-Key` header.

### Setting the API key

**Swagger UI:**
1. Open `http://localhost:8001/docs`
2. Click **Authorize** button (top right)
3. Enter your API key from `.env` (`PF_RATES_API_KEY`)
4. Click **Authorize** then **Close**

**curl:**
```bash
curl -H "X-API-Key: your-api-key-here" http://localhost:8001/currencies
```

**Python requests:**
```python
import requests

headers = {"X-API-Key": "your-api-key-here"}
response = requests.get("http://localhost:8001/currencies", headers=headers)
```

### Response codes

| Code | Meaning |
|---|---|
| `200` | Success |
| `401` | Missing or invalid `X-API-Key` |
| `404` | Resource not found |
| `422` | Validation error (invalid parameters) |
| `500` | Internal server error |

## Endpoints

### Health Check

**GET /health**

Service liveness check. No authentication required.

**Response:**
```json
{"status": "ok"}
```

**Example:**
```bash
curl http://localhost:8001/health
```

---

### Currencies

**GET /currencies**

List all supported currencies.

**Authentication:** Required

**Response:**
```json
[
  {"code": "USD", "name": "United States Dollar"},
  {"code": "EUR", "name": "Euro"}
]
```

**Example:**
```bash
curl -H "X-API-Key: your-key" http://localhost:8001/currencies
```

---

### Exchange Rates

#### List exchange rates

**GET /exchange-rates**

List all exchange rates, optionally filtered by currency.

**Authentication:** Required

**Query Parameters:**
- `currency_code` (optional): Filter by currency (e.g., `USD`)

**Response:**
```json
[
  {
    "id": 1,
    "currency_code": "USD",
    "rate_date": "2024-01-15",
    "value_clp": "897.5000"
  },
  {
    "id": 2,
    "currency_code": "USD",
    "rate_date": "2024-01-16",
    "value_clp": "895.2000"
  }
]
```

**Example:**
```bash
# All rates
curl -H "X-API-Key: your-key" http://localhost:8001/exchange-rates

# USD only
curl -H "X-API-Key: your-key" http://localhost:8001/exchange-rates?currency_code=USD
```

#### Get exchange rate value

**GET /exchange-rates/value**

Get the CLP value for a currency on a specific date.

**Authentication:** Required

**Query Parameters:**
- `currency_code` (required): Currency code (e.g., `USD`)
- `rate_date` (required): Date in `YYYY-MM-DD` format

**Response:**
```json
{
  "currency_code": "USD",
  "rate_date": "2024-01-15",
  "value_clp": "897.5000"
}
```

**Example:**
```bash
curl -H "X-API-Key: your-key" \
  "http://localhost:8001/exchange-rates/value?currency_code=USD&rate_date=2024-01-15"
```

#### Refresh exchange rates

**POST /exchange-rates/refresh**

Upsert exchange rates, either from values you supply yourself ("manual"
entries) or by asking pf-rates to fetch the value from its configured
provider chain for you ("provider fetch" entries). Both can be combined
in the same request; if the same `(currency_code, rate_date)` pair
appears in both lists, the manual entry wins.

**Authentication:** Required

**Request Body:**
```json
{
  "exchange_rates": [
    {
      "currency_code": "USD",
      "rate_date": "2024-01-15",
      "value_clp": "897.5000",
      "source": "manual"
    }
  ],
  "fetch_exchange_rates": [
    { "currency_code": "USD", "rate_date": "2024-01-16" }
  ]
}
```

Both arrays default to empty and are optional individually, but at least
one entry (in either array) is required across the whole request.
`exchange_rates[].source` defaults to `"manual"` if omitted.

**Response** (same shape for `/exchange-rates/refresh` and
`/economic-indices/refresh` -- see `RefreshRatesResponse`; whichever
field doesn't apply to the endpoint you called is always `0`):
```json
{
  "upserted_exchange_rates": 2,
  "upserted_economic_indices": 0
}
```

**Errors:**
- `400` if neither `exchange_rates` nor `fetch_exchange_rates` has any entries.
- `502` if a `fetch_exchange_rates` entry can't be resolved by any
  configured provider. **The whole request is rejected and nothing is
  persisted** -- even entries earlier in the same request that resolved
  fine. For a large batch (e.g. a multi-year historical backfill), split
  it into smaller requests (e.g. one per year) so one bad date doesn't
  discard an otherwise-successful batch.
- `503` if `fetch_exchange_rates` has entries but no provider chain is configured.

**Example (manual entry):**
```bash
curl -X POST -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"exchange_rates": [{"currency_code": "USD", "rate_date": "2024-01-15", "value_clp": "897.50"}]}' \
  http://localhost:8001/exchange-rates/refresh
```

**Example (provider fetch -- pf-rates resolves the value itself):**
```bash
curl -X POST -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"fetch_exchange_rates": [{"currency_code": "USD", "rate_date": "2024-01-16"}]}' \
  http://localhost:8001/exchange-rates/refresh
```

#### Export combined exchange-rate + economic-index data to Google Drive

**POST /exports/financial-data**

Build a single CSV covering both exchange rates (RAT_EXCH_RATE) and
economic indices (RAT_ECON_INDEX) and upload it to a pre-configured
Google Drive folder. This is the only CSV-export trigger endpoint
pf-rates exposes -- the original exchange-rates-only
`POST /exchange-rates/export` was removed once `pf-sheets` fully
migrated to this combined export.

Requires `PF_RATES_GDRIVE_EXPORT_FOLDER_ID` to be configured, and that
folder shared as Editor with the service's identity (see `.env.example`
for local dev, [`deployment.md`](deployment.md) for production, and
[`google-drive-credentials-setup.md`](google-drive-credentials-setup.md)
for the full setup and its accepted trade-off).

**Authentication:** Required

CSV shape (uniform across both series types):
```
series_type,code,period_date,value
EXCHANGE_RATE,USD,2024-06-14,950.12
ECONOMIC_INDEX,IPC_CL,2024-06-14,125.50
```

`series_type` is `EXCHANGE_RATE` or `ECONOMIC_INDEX`. Exchange-rate rows
are resolved for every non-CLP currency/index (`USD`, `EUR`, `UF`, `UTM`)
across the requested rolling window, using the same fallback chain as
`GET /exchange-rates/value`; dates that cannot be resolved (mostly future
dates for `USD`/`EUR`) are simply omitted from the CSV. Economic-index
rows are expanded from RAT_ECON_INDEX's monthly storage to one row per
calendar day in the window -- the same pattern used for `UTM` --
repeating that month's value for every day in it. A month with nothing
stored simply has its days omitted from the CSV, same "omit what can't
be resolved" behavior exchange rates already use.

**Request Body** (all fields optional):
```json
{
  "lookback_days": 90,
  "forward_days": 30,
  "async": false
}
```

Set the async field to true to trigger the export in the background
instead of waiting for it (see below) -- recommended for large windows
(e.g. a multi-year historical backfill), where a synchronous call risks
the request timing out before the CSV finishes uploading. Async jobs
from this endpoint are monitored through the `GET/POST /exports/jobs/...`
endpoints.

**Response (synchronous, default):**
```json
{
  "rows_written": 412,
  "file_id": "1AbCdEfGhIjKlMnOpQrStUvWxYz"
}
```

**Response (async mode -- 202 Accepted):**
```json
{
  "job_id": 42,
  "status": "pending",
  "monitor_url": "/exports/jobs/42"
}
```

**Errors:**
- `503` if Google Drive export is not configured yet -- either
  `PF_RATES_GDRIVE_EXPORT_FOLDER_ID` is unset/the folder isn't shared as
  Editor with the service's identity, or no Application Default
  Credentials are available (see
  [`google-drive-credentials-setup.md`](google-drive-credentials-setup.md)).
  Both preconditions map to the same 503 so callers see one consistent
  "not configured" failure mode either way. Returned immediately even in
  async mode, before any job row is created -- a job would otherwise be
  guaranteed to fail as soon as it ran in the background.

**Example (synchronous):**
```bash
curl -X POST -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{}' \
  http://localhost:8001/exports/financial-data
```

**Example (async, large historical backfill):**
```bash
curl -X POST -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"lookback_days": 6100, "forward_days": 30, "async": true}' \
  http://localhost:8001/exports/financial-data
```

#### Check an async export job status

**GET /exports/jobs/{job_id}**

Return the current state of a previously-triggered async export job.
Status is one of pending, running, succeeded, failed, cancelled. Job state is
persisted in Postgres (RAT_EXPORT_JOB), not in process memory, so it
survives Cloud Run scaling to zero or routing the poll to a different
instance than the one that ran the job.

While a job is running, `processed_items`/`total_items`/`progress_percent`
report how far the export loop has gotten. `total_items` is the number of
(currency, date) pairs the run will visit, resolved once at the start of
execution; `progress_percent` is derived from the two counts on every
response rather than stored directly, so it can never drift out of sync
with them. Both item counts are `null`/`0` before a job starts running and
hold their final value once a job reaches a terminal status.

**Authentication:** Required

**Response:**
```json
{
  "job_id": 42,
  "status": "succeeded",
  "lookback_days": 6100,
  "forward_days": 30,
  "rows_written": 13429,
  "file_id": "1AbCdEfGhIjKlMnOpQrStUvWxYz",
  "error_message": null,
  "cancel_requested_at": null,
  "total_items": 24404,
  "processed_items": 24404,
  "progress_percent": 100.0,
  "created_at": "2026-09-13T18:00:00Z",
  "updated_at": "2026-09-13T18:04:12Z"
}
```

While it is still running, the same shape looks like this instead:
```json
{
  "job_id": 42,
  "status": "running",
  "lookback_days": 6100,
  "forward_days": 30,
  "rows_written": null,
  "file_id": null,
  "error_message": null,
  "cancel_requested_at": null,
  "total_items": 24404,
  "processed_items": 9750,
  "progress_percent": 40.0,
  "created_at": "2026-09-13T18:00:00Z",
  "updated_at": "2026-09-13T18:02:31Z"
}
```

**Errors:**
- `404` if no job exists with that id.

**Example:**
```bash
curl -H "X-API-Key: your-key" \
  http://localhost:8001/exports/jobs/42
```

---

### Export job management

#### List export jobs

**GET /exports/jobs**

List export jobs, newest first, optionally filtered by status and/or a
`created_at` date range. Backed by the same `RAT_EXPORT_JOB` table. Each
entry has the same shape as the single-job GET above, including
`processed_items`/`total_items`/`progress_percent` for whichever jobs are
currently `running`.

**Authentication:** Required

**Query parameters** (all optional):
| Param | Type | Notes |
|---|---|---|
| `status` | string | One of `pending`, `running`, `succeeded`, `failed`, `cancelled`. `400` if anything else. |
| `created_from` | ISO 8601 datetime | Inclusive lower bound on `created_at`. |
| `created_to` | ISO 8601 datetime | Inclusive upper bound on `created_at`. |
| `limit` | int | Default 100, max 500. |
| `offset` | int | Default 0. |

**Example:**
```bash
curl -H "X-API-Key: your-key" \
  "http://localhost:8001/exports/jobs?status=failed&limit=20"
```

#### Stop a running/pending export job

**POST /exports/jobs/{job_id}/stop**

Request cooperative cancellation of a single job. pf-rates has no message
queue in front of it (Cloud Run + BackgroundTasks only, by deliberate cost
choice -- see [`AGENTS.md`](../AGENTS.md)), so this does not kill the job
synchronously: it sets a DB-side flag (`cancel_requested_at`) that the
running export loop polls periodically and stops on at its next
checkpoint (typically within a few seconds, never mid-CSV-upload -- a
partial file is never uploaded, since the export filename is stable and
would otherwise silently overwrite the last good export). Calling this
twice on the same job is safe (idempotent).

**Authentication:** Required

**Response:**
```json
{
  "job_id": 42,
  "status": "running",
  "cancel_requested_at": "2026-09-14T18:05:00Z"
}
```

**Errors:**
- `404` if no job exists with that id.
- `409` if the job is already in a terminal state (`succeeded`, `failed`,
  or `cancelled`) -- nothing left to stop.

**Example:**
```bash
curl -X POST -H "X-API-Key: your-key" \
  http://localhost:8001/exports/jobs/42/stop
```

#### Stop every running/pending export job

**POST /exports/jobs/stop**

Same cooperative-cancellation semantics as above, applied in bulk to
every job currently `pending` or `running`. Jobs that finish in the small
window between listing active jobs and flagging them are silently
omitted from the response rather than reported as stopped.

**Authentication:** Required

**Response:**
```json
{
  "jobs": [
    {"job_id": 42, "status": "running", "cancel_requested_at": "2026-09-14T18:05:00Z"},
    {"job_id": 43, "status": "pending", "cancel_requested_at": "2026-09-14T18:05:00Z"}
  ]
}
```

**Example:**
```bash
curl -X POST -H "X-API-Key: your-key" \
  http://localhost:8001/exports/jobs/stop
```

---

### Economic Indices

#### List economic indices

**GET /economic-indices**

List all economic indices, optionally filtered by code.

**Authentication:** Required

**Query Parameters:**
- `code` (optional): Filter by index code (e.g., `UF`, `UTM`, `IPC`)

**Response:**
```json
[
  {
    "id": 1,
    "code": "UF",
    "year": 2024,
    "month": 1,
    "value": "36500.25"
  },
  {
    "id": 2,
    "code": "UTM",
    "year": 2024,
    "month": 1,
    "value": "65000.00"
  }
]
```

**Example:**
```bash
# All indices
curl -H "X-API-Key: your-key" http://localhost:8001/economic-indices

# UF only
curl -H "X-API-Key: your-key" http://localhost:8001/economic-indices?code=UF
```

#### Get economic index value

**GET /economic-indices/value**

Get the value for an economic index in a specific period.

**Authentication:** Required

**Query Parameters:**
- `code` (required): Index code (`UF`, `UTM`, `IPC`)
- `year` (required): Year (e.g., `2024`)
- `month` (required): Month (1-12)

**Response:**
```json
{
  "code": "UF",
  "year": 2024,
  "month": 1,
  "value": "36500.25"
}
```

**Example:**
```bash
curl -H "X-API-Key: your-key" \
  "http://localhost:8001/economic-indices/value?code=UF&year=2024&month=1"
```

#### Refresh economic indices

**POST /economic-indices/refresh**

Upsert economic indices, either from values you supply yourself ("manual"
entries) or by asking pf-rates to fetch the value from its configured
provider chain for you ("provider fetch" entries). Both can be combined
in the same request; if the same `(code, period_year, period_month)`
triple appears in both lists, the manual entry wins. This is the
endpoint to use for a historical backfill of `RAT_ECON_INDEX` (e.g.
`IPC_CL` since 2010) -- `POST /sync` does NOT work for this: its
`lookback_days` only applies to exchange rates, economic indices there
are always limited to a fixed rolling 12-month window regardless of what
you pass. `POST /exports/financial-data` doesn't help either -- it's
read-only, it exports what's already in the DB to a CSV, it never writes
to `RAT_ECON_INDEX`.

**Authentication:** Required

**Request Body:**
```json
{
  "economic_indices": [
    {
      "code": "IPC_CL",
      "period_year": 2024,
      "period_month": 1,
      "index_value": "125.50",
      "source": "manual"
    }
  ],
  "fetch_economic_indices": [
    { "code": "IPC_CL", "period_year": 2013, "period_month": 1 },
    { "code": "IPC_CL", "period_year": 2013, "period_month": 2 }
  ]
}
```

Both arrays default to empty and are optional individually, but at least
one entry (in either array) is required across the whole request.
`economic_indices[].source` defaults to `"manual"`,
`economic_indices[].base_period` defaults to `"DIC-2018"` if omitted (only
applies to manual entries -- see the note below for `fetch_economic_indices`).
`period_year` must be between 1990 and 2100.

> **`IPC_CL` provider coverage:** as of 2026-09, the configured providers
> (BCCh + SII, chained) only have `IPC_CL` data from **2013-01 onward**.
> `2010-01` through `2012-12` reliably fail with a `502` -- this was
> confirmed by direct probing, not assumed, so don't retry that range
> expecting a transient failure.
>
> **`base_period` for fetched entries:** INE Chile rebases the IPC index
> roughly every five years. `SiiIndicatorsProvider` resolves the correct
> historical `base_period` label per `(period_year, period_month)` instead
> of using a single fixed value -- e.g. `2013-01` is labeled `DIC-2008`,
> `2015-06` is labeled `DIC-2013`, `2026-08` is labeled `DIC-2023`. See
> `_IPC_BASE_PERIODS` in `official_providers.py` for the full chronology
> (sourced from INE's published rebasing history).

**Response:** same shape as [`/exchange-rates/refresh`](#refresh-exchange-rates)
(see above) -- `upserted_exchange_rates` will always be `0` here, since
this endpoint never touches exchange rates:
```json
{
  "upserted_exchange_rates": 0,
  "upserted_economic_indices": 2
}
```

**Errors:**
- `400` if neither `economic_indices` nor `fetch_economic_indices` has any entries.
- `502` if a `fetch_economic_indices` entry can't be resolved by any
  configured provider (e.g. a period the provider never published, such
  as `IPC_CL` before 2013-01 -- see the coverage note above).
  **The whole request is rejected and nothing is persisted** -- even
  entries earlier in the same request that resolved fine. For a large
  batch (e.g. a multi-year historical backfill), split it into smaller
  requests (e.g. one per year, 12 months at a time) so one bad period
  doesn't discard an otherwise-successful batch.
- `503` if `fetch_economic_indices` has entries but no provider chain is configured.

**Example (manual entry):**
```bash
curl -X POST -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"economic_indices": [{"code": "IPC_CL", "period_year": 2024, "period_month": 1, "index_value": "125.50"}]}' \
  http://localhost:8001/economic-indices/refresh
```

**Example (provider fetch -- historical backfill, one year at a time):**
```bash
curl -X POST -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"fetch_economic_indices": [
    {"code": "IPC_CL", "period_year": 2013, "period_month": 1},
    {"code": "IPC_CL", "period_year": 2013, "period_month": 2},
    {"code": "IPC_CL", "period_year": 2013, "period_month": 3}
  ]}' \
  http://localhost:8001/economic-indices/refresh
```

---

### Income Tax Brackets

#### Get matching bracket

**GET /income-tax-brackets**

Get the tax bracket matching a reference date and taxable base.

**Authentication:** Required

**Query Parameters:**
- `reference_date` (required): Date in `YYYY-MM-DD` format
- `taxable_base_utm` (required): Taxable base in UTM

**Response:**
```json
{
  "id": 1,
  "year": 2024,
  "lower_bound_utm": "0.00",
  "upper_bound_utm": "13.50",
  "rate": "0.00",
  "rebate_utm": "0.00"
}
```

**Example:**
```bash
curl -H "X-API-Key: your-key" \
  "http://localhost:8001/income-tax-brackets?reference_date=2024-01-15&taxable_base_utm=10.5"
```

#### List brackets for a year

**GET /income-tax-brackets/list**

List all tax brackets for a specific year.

**Authentication:** Required

**Query Parameters:**
- `year` (required): Year (e.g., `2024`)

**Response:**
```json
[
  {
    "id": 1,
    "year": 2024,
    "lower_bound_utm": "0.00",
    "upper_bound_utm": "13.50",
    "rate": "0.00",
    "rebate_utm": "0.00"
  },
  {
    "id": 2,
    "year": 2024,
    "lower_bound_utm": "13.50",
    "upper_bound_utm": "30.00",
    "rate": "0.04",
    "rebate_utm": "0.54"
  }
]
```

**Example:**
```bash
curl -H "X-API-Key: your-key" \
  "http://localhost:8001/income-tax-brackets/list?year=2024"
```

#### Refresh income tax brackets

**POST /income-tax-brackets/refresh**

Fetch and persist official tax brackets for a year.

**Authentication:** Required

**Request Body:**
```json
{
  "year": 2024
}
```

**Response:**
```json
{
  "inserted": 8,
  "updated": 0,
  "total": 8
}
```

**Example:**
```bash
curl -X POST -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"year": 2024}' \
  http://localhost:8001/income-tax-brackets/refresh
```

---

### Sync

**POST /sync**

Rolling sync of missing market data. Fetches exchange rates and income
tax brackets for the requested window, plus economic indices -- but
**`lookback_days` only applies to exchange rates**; economic indices
(`IPC_CL`) are always synced for a fixed rolling 12-month window ending
today, regardless of what `lookback_days`/`forward_days` you pass (see
`SyncRecentMarketData._build_monthly_dates` in
`src/rates/application/use_cases/sync_recent_market_data.py`). This
endpoint is meant for routine "catch up on what's missing recently"
syncs (e.g. a daily/weekly cron), not for a historical backfill of
`RAT_ECON_INDEX` further back than 12 months -- use
[`POST /economic-indices/refresh`](#refresh-economic-indices) with
`fetch_economic_indices` for that instead.

**Authentication:** Required

**Request Body (optional):**
```json
{
  "lookback_days": 365,
  "forward_days": 35
}
```

**Defaults:**
- `lookback_days`: 365 (exchange rates only -- max `MAX_LOOKBACK_DAYS`, 7300)
- `forward_days`: 35 (exchange rates only, e.g. pre-published `UF` values)

**Response:**
```json
{
  "exchange_rates_upserted": 730,
  "economic_indices_upserted": 24,
  "brackets_upserted": 1
}
```

**Example:**
```bash
# Use defaults
curl -X POST -H "X-API-Key: your-key" http://localhost:8001/sync

# Custom exchange-rate window (does not affect economic indices)
curl -X POST -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"lookback_days": 180, "forward_days": 60}' \
  http://localhost:8001/sync
```

**Note:** UF includes pre-published future values (Banco Central publishes UF up to 3 months ahead).

---

## Error Responses

### 401 Unauthorized

**Cause:** Missing or invalid `X-API-Key`

**Response:**
```json
{
  "detail": "Invalid or missing API key"
}
```

### 404 Not Found

**Cause:** Resource does not exist

**Response:**
```json
{
  "detail": "Exchange rate not found for USD on 2024-01-15"
}
```

### 422 Validation Error

**Cause:** Invalid request parameters

**Response:**
```json
{
  "detail": [
    {
      "loc": ["query", "rate_date"],
      "msg": "invalid date format",
      "type": "value_error"
    }
  ]
}
```

## Interactive Documentation

For interactive API exploration:

- **Swagger UI:** `http://localhost:8001/docs`
- **ReDoc:** `http://localhost:8001/redoc`

Both provide:
- Try-it-out functionality
- Request/response schemas
- Authentication configuration
- Example values

## Client Libraries

### Python Example

```python
import requests
from decimal import Decimal
from datetime import date

class PFRatesClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.headers = {"X-API-Key": api_key}
    
    def get_exchange_rate(self, currency: str, rate_date: date) -> Decimal:
        response = requests.get(
            f"{self.base_url}/exchange-rates/value",
            headers=self.headers,
            params={"currency_code": currency, "rate_date": rate_date.isoformat()}
        )
        response.raise_for_status()
        return Decimal(response.json()["value_clp"])
    
    def get_uf_value(self, year: int, month: int) -> Decimal:
        response = requests.get(
            f"{self.base_url}/economic-indices/value",
            headers=self.headers,
            params={"code": "UF", "year": year, "month": month}
        )
        response.raise_for_status()
        return Decimal(response.json()["value"])

# Usage
client = PFRatesClient("http://localhost:8001", "your-api-key")
usd_rate = client.get_exchange_rate("USD", date(2024, 1, 15))
uf_value = client.get_uf_value(2024, 1)
```

## Rate Limits

Currently, pf-rates does not enforce rate limits. In production, consider adding:
- Per-client rate limiting (e.g., 100 requests/minute)
- Caching layer (Redis) for frequently accessed data
- CDN for static reference data (currencies list)

## See also

- [Getting Started](getting-started.md) - Installation and setup
- [Development Guide](development.md) - Local development workflow
- [Database Guide](database.md) - Data sources and table ownership
- [Deployment Guide](deployment.md) - Production deployment
