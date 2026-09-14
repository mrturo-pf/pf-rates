"""Port definition for async export-job persistence."""

from typing import Protocol

from rates.application.dto import ExportJobDTO


class ExportJobRepository(Protocol):
    """Persistence port for RAT_EXPORT_JOB rows.

    Backs the `POST /exchange-rates/export {"async": true}` flow. State
    lives in the DB (not in-process memory) because Cloud Run can run
    multiple instances and scale to zero -- any instance must be able to
    create/update/read a job regardless of which instance handled the
    triggering request or the background execution.
    """

    async def create(self, lookback_days: int, forward_days: int) -> int:
        """Insert a new job row in 'pending' status and return its id."""
        ...

    async def mark_running(self, job_id: int) -> None:
        """Transition the job to 'running'."""
        ...

    async def mark_succeeded(
        self, job_id: int, rows_written: int, file_id: str
    ) -> None:
        """Transition the job to 'succeeded' and record the export result."""
        ...

    async def mark_failed(self, job_id: int, error_message: str) -> None:
        """Transition the job to 'failed' and record the error message."""
        ...

    async def get(self, job_id: int) -> ExportJobDTO | None:
        """Return the job's current state, or None if it does not exist."""
        ...
