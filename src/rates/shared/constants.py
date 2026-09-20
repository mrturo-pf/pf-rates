"""Shared financial constants."""

DEFAULT_CURRENCY = "CLP"

# Single source of truth for the largest lookback window any endpoint will
# accept (/sync and /exchange-rates/export). 20 years comfortably covers
# deliberate historical backfills (e.g. a one-off multi-year export) while
# still rejecting obvious fat-finger values (millions of days).
MAX_LOOKBACK_DAYS = 7300
DAILY_MARKET_RATE_CODES = ("USD", "EUR", "UF")
MONTHLY_MARKET_RATE_CODES = ("UTM",)
MONTHLY_ECONOMIC_INDEX_CODES = ("IPC_CL",)
MONTHLY_EXCHANGE_RATE_CODES = frozenset(MONTHLY_MARKET_RATE_CODES)

# CMF/SII publishes UF values for the following month around the 9th of each month.
# The maximum forward horizon is roughly today + 10..40 days depending on position
# in the calendar.  Overshooting is benign — unpublished future dates simply return
# nothing from the provider.
FORWARD_DAILY_RATE_CODES = ("UF",)

# Maximum number of prior calendar days to probe for a fallback value (DB or
# provider) when neither the exact date nor any later prior date is stored.
# Chile's FX market is closed on weekends and holidays, so a rate requested for
# e.g. a Sunday resolves to the preceding Friday's value within this window.
MAX_PROVIDER_LOOKBACK_DAYS = 7

# Status values for RAT_EXPORT_JOB.status (async CSV export tracking).
# Kept as plain strings (not an enum) since they cross the DB boundary as-is
# and the DB CHECK constraint (pf-db migration 0004) is the actual source of
# truth for which values are valid -- this tuple just avoids repeating the
# same 4 string literals across the use case, repository, and routes.
EXPORT_JOB_STATUS_PENDING = "pending"
EXPORT_JOB_STATUS_RUNNING = "running"
EXPORT_JOB_STATUS_SUCCEEDED = "succeeded"
EXPORT_JOB_STATUS_FAILED = "failed"
EXPORT_JOB_STATUS_CANCELLED = "cancelled"

EXPORT_JOB_STATUSES = (
    EXPORT_JOB_STATUS_PENDING,
    EXPORT_JOB_STATUS_RUNNING,
    EXPORT_JOB_STATUS_SUCCEEDED,
    EXPORT_JOB_STATUS_FAILED,
    EXPORT_JOB_STATUS_CANCELLED,
)

# Statuses a stop request may still act on -- anything else is terminal.
EXPORT_JOB_ACTIVE_STATUSES = (EXPORT_JOB_STATUS_PENDING, EXPORT_JOB_STATUS_RUNNING)

# RAT_EXPORT_JOB.export_kind values (pf-db migration 0007). Distinguishes
# which CSV-export use case a job's background runner must build --
# "exchange_rates" for ExportExchangeRatesCsv (POST /exchange-rates/export),
# "combined" for ExportCombinedFinancialDataCsv (POST /exports/financial-data).
# Job status/progress/cancellation endpoints are shared across both kinds;
# only job creation and background dispatch need to know which is which.
EXPORT_KIND_EXCHANGE_RATES = "exchange_rates"
EXPORT_KIND_COMBINED = "combined"
EXPORT_KINDS = (EXPORT_KIND_EXCHANGE_RATES, EXPORT_KIND_COMBINED)

# GET /exports/jobs pagination guardrails. A hard cap (not
# just a default) prevents an unbounded SELECT as job history grows --
# cheap to enforce, and this is an internal operational endpoint, not a
# user-facing paginated list that needs a larger page size.
EXPORT_JOB_LIST_DEFAULT_LIMIT = 100
EXPORT_JOB_LIST_MAX_LIMIT = 500

# How often (in resolved dates) the CSV export loop polls the DB for a
# cancellation request. Small enough that a stop takes effect within a
# few seconds even on a large multi-year window; large enough that it
# doesn't add a meaningful number of extra DB round-trips.
EXPORT_CANCELLATION_CHECK_INTERVAL = 50

# Minimum wall-clock time (seconds) between DB session refreshes during a
# running export. A large lookback window (thousands of dates x several
# currencies) can run for many minutes; holding a single DB session/
# connection open that whole time defeats pool_pre_ping and pool_recycle
# (session.py) -- both only act when a connection is checked back into
# the pool, which never happens for one long-lived session. 120s is
# comfortably under Neon's ~5 min idle-connection window (see session.py)
# while not adding meaningful overhead: at most a handful of extra
# connection round-trips even for a job running an hour.
EXPORT_SESSION_REFRESH_INTERVAL_SECONDS = 120
