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
