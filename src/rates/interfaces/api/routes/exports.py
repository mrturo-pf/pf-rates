"""Combined financial-data export routes (exchange rates + economic indices)."""

from collections.abc import Callable

from fastapi import APIRouter, BackgroundTasks, Depends, Response
from pydantic import BaseModel, ConfigDict, Field

from rates.application.errors import FinancialDataError
from rates.application.ports.export_job_repository import ExportJobRepository
from rates.application.use_cases.export_combined_financial_data_csv import (
    DEFAULT_FORWARD_DAYS,
    DEFAULT_LOOKBACK_DAYS,
    ExportCombinedFinancialDataCsv,
)
from rates.interfaces.api.dependencies import (
    get_export_combined_financial_data_csv_use_case,
    get_export_job_background_runner,
    get_export_job_repository,
)
from rates.interfaces.api.errors import to_http_exception
from rates.interfaces.api.routes._export_job_trigger import (
    ExportJobTriggeredResponse,
    trigger_async_export_job,
)
from rates.shared.constants import (
    EXPORT_KIND_COMBINED,
    MAX_LOOKBACK_DAYS,
)

router = APIRouter(prefix="/exports", tags=["exports"])


class ExportFinancialDataRequest(BaseModel):
    """Represent the request body for the combined financial-data export."""

    model_config = ConfigDict(populate_by_name=True)

    lookback_days: int = Field(
        default=DEFAULT_LOOKBACK_DAYS,
        ge=1,
        le=MAX_LOOKBACK_DAYS,
        description=(
            "Days in the past to include, relative to today (Chile time). "
            "Applies to both series types (exchange rates and economic "
            "indices) alike."
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
            "GET /exchange-rates/export/jobs/{job_id} for its status (job "
            "status/cancellation is shared infrastructure across every "
            "export kind). Defaults to false."
        ),
    )


class ExportFinancialDataResponse(BaseModel):
    """Represent the synchronous response for the combined export."""

    rows_written: int
    file_id: str


@router.post("/financial-data")
async def export_financial_data(
    background_tasks: BackgroundTasks,
    response: Response,
    payload: ExportFinancialDataRequest = ExportFinancialDataRequest(),
    use_case: ExportCombinedFinancialDataCsv = Depends(
        get_export_combined_financial_data_csv_use_case
    ),
    export_job_repository: ExportJobRepository = Depends(get_export_job_repository),
    run_job_in_background: Callable[[int, int, int, str], object] = Depends(
        get_export_job_background_runner
    ),
) -> ExportFinancialDataResponse | ExportJobTriggeredResponse:
    """Build a combined CSV of exchange-rate + economic-index values and upload it.

    One CSV, one row shape (`series_type,code,period_date,value`),
    covering both RAT_EXCH_RATE (`series_type=EXCHANGE_RATE`) and
    RAT_ECON_INDEX (`series_type=ECONOMIC_INDEX`) data across the same
    rolling window. Economic indices are monthly in storage but expanded
    to one row per calendar day in the window, repeating that month's
    value -- the same behavior `POST /exchange-rates/export` already uses
    for UTM. Does not replace `POST /exchange-rates/export`, which keeps
    producing its own currency-only CSV unchanged for existing consumers.

    Same async_execution / job-monitoring contract as
    `POST /exchange-rates/export` -- see its docstring. Job status,
    progress, and cooperative-cancellation endpoints
    (`GET/POST /exchange-rates/export/jobs/...`) are shared across both
    export kinds; only creation and background dispatch differ.
    """
    if payload.async_execution:
        return await trigger_async_export_job(
            background_tasks,
            response,
            export_job_repository,
            run_job_in_background,
            payload.lookback_days,
            payload.forward_days,
            EXPORT_KIND_COMBINED,
        )
    try:
        result = await use_case.execute(
            lookback_days=payload.lookback_days,
            forward_days=payload.forward_days,
        )
    except FinancialDataError as exc:
        raise to_http_exception(exc) from exc
    return ExportFinancialDataResponse(
        rows_written=result.rows_written, file_id=result.file_id
    )
