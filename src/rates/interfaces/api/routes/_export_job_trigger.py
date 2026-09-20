"""Shared "create + dispatch an async export job" flow.

Both `exchange_rates.py` (`POST /exchange-rates/export`) and `exports.py`
(`POST /exports/financial-data`) offer the exact same `async_execution`
contract: create a job row, schedule the background task, and return a
202-style response with a `job_id` and `monitor_url`. Only the
`export_kind` they pass differs. Extracted here so that identical flow
(and its response model) exists in exactly one place.
"""

from collections.abc import Callable

from fastapi import BackgroundTasks, Response
from pydantic import BaseModel

from rates.application.ports.export_job_repository import ExportJobRepository
from rates.shared.constants import EXPORT_JOB_STATUS_PENDING

_JOB_STATUS_MONITOR_PATH = "/exports/jobs"


class ExportJobTriggeredResponse(BaseModel):
    """Represent the response for an asynchronously triggered export job."""

    job_id: int
    status: str
    monitor_url: str


async def trigger_async_export_job(
    background_tasks: BackgroundTasks,
    response: Response,
    export_job_repository: ExportJobRepository,
    run_job_in_background: Callable[[int, int, int, str], object],
    lookback_days: int,
    forward_days: int,
    export_kind: str,
) -> ExportJobTriggeredResponse:
    """Create an export job row, schedule it in the background, return 202.

    Job status/cancellation endpoints are shared infrastructure across
    every export kind (they read `RAT_EXPORT_JOB` by id), so the
    monitor_url is the same path regardless of export_kind.
    """
    job_id = await export_job_repository.create(
        lookback_days, forward_days, export_kind
    )
    background_tasks.add_task(
        run_job_in_background, job_id, lookback_days, forward_days, export_kind
    )
    response.status_code = 202
    return ExportJobTriggeredResponse(
        job_id=job_id,
        status=EXPORT_JOB_STATUS_PENDING,
        monitor_url=f"{_JOB_STATUS_MONITOR_PATH}/{job_id}",
    )
