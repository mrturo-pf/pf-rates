"""Exchange-rate routes."""

from datetime import date
from decimal import Decimal
from collections.abc import Callable

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from rates.application.errors import (
    FinancialDataError,
)
from rates.application.dto import (
    ExchangeRateWriteDTO,
    ProviderExchangeRateRequestDTO,
    RefreshRatesCommandDTO,
)
from rates.application.ports.export_job_repository import ExportJobRepository
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
    get_export_job_background_runner,
    get_export_job_repository,
)
from rates.interfaces.api.routes._refresh_deps import (
    MarketDataRepository,
    RefreshRates,
    get_market_data_repository,
    get_refresh_rates_use_case,
    to_http_exception,
    RefreshRatesResponse,
)
from rates.shared.constants import EXPORT_JOB_STATUS_PENDING, MAX_LOOKBACK_DAYS

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

    model_config = ConfigDict(populate_by_name=True)

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
    async_execution: bool = Field(
        default=False,
        alias="async",
        description=(
            "If true, create the export job and return immediately with a "
            "job_id instead of waiting for completion -- poll "
            "GET /exchange-rates/export/jobs/{job_id} for its status. "
            "Defaults to false (synchronous, waits for the CSV upload)."
        ),
    )


class ExportExchangeRatesResponse(BaseModel):
    """Represent Export Exchange Rates Response."""

    rows_written: int
    file_id: str


class ExportJobTriggeredResponse(BaseModel):
    """Represent the response for an asynchronously triggered export job."""

    job_id: int
    status: str
    monitor_url: str


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


@router.post("/export")
async def export_exchange_rates(
    background_tasks: BackgroundTasks,
    response: Response,
    payload: ExportExchangeRatesRequest = ExportExchangeRatesRequest(),
    use_case: ExportExchangeRatesCsv = Depends(get_export_exchange_rates_csv_use_case),
    export_job_repository: ExportJobRepository = Depends(get_export_job_repository),
    run_job_in_background: Callable[[int, int, int], object] = Depends(
        get_export_job_background_runner
    ),
) -> ExportExchangeRatesResponse | ExportJobTriggeredResponse:
    """Build a CSV of resolved exchange-rate values and upload it to Drive.

    Iterates every non-CLP currency across the requested rolling window
    (default: 90 days back, 30 days forward), resolving each value with
    the same fallback chain as `GET /exchange-rates/value`. Dates that
    cannot be resolved (e.g. most future dates for USD/EUR) are omitted
    from the CSV rather than erroring out the whole export.

    Set async_execution (JSON key: async) to true to trigger the export in
    the background instead of waiting for it: returns 202 Accepted with a
    job_id right away, and the actual export runs after the response is
    sent. Poll GET /exchange-rates/export/jobs/{job_id} for its status.
    Recommended for large windows (e.g. a multi-year historical backfill)
    where a synchronous call risks the request timing out before the CSV
    finishes uploading, even with a warm cache.

    Returns 503 immediately if Google Drive export is not configured yet --
    including in async mode, before any job row is created, since a job
    would otherwise be guaranteed to fail as soon as it ran in the background.
    """
    if payload.async_execution:
        job_id = await export_job_repository.create(
            payload.lookback_days, payload.forward_days
        )
        background_tasks.add_task(
            run_job_in_background,
            job_id,
            payload.lookback_days,
            payload.forward_days,
        )
        response.status_code = 202
        return ExportJobTriggeredResponse(
            job_id=job_id,
            status=EXPORT_JOB_STATUS_PENDING,
            monitor_url=f"/exchange-rates/export/jobs/{job_id}",
        )
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
