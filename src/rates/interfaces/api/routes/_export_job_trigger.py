"""Shared "create + dispatch an async export job" flow.

Used by `exports.py` (`POST /exports/financial-data`) to offer the
`async_execution` contract: create a job row, schedule the background
task, and return a 202-style response with a `job_id` and `monitor_url`.

Extracted into its own module (rather than living inline in exports.py)
since job-trigger logic is exactly the kind of thing that tends to grow
a second consumer over time; keeping it isolated and independently
testable costs nothing today and avoids re-extracting it later.
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
    run_job_in_background: Callable[[int, int, int], object],
    lookback_days: int,
    forward_days: int,
) -> ExportJobTriggeredResponse:
    """Create an export job row, schedule it in the background, return 202."""
    job_id = await export_job_repository.create(lookback_days, forward_days)
    background_tasks.add_task(
        run_job_in_background, job_id, lookback_days, forward_days
    )
    response.status_code = 202
    return ExportJobTriggeredResponse(
        job_id=job_id,
        status=EXPORT_JOB_STATUS_PENDING,
        monitor_url=f"{_JOB_STATUS_MONITOR_PATH}/{job_id}",
    )
