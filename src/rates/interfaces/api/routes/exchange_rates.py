"""Exchange-rate routes."""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from rates.application.errors import (
    FinancialDataError,
)
from rates.application.dto import (
    ExchangeRateWriteDTO,
    ProviderExchangeRateRequestDTO,
    RefreshRatesCommandDTO,
)
from rates.application.use_cases.export_exchange_rates_csv import (
    DEFAULT_FORWARD_DAYS,
    DEFAULT_LOOKBACK_DAYS,
    ExportExchangeRatesCsv,
)
from rates.application.use_cases.get_exchange_rate_value import (
    GetExchangeRateValue,
)
from rates.interfaces.api.dependencies import (
    get_exchange_rate_value_use_case,
    get_export_exchange_rates_csv_use_case,
)
from rates.interfaces.api.routes._refresh_deps import (
    MarketDataRepository,
    RefreshRates,
    get_market_data_repository,
    get_refresh_rates_use_case,
    to_http_exception,
    RefreshRatesResponse,
)
from rates.shared.constants import MAX_LOOKBACK_DAYS

router = APIRouter(prefix="/exchange-rates", tags=["exchange-rates"])


class ExchangeRateRead(BaseModel):
    """Represent Exchange Rate Read."""

    currency_code: str
    rate_date: date
    value_clp: str
    source: str


class ExchangeRateWrite(BaseModel):
    """Represent Exchange Rate Write."""

    currency_code: str = Field(min_length=1)
    rate_date: date
    value_clp: Decimal = Field(gt=0)
    source: str = Field(default="manual", min_length=1)


class ProviderExchangeRateRequest(BaseModel):
    """Represent Provider Exchange Rate Request."""

    currency_code: str = Field(min_length=1)
    rate_date: date


class ExchangeRateRefreshRequest(BaseModel):
    """Represent Exchange Rate Refresh Request."""

    exchange_rates: list[ExchangeRateWrite] = Field(default_factory=list)
    fetch_exchange_rates: list[ProviderExchangeRateRequest] = Field(
        default_factory=list
    )


class ExportExchangeRatesRequest(BaseModel):
    """Represent Export Exchange Rates Request."""

    lookback_days: int = Field(
        default=DEFAULT_LOOKBACK_DAYS,
        ge=1,
        le=MAX_LOOKBACK_DAYS,
        description=(
            "Days in the past to include, relative to today (Chile time). "
            "For windows beyond the default 90 days, call POST /sync first "
            "with the same lookback_days so Neon is warm -- otherwise this "
            "endpoint resolves each (currency, date) pair one at a time and "
            "can be slow for large, previously-uncached windows."
        ),
    )
    forward_days: int = Field(
        default=DEFAULT_FORWARD_DAYS,
        ge=0,
        le=365,
        description="Days in the future to include, relative to today (Chile time).",
    )


class ExportExchangeRatesResponse(BaseModel):
    """Represent Export Exchange Rates Response."""

    rows_written: int
    file_id: str


@router.get("", response_model=list[ExchangeRateRead])
async def list_exchange_rates(
    currency_code: str | None = Query(default=None),
    repository: MarketDataRepository = Depends(get_market_data_repository),
) -> list[ExchangeRateRead]:
    """List stored exchange rates, optionally filtered by currency code."""
    return [
        ExchangeRateRead(
            currency_code=item.currency_code,
            rate_date=item.rate_date,
            value_clp=str(item.value_clp),
            source=item.source,
        )
        for item in await repository.list_exchange_rates(currency_code)
    ]


@router.get("/value")
async def get_exchange_rate_value(
    currency_code: str = Query(...),
    rate_date: date = Query(...),
    use_case: GetExchangeRateValue = Depends(get_exchange_rate_value_use_case),
) -> dict[str, str]:
    """Return the CLP value for a currency on the given date.

    If the rate is not in the database, it is fetched from the external
    provider chain, persisted for future lookups, and then returned.
    """
    try:
        value = await use_case.execute(currency_code, rate_date)
    except FinancialDataError as exc:
        raise to_http_exception(exc) from exc
    return {"value_clp": str(value)}


@router.post("/refresh", response_model=RefreshRatesResponse)
async def refresh_exchange_rates(
    payload: ExchangeRateRefreshRequest,
    use_case: RefreshRates = Depends(get_refresh_rates_use_case),
) -> RefreshRatesResponse:
    """Upsert exchange rates from manual entries or provider fetches."""
    try:
        result = await use_case.execute(
            RefreshRatesCommandDTO(
                exchange_rates=[
                    ExchangeRateWriteDTO(
                        currency_code=item.currency_code,
                        rate_date=item.rate_date,
                        value_clp=item.value_clp,
                        source=item.source,
                    )
                    for item in payload.exchange_rates
                ],
                provider_exchange_rates=[
                    ProviderExchangeRateRequestDTO(
                        currency_code=item.currency_code,
                        rate_date=item.rate_date,
                    )
                    for item in payload.fetch_exchange_rates
                ],
            )
        )
    except FinancialDataError as exc:
        raise to_http_exception(exc) from exc
    return RefreshRatesResponse(
        upserted_exchange_rates=result.upserted_exchange_rates,
        upserted_economic_indices=result.upserted_economic_indices,
    )


@router.post("/export", response_model=ExportExchangeRatesResponse)
async def export_exchange_rates(
    payload: ExportExchangeRatesRequest = ExportExchangeRatesRequest(),
    use_case: ExportExchangeRatesCsv = Depends(get_export_exchange_rates_csv_use_case),
) -> ExportExchangeRatesResponse:
    """Build a CSV of resolved exchange-rate values and upload it to Drive.

    Iterates every non-CLP currency across the requested rolling window
    (default: 90 days back, 30 days forward), resolving each value with
    the same fallback chain as `GET /exchange-rates/value`. Dates that
    cannot be resolved (e.g. most future dates for USD/EUR) are omitted
    from the CSV rather than erroring out the whole export.

    Returns 503 if Google Drive export is not configured yet.
    """
    try:
        result = await use_case.execute(
            lookback_days=payload.lookback_days,
            forward_days=payload.forward_days,
        )
    except FinancialDataError as exc:
        raise to_http_exception(exc) from exc
    return ExportExchangeRatesResponse(
        rows_written=result.rows_written, file_id=result.file_id
    )
