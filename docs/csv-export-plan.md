# Action Plan — Exchange Rates CSV Export to Google Drive

> Status: **implemented and deployed** (`POST /exchange-rates/export`,
> Option 1 below). Secret Manager entries and the deploy pipeline's
> `--set-secrets` wiring are in place -- see "Open items" for what's still
> pending (the Cloud Scheduler cronjob).

## Goal

An HTTP-triggered flow (with a cronjob planned as a follow-up) that builds
a CSV with exchange-rate values for the last 90 days and the next 30 days,
for all non-CLP currencies/index units, using the same resolution logic as
`GET /exchange-rates/value` (DB hit → provider fallback → nearest-prior-
date fallback → persist). The CSV is then uploaded to a specific folder in
the user's personal Google Drive, authenticated as the user via OAuth.

## Decisions (confirmed with the user)

| Topic | Decision |
|---|---|
| Currencies/units included | `USD`, `EUR`, `UF`, `UTM` (all non-CLP entries from `GET /currencies`) |
| Date range | `today - 90 days` → `today + 30 days`, inclusive, computed in `America/Santiago` (same TZ the backend itself uses) |
| Missing values (mostly future USD/EUR dates) | **Omit the row.** The CSV only contains rows with a real, resolved value — no empty/placeholder rows. |
| Google Drive integration | Google Drive API v3 with **OAuth as the account owner, published "In production"** (not a Service Account — see below) |
| Execution | Triggered by `POST /exchange-rates/export`, with a Cloud Scheduler cronjob planned as a follow-up. |
| Code location | Inside pf-rates itself (Option 1) — see "Architecture decision" below |

### Why OAuth as the account owner, not a Service Account (revised decision, twice)

The original plan proposed OAuth "Desktop app" user consent left in
"Testing" publishing mode. That was wrong once the execution model changed
from "a human runs this by hand" to "triggered by an endpoint, eventually
on a cron schedule": while a Google Cloud OAuth consent screen stays in
"Testing" mode, its refresh tokens **expire after 7 days**, requiring an
interactive browser re-login. That's fundamentally incompatible with
unattended execution — nobody is present to click "Allow" when a cronjob
fires at 3am.

The next iteration switched to a **Service Account**: authenticates with a
private key, non-interactively, no token expiry. That held up for reading
and for updating an already-existing file -- but broke the very first time
the export needed to *create* a new file: Google Service Accounts have no
storage quota of their own in a personal (non-Workspace) Drive, so
`files.create()` fails with a 403 ("Service Accounts do not have storage
quota"). Working around that would require either a Google Workspace
Shared Drive (not available on the target personal `@gmail.com` account)
or a human manually pre-creating the destination file as a permanent
prerequisite -- fragile for a cronjob (a single accidental deletion of
that seed file breaks every future run).

The actual fix: keep OAuth, but **publish the consent screen as "In
production"** instead of leaving it in "Testing". That single setting
removes the 7-day refresh-token expiry while authenticating as the real
account owner (full personal quota, so create/update/delete all work
normally, and the export can self-heal if the file is ever deleted). One
interactive browser consent, done once via `scripts/gdrive_oauth_setup.py`,
never repeated. See `google-drive-credentials-setup.md` for the full
setup.

### Architecture decision: Option 1 (endpoint inside pf-rates) — RESOLVED

Implemented as `POST /exchange-rates/export` directly inside pf-rates,
following the existing hexagonal architecture:

- Port: `application/ports/file_export_port.py` (`FileExportPort`)
- Use case: `application/use_cases/export_exchange_rates_csv.py`
  (`ExportExchangeRatesCsv`), composed with the existing
  `GetExchangeRateValue` use case — no logic duplicated, no self-HTTP
  loopback.
- Adapter: `infrastructure/gdrive/drive_file_export.py`
  (`GoogleDriveFileExport`), authenticating via OAuth as the account owner.
- Route: added to `interfaces/api/routes/exchange_rates.py` (same router,
  same `/exchange-rates` prefix — no new router file, to stay DRY/cohesive).
- Wiring: `get_file_export_port()` / `get_export_exchange_rates_csv_use_case()`
  in `interfaces/api/dependencies.py`. Missing credentials raise
  `FinancialDataDependencyConfigurationError` -> HTTP `503`, so the rest of
  the service keeps working even before Drive is configured.
- New settings: `PF_RATES_GDRIVE_OAUTH_TOKEN_JSON` (raw content, prod),
  `PF_RATES_GDRIVE_OAUTH_TOKEN_JSON_PATH` (local file path, dev — see
  `../secrets/pf-rates/` at the repo root), `PF_RATES_GDRIVE_EXPORT_FOLDER_ID`
  (see `config.py`).
- New dependencies: `google-api-python-client`, `google-auth` (runtime,
  pinned in `pyproject.toml`); `google-auth-oauthlib` (dev-only, used solely
  by the one-time `scripts/gdrive_oauth_setup.py`).
- Full unit-test coverage (100%) added for all new modules, following the
  project's stub-based testing convention (no `unittest.mock` for
  application-layer ports; `Mock`/`patch` reserved for the Google API SDK
  boundary in the infrastructure adapter and dependency wiring).

Option 2 (a separate service) was not built — kept here for the historical
record of the decision, not as a live alternative.

## Why the resolver logic matters here (not the plain list endpoint)

`GET /exchange-rates` is a raw DB read — it can have gaps (e.g. weekends,
holidays, provider outages on a given day). `GET /exchange-rates/value`
instead runs a 5-step resolution chain (see
`src/rates/application/use_cases/get_exchange_rate_value.py`):

1. Exact date in DB.
2. Exact date from the external provider chain (persisted).
3. Nearest prior date in DB within a 7-day window (not persisted).
4. Provider probed day-by-day backward up to 7 days (persisted under the
   found date).
5. Not found → 404.

Steps 3–4 only apply to `rate_date <= today`. This means:

- **Last 90 days**: nearly always resolves to *some* value for every
  currency, thanks to the fallback chain.
- **Next 30 days**: `USD`/`EUR` will mostly 404 (no such thing as
  "tomorrow's dollar"). `UF` often has real values because Chile
  pre-publishes the current month's UF. `UTM` is published monthly and may
  or may not cover the full 30-day forward window depending on when in the
  month the script runs.

This is expected, correct behavior of the underlying endpoint — not a bug to
work around, just a shape to account for (see "omit the row" decision above).

## Flow (as implemented)

1. List the codes to include, excluding `CLP` (the base currency; an FX
   rate against itself is meaningless), via
   `ReferenceDataRepository.list_currencies()`.
2. Compute the 121 calendar dates in the `America/Santiago` timezone.
3. For each `(currency_code, rate_date)` pair (up to 4 × 121 = 484
   lookups), call `GetExchangeRateValue.execute(...)` directly in-process
   — no HTTP, no API key needed internally, no self-loopback. A resulting
   `ExchangeRateNotFoundError` is treated as "no data for this pair" and
   simply skipped — it does not abort the whole run.
4. Assemble the CSV in memory. Columns: `currency_code, rate_date,
   value_clp`. `value_clp` stays a **string**, exactly as returned/computed
   — never cast to `float` (financial precision rule: `Decimal`/string
   representations only, never floats).
5. Upload the CSV to the target Google Drive folder via the Drive API v3,
   authenticated via OAuth as the account owner (see
   `google-drive-credentials-setup.md`).

## Performance notes

- Every value resolved through provider fallback gets persisted
  server-side. Re-running the flow later (e.g. next week) will hit the
  DB-fast-path (step 1) for most of the previously-resolved dates, making
  subsequent runs progressively faster.
- Expect the first run to be the slowest, especially for the 90-day
  backfill window if pf-rates' own rolling sync hasn't already covered it.
- Because resolution happens in-process, this avoids 484 HTTP round-trips
  entirely — only actual provider-fallback calls hit the network. A
  cold-start-heavy first run on a service with `min-instances=0` may still
  approach the Cloud Run request timeout; revisit if that becomes an issue
  (e.g. bump `--timeout`, or move to a background/async job pattern).

## Explicitly out of scope (for now)

- Historical data older than 90 days, or forward data beyond 30 days.
- Building the actual Cloud Scheduler cronjob wiring — the plan is to get
  the endpoint working first, then attach a schedule once it's proven
  stable.

## Open items before production deployment

- [x] Architecture decision: Option 1, implemented.
- [x] User ran the one-time OAuth authorization script — see
  `google-drive-credentials-setup.md`.
- [x] Destination Drive folder id (goes into `PF_RATES_GDRIVE_EXPORT_FOLDER_ID`).
  No manual file pre-creation or folder sharing needed — OAuth-as-owner
  can create the destination file itself.
- [x] Added `PF_RATES_GDRIVE_OAUTH_TOKEN_JSON` and
  `PF_RATES_GDRIVE_EXPORT_FOLDER_ID` to Secret Manager, granted
  `pf-rates@<PROJECT>.iam.gserviceaccount.com` accessor access, and wired
  both into the deploy workflow's `--set-secrets` (conditional on
  `repo_name == pf-rates`, inside `pf-common`'s `deploy-reusable.yml`) —
  see `deployment.md`.
- [ ] Build the Cloud Scheduler cronjob once the endpoint is proven stable
  in production with real credentials.

## See also

- [`google-drive-credentials-setup.md`](google-drive-credentials-setup.md) —
  step-by-step guide to run the one-time OAuth authorization.
- [`api.md`](api.md) — full endpoint reference, including
  `/exchange-rates/value`.
