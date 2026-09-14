"""SQLAlchemy repository for async export-job tracking."""

from typing import Any

from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession

from rates.application.dto import ExportJobDTO
from rates.infrastructure.db.models.financial_data import ExportJobModel
from rates.shared.constants import (
    EXPORT_JOB_STATUS_FAILED,
    EXPORT_JOB_STATUS_RUNNING,
    EXPORT_JOB_STATUS_SUCCEEDED,
)


class SqlAlchemyExportJobRepository:
    """SQLAlchemy-backed implementation of ExportJobRepository."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the instance."""
        self._session = session

    async def create(self, lookback_days: int, forward_days: int) -> int:
        """Insert a new job row in 'pending' status and return its id."""
        job = ExportJobModel(lookback_days=lookback_days, forward_days=forward_days)
        self._session.add(job)
        await self._session.commit()
        await self._session.refresh(job)
        return job.id

    async def mark_running(self, job_id: int) -> None:
        """Transition the job to 'running'."""
        await self._update(job_id, status=EXPORT_JOB_STATUS_RUNNING)

    async def mark_succeeded(
        self, job_id: int, rows_written: int, file_id: str
    ) -> None:
        """Transition the job to 'succeeded' and record the export result."""
        await self._update(
            job_id,
            status=EXPORT_JOB_STATUS_SUCCEEDED,
            rows_written=rows_written,
            file_id=file_id,
        )

    async def mark_failed(self, job_id: int, error_message: str) -> None:
        """Transition the job to 'failed' and record the error message."""
        await self._update(
            job_id, status=EXPORT_JOB_STATUS_FAILED, error_message=error_message
        )

    async def get(self, job_id: int) -> ExportJobDTO | None:
        """Return the job's current state, or None if it does not exist."""
        job = await self._session.get(ExportJobModel, job_id)
        if job is None:
            return None
        return ExportJobDTO(
            id=job.id,
            status=job.status,
            lookback_days=job.lookback_days,
            forward_days=job.forward_days,
            rows_written=job.rows_written,
            file_id=job.file_id,
            error_message=job.error_message,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )

    async def _update(self, job_id: int, **fields: Any) -> None:
        """Update the given fields plus updated_at, committing immediately.

        Committed right away (not batched) so that a status check from a
        *different* Cloud Run instance sees progress as soon as it happens --
        the background task and the polling request never share a session.

        updated_at uses the DB server's own clock (func.now()), matching
        created_at's server_default -- mixing a Python-side datetime.now()
        for one column with the DB's clock for the other can make
        updated_at < created_at look true under real clock skew between the
        app process and the database host.
        """
        await self._session.execute(
            update(ExportJobModel)
            .where(ExportJobModel.id == job_id)
            .values(updated_at=func.now(), **fields)
        )
        await self._session.commit()
