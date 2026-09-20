"""SQLAlchemy repository for async export-job tracking."""

from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update

from rates.application.dto import ExportJobDTO
from rates.infrastructure.db.models.financial_data import ExportJobModel
from rates.infrastructure.db.repositories._session_bound import (
    SessionBoundRepositoryMixin,
)
from rates.shared.constants import (
    EXPORT_JOB_ACTIVE_STATUSES,
    EXPORT_JOB_STATUS_CANCELLED,
    EXPORT_JOB_STATUS_FAILED,
    EXPORT_JOB_STATUS_RUNNING,
    EXPORT_JOB_STATUS_SUCCEEDED,
    EXPORT_KIND_EXCHANGE_RATES,
)


class SqlAlchemyExportJobRepository(SessionBoundRepositoryMixin):
    """SQLAlchemy-backed implementation of ExportJobRepository."""

    async def create(
        self,
        lookback_days: int,
        forward_days: int,
        export_kind: str = EXPORT_KIND_EXCHANGE_RATES,
    ) -> int:
        """Insert a new job row in 'pending' status and return its id."""
        job = ExportJobModel(
            lookback_days=lookback_days,
            forward_days=forward_days,
            export_kind=export_kind,
        )
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

    async def mark_cancelled(self, job_id: int) -> None:
        """Transition the job to 'cancelled'."""
        await self._update(job_id, status=EXPORT_JOB_STATUS_CANCELLED)

    async def update_progress(
        self, job_id: int, processed_items: int, total_items: int
    ) -> None:
        """Record how far a running job has gotten."""
        await self._update(
            job_id, processed_items=processed_items, total_items=total_items
        )

    async def get(self, job_id: int) -> ExportJobDTO | None:
        """Return the job's current state, or None if it does not exist."""
        job = await self._session.get(ExportJobModel, job_id)
        return self._to_dto(job) if job is not None else None

    async def list_jobs(
        self,
        status: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ExportJobDTO]:
        """Return jobs matching the given filters, newest first."""
        query = select(ExportJobModel).order_by(ExportJobModel.created_at.desc())
        if status is not None:
            query = query.where(ExportJobModel.status == status)
        if created_from is not None:
            query = query.where(ExportJobModel.created_at >= created_from)
        if created_to is not None:
            query = query.where(ExportJobModel.created_at <= created_to)
        query = query.limit(limit).offset(offset)
        result = await self._session.execute(query)
        return [self._to_dto(job) for job in result.scalars().all()]

    async def request_cancel(self, job_id: int) -> ExportJobDTO | None:
        """Request cancellation of a pending/running job.

        A single conditional UPDATE (WHERE status IN active statuses AND
        cancel_requested_at IS NULL) avoids a race with the background
        job's own mark_succeeded/mark_failed calls -- a job that just
        finished cannot be "un-finished" by a stop request that arrives
        a moment later.
        """
        await self._session.execute(
            update(ExportJobModel)
            .where(
                ExportJobModel.id == job_id,
                ExportJobModel.status.in_(EXPORT_JOB_ACTIVE_STATUSES),
                ExportJobModel.cancel_requested_at.is_(None),
            )
            .values(cancel_requested_at=func.now(), updated_at=func.now())
        )
        await self._session.commit()
        # Read back regardless of whether the UPDATE matched a row: it's a
        # no-op (0 rows) when the job doesn't exist, is already terminal, or
        # already had cancellation requested -- the caller tells those apart
        # by inspecting the returned state, not by rowcount.
        return await self.get(job_id)

    async def is_cancel_requested(self, job_id: int) -> bool:
        """Cheap read-only check polled by the running export loop."""
        result = await self._session.execute(
            select(ExportJobModel.cancel_requested_at).where(
                ExportJobModel.id == job_id
            )
        )
        cancel_requested_at = result.scalar_one_or_none()
        return cancel_requested_at is not None

    async def list_active_ids(self) -> list[int]:
        """Return ids of every job in 'pending' or 'running' status."""
        result = await self._session.execute(
            select(ExportJobModel.id).where(
                ExportJobModel.status.in_(EXPORT_JOB_ACTIVE_STATUSES)
            )
        )
        return list(result.scalars().all())

    @staticmethod
    def _to_dto(job: ExportJobModel) -> ExportJobDTO:
        """Map an ExportJobModel row to its DTO."""
        return ExportJobDTO(
            id=job.id,
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
