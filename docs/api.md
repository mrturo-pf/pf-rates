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

Upsert exchange rates from manual entries or provider fetches.

**Authentication:** Required

**Request Body:**
```json
{
  "source": "mindicador",
  "entries": [
    {
      "currency_code": "USD",
      "rate_date": "2024-01-15",
      "value_clp": "897.5000"
    }
  ]
}
```

**Response:**
```json
{
  "inserted": 1,
  "updated": 0,
  "total": 1
}
```

**Example:**
```bash
curl -X POST -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"source": "manual", "entries": [{"currency_code": "USD", "rate_date": "2024-01-15", "value_clp": "897.50"}]}' \
  http://localhost:8001/exchange-rates/refresh
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

Upsert economic indices from manual entries or provider fetches.

**Authentication:** Required

**Request Body:**
```json
{
  "source": "bcch",
  "entries": [
    {
      "code": "UF",
      "year": 2024,
      "month": 1,
      "value": "36500.25"
    }
  ]
}
```

**Response:**
```json
{
  "inserted": 1,
  "updated": 0,
  "total": 1
}
```

**Example:**
```bash
curl -X POST -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"source": "manual", "entries": [{"code": "UF", "year": 2024, "month": 1, "value": "36500.25"}]}' \
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

Rolling sync of all missing market data. Fetches exchange rates and economic indices for a date range.

**Authentication:** Required

**Request Body (optional):**
```json
{
  "lookback_days": 365,
  "forward_days": 35
}
```

**Defaults:**
- `lookback_days`: 365
- `forward_days`: 35

**Response:**
```json
{
  "exchange_rates": {
    "inserted": 730,
    "updated": 0,
    "total": 730
  },
  "economic_indices": {
    "inserted": 24,
    "updated": 0,
    "total": 24
  }
}
```

**Example:**
```bash
# Use defaults
curl -X POST -H "X-API-Key: your-key" http://localhost:8001/sync

# Custom range
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
