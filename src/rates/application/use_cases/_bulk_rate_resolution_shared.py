"""Shared bulk-resolution helpers for exchange-rate consumers."""

from datetime import date, timedelta
from decimal import Decimal

from rates.application.errors import ExchangeRateNotFoundError
from rates.application.ports.market_data_repository import MarketDataRepository
from rates.application.use_cases.get_exchange_rate_value import GetExchangeRateValue
from rates.domain.normalization import normalize_exchange_rate_lookup_date
from rates.shared.constants import (
    MAX_PROVIDER_LOOKBACK_DAYS,
    MONTHLY_EXCHANGE_RATE_CODES,
)


async def bulk_fetch_currency_values(
    repository: MarketDataRepository, currency_code: str, start: date, end: date
) -> dict[date, Decimal]:
    """Fetch stored values for one currency and a date span in one query."""
    query_start = start
    if currency_code.upper() in MONTHLY_EXCHANGE_RATE_CODES:
        query_start = date(start.year, start.month, 1)
    return await repository.list_exchange_rate_values(currency_code, query_start, end)


def lookup_cached_value(
    currency_code: str, rate_date: date, cached_values: dict[date, Decimal]
) -> Decimal | None:
    """Return the exact normalized value from a bulk-fetched map."""
    lookup_date = normalize_exchange_rate_lookup_date(currency_code, rate_date)
    return cached_values.get(lookup_date)


def lookup_nearest_prior_cached_value(
    currency_code: str, rate_date: date, cached_values: dict[date, Decimal]
) -> Decimal | None:
    """Return a bounded prior value from a bulk-fetched map."""
    lookup_date = normalize_exchange_rate_lookup_date(currency_code, rate_date)
    for days_back in range(1, MAX_PROVIDER_LOOKBACK_DAYS + 1):
        value = cached_values.get(lookup_date - timedelta(days=days_back))
        if value is not None:
            return value
    return None


async def resolve_value_for_date(
    currency_code: str,
    rate_date: date,
    cached_values: dict[date, Decimal],
    today: date,
    get_exchange_rate_value: GetExchangeRateValue,
) -> Decimal | None:
    """Resolve one pair using bulk values before the singular fallback chain."""
    value = lookup_cached_value(currency_code, rate_date, cached_values)
    if value is None and rate_date <= today:
        value = lookup_nearest_prior_cached_value(
            currency_code, rate_date, cached_values
        )
    if value is not None:
        return value
    try:
        return await get_exchange_rate_value.execute(currency_code, rate_date)
    except ExchangeRateNotFoundError:
        return None


async def resolve_exchange_rate_pairs(
    pairs: list[tuple[str, date]],
    repository: MarketDataRepository,
    get_exchange_rate_value: GetExchangeRateValue,
    today: date,
) -> dict[tuple[str, date], Decimal | None]:
    """Resolve exchange-rate pairs with one bulk DB fetch per currency."""
    grouped: dict[str, list[date]] = {}
    for currency_code, rate_date in pairs:
        grouped.setdefault(currency_code, []).append(rate_date)

    resolved: dict[tuple[str, date], Decimal | None] = {}
    for currency_code, dates in grouped.items():
        cached_values = await bulk_fetch_currency_values(
            repository, currency_code, min(dates), max(dates)
        )
        for rate_date in dates:
            resolved[(currency_code, rate_date)] = await resolve_value_for_date(
                currency_code,
                rate_date,
                cached_values,
                today,
                get_exchange_rate_value,
            )
    return resolved


async def resolve_economic_index_pairs(
    pairs: list[tuple[str, int, int]], repository: MarketDataRepository
) -> dict[tuple[str, int, int], Decimal | None]:
    """Resolve economic-index pairs with one full-series fetch per code."""
    grouped: dict[str, set[tuple[int, int]]] = {}
    for code, year, month in pairs:
        grouped.setdefault(code, set()).add((year, month))

    resolved: dict[tuple[str, int, int], Decimal | None] = {}
    for code, periods in grouped.items():
        entries = await repository.list_economic_indices(code)
        values = {
            (entry.period_year, entry.period_month): entry.index_value
            for entry in entries
        }
        for year, month in periods:
            resolved[(code, year, month)] = values.get((year, month))
    return resolved
