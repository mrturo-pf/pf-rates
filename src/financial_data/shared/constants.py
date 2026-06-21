"""Shared financial constants."""

DEFAULT_CURRENCY = "CLP"
DAILY_MARKET_RATE_CODES = ("USD", "EUR", "UF")
MONTHLY_MARKET_RATE_CODES = ("UTM",)
MONTHLY_ECONOMIC_INDEX_CODES = ("IPC_CL",)
MONTHLY_EXCHANGE_RATE_CODES = frozenset(MONTHLY_MARKET_RATE_CODES)

# CMF/SII publishes UF values for the following month around the 9th of each month.
# The maximum forward horizon is roughly today + 10..40 days depending on position
# in the calendar.  Overshooting is benign — unpublished future dates simply return
# nothing from the provider.
FORWARD_DAILY_RATE_CODES = ("UF",)
