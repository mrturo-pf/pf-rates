"""Export-job management routes: list, status, and cooperative cancellation.

Split out from exchange_rates.py (which keeps the CRUD + trigger
endpoints) to keep each route module focused on one sub-resource --
job lifecycle management is a distinct concern from rate data itself.

Lives under `/exports/jobs` (not nested under `/exchange-rates`) because
it is shared infrastructure across every export kind -- these routes read
`RAT_EXPORT_JOB` by id/status alone, agnostic to whether the job is an
`exchange_rates` or `combined` export (see `export_kind` on the response).
Both `POST /exchange-rates/export` and `POST /exports/financial-data`
point their async `monitor_url` here.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from rates.application.dto import ExportJobDTO
from rates.application.errors import (
    ExportJobNotCancellableError,
    ExportJobNotFoundError,
    FinancialDataValidationError,
)
from rates.application.ports.export_job_repository import ExportJobRepository
from rates.interfaces.api.dependencies import get_export_job_repository
from rates.interfaces.api.errors import to_http_exception
from rates.shared.constants import (
    EXPORT_JOB_ACTIVE_STATUSES,
    EXPORT_JOB_LIST_DEFAULT_LIMIT,
    EXPORT_JOB_LIST_MAX_LIMIT,
    EXPORT_JOB_STATUSES,
)

router = APIRouter(prefix="/exports/jobs", tags=["exports"])


class ExportJobStatusResponse(BaseModel):
    """Represent the current state of an async export job."""

    # jscpd:ignore-start -- this field-for-field mirrors ExportJobDTO
    # (application layer) by design: DTOs are the only thing allowed to
    # cross layer boundaries (see AGENTS.md), so the interface layer's
    # response schema legitimately restates them rather than importing an
    # application-layer type straight into a Pydantic response model.
    job_id: int
    status: str
    lookback_days: int
    forward_days: int
    export_kind: str
    rows_written: int | None
    file_id: str | None
    error_message: str | None
    cancel_requested_at: datetime | None
    total_items: int | None
    processed_items: int
    progress_percent: float | None
    created_at: datetime
    updated_at: datetime
    # jscpd:ignore-end


class ExportJobStopResponse(BaseModel):
    """Represent the outcome of requesting cancellation for one job."""

    job_id: int
    status: str
    cancel_requested_at: datetime | None


class ExportJobBulkStopResponse(BaseModel):
    """Represent the outcome of requesting cancellation for every active job."""

    jobs: list[ExportJobStopResponse]


def _progress_percent(job: ExportJobDTO) -> float | None:
    """Derive a 0-100 progress percentage from the job's raw item counts.

    Returns None when there is nothing meaningful to report yet -- a
    'pending' job has no total_items resolved, and a zero-item run (an
    empty currency list) has nothing to divide by. Rounded to one decimal
    place: enough precision to see movement on a large window without
    implying false accuracy.
    """
    if job.total_items is None or job.total_items == 0:
        return None
    return round(job.processed_items / job.total_items * 100, 1)


def _to_status_response(job: ExportJobDTO) -> ExportJobStatusResponse:
    """Map an ExportJobDTO to its API response shape."""
    return ExportJobStatusResponse(
        job_id=job.id,
        status=job.status,
        lookback_days=job.lookback_days,
        forward_days=job.forward_days,
        export_kind=job.export_kind,
        rows_written=job.rows_written,
        file_id=job.file_id,
        error_message=job.error_message,
        cancel_requested_at=job.cancel_requested_at,
        total_items=job.total_items,
        processed_items=job.processed_items,
        progress_percent=_progress_percent(job),
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _to_stop_response(job: ExportJobDTO) -> ExportJobStopResponse:
    """Map an ExportJobDTO to the stop-endpoint response shape."""
    return ExportJobStopResponse(
        job_id=job.id, status=job.status, cancel_requested_at=job.cancel_requested_at
    )


@router.get("", response_model=list[ExportJobStatusResponse])
async def list_export_jobs(
    status: str | None = Query(
        default=None,
        description=f"Filter by status. One of: {', '.join(EXPORT_JOB_STATUSES)}.",
    ),
    created_from: datetime | None = Query(
        default=None, description="Inclusive lower bound on created_at (ISO 8601)."
    ),
    created_to: datetime | None = Query(
        default=None, description="Inclusive upper bound on created_at (ISO 8601)."
    ),
    limit: int = Query(
        default=EXPORT_JOB_LIST_DEFAULT_LIMIT, ge=1, le=EXPORT_JOB_LIST_MAX_LIMIT
    ),
    offset: int = Query(default=0, ge=0),
    export_job_repository: ExportJobRepository = Depends(get_export_job_repository),
) -> list[ExportJobStatusResponse]:
    """List export jobs, newest first, optionally filtered by status/date range."""
    if status is not None and status not in EXPORT_JOB_STATUSES:
        raise to_http_exception(
            FinancialDataValidationError(
                f"Invalid status '{status}'. Must be one of: "
                f"{', '.join(EXPORT_JOB_STATUSES)}"
            )
        )
    jobs = await export_job_repository.list_jobs(
        status=status,
        created_from=created_from,
        created_to=created_to,
        limit=limit,
        offset=offset,
    )
    return [_to_status_response(job) for job in jobs]


@router.get("/{job_id}", response_model=ExportJobStatusResponse)
async def get_export_job(
    job_id: int,
    export_job_repository: ExportJobRepository = Depends(get_export_job_repository),
) -> ExportJobStatusResponse:
    """Return the current status of a previously-triggered async export job."""
    job = await export_job_repository.get(job_id)
    if job is None:
        raise to_http_exception(
            ExportJobNotFoundError(f"Export job {job_id} not found")
        )
    return _to_status_response(job)


@router.post("/stop", response_model=ExportJobBulkStopResponse)
async def stop_all_export_jobs(
    export_job_repository: ExportJobRepository = Depends(get_export_job_repository),
) -> ExportJobBulkStopResponse:
    """Request cooperative cancellation of every pending/running job.

    Best-effort: a job's own background loop only actually stops once it
    polls the flag at its next checkpoint (see
    EXPORT_CANCELLATION_CHECK_INTERVAL) -- this endpoint returns as soon
    as the flag is set in the DB, not once every job has fully unwound.
    Jobs that finish (succeed/fail) in the small window between listing
    active ids and requesting cancellation are silently skipped from the
    response rather than reported as stopped.
    """
    stopped = []
    for job_id in await export_job_repository.list_active_ids():
        job = await export_job_repository.request_cancel(job_id)
        if job is not None and job.status in EXPORT_JOB_ACTIVE_STATUSES:
            stopped.append(_to_stop_response(job))
    return ExportJobBulkStopResponse(jobs=stopped)


@router.post("/{job_id}/stop", response_model=ExportJobStopResponse)
async def stop_export_job(
    job_id: int,
    export_job_repository: ExportJobRepository = Depends(get_export_job_repository),
) -> ExportJobStopResponse:
    """Request cooperative cancellation of a single pending/running job.

    Returns 404 if the job does not exist, 409 if it is already in a
    terminal state (succeeded/failed/cancelled -- nothing left to stop).
    Otherwise sets the DB-side flag and returns immediately: the actual
    export loop stops itself at its next checkpoint, it is not killed
    synchronously by this call (see AGENTS.md / docs/api.md for why --
    no message queue in front of pf-rates, by deliberate cost choice).
    Calling this twice on the same job is safe (idempotent).
    """
    job = await export_job_repository.request_cancel(job_id)
    if job is None:
        raise to_http_exception(
            ExportJobNotFoundError(f"Export job {job_id} not found")
        )
    if job.status not in EXPORT_JOB_ACTIVE_STATUSES:
        raise to_http_exception(
            ExportJobNotCancellableError(
                f"Export job {job_id} is already '{job.status}' and cannot be stopped"
            )
        )
    return _to_stop_response(job)
