"""Exchange-rate routes."""

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

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
from rates.application.use_cases.get_exchange_rate_value import GetExchangeRateValue
from rates.application.use_cases.get_exchange_rate_values import (
    GetExchangeRateValues,
)
from rates.interfaces.api.dependencies import (
    get_exchange_rate_values_use_case,
    get_exchange_rate_value_use_case,
)
from rates.interfaces.api.routes._refresh_deps import (
    MarketDataRepository,
    RefreshRates,
    get_market_data_repository,
    get_refresh_rates_use_case,
    to_http_exception,
    RefreshRatesResponse,
)

router = APIRouter(prefix="/exchange-rates", tags=["exchange-rates"])
_CHILE_TZ = ZoneInfo("America/Santiago")


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


class ExchangeRateValuesRequest(BaseModel):
    """Represent a batch exchange-rate lookup request."""

    pairs: list[ProviderExchangeRateRequest] = Field(
        default_factory=list, max_length=500
    )


class ExchangeRateValueResult(BaseModel):
    """Represent one batch exchange-rate lookup result."""

    currency_code: str
    rate_date: date
    value_clp: str | None


class ExchangeRateValuesResponse(BaseModel):
    """Represent a batch exchange-rate lookup response."""

    results: list[ExchangeRateValueResult]


class ExchangeRateRefreshRequest(BaseModel):
    """Represent Exchange Rate Refresh Request."""

    exchange_rates: list[ExchangeRateWrite] = Field(default_factory=list)
    fetch_exchange_rates: list[ProviderExchangeRateRequest] = Field(
        default_factory=list
    )


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


@router.post("/values", response_model=ExchangeRateValuesResponse)
async def get_exchange_rate_values(
    payload: ExchangeRateValuesRequest,
    use_case: GetExchangeRateValues = Depends(get_exchange_rate_values_use_case),
) -> ExchangeRateValuesResponse:
    """Return CLP values for multiple currency/date pairs."""
    values = await use_case.execute(
        [(pair.currency_code, pair.rate_date) for pair in payload.pairs],
        datetime.now(tz=_CHILE_TZ).date(),
    )
    return ExchangeRateValuesResponse(
        results=[
            ExchangeRateValueResult(
                currency_code=item.currency_code,
                rate_date=item.rate_date,
                value_clp=str(item.value_clp) if item.value_clp is not None else None,
            )
            for item in values
        ]
    )


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
