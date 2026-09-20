"""Unit tests for the export-job management routes (list, status, stop)."""

from datetime import UTC, datetime as dt, timedelta

import pytest
from httpx import AsyncClient

from rates.application.dto import ExportJobDTO
from rates.interfaces.api.dependencies import (
    get_export_job_repository,
    get_sync_use_case,
)
from rates.interfaces.api.main import app
from rates.shared.constants import (
    EXPORT_JOB_ACTIVE_STATUSES,
    EXPORT_KIND_EXCHANGE_RATES,
)
from tests.unit.interfaces._http_client_support import AUTHED, StubSyncUseCase


class _StubExportJobRepository:
    """In-memory stand-in implementing the full ExportJobRepository shape."""

    def __init__(self) -> None:
        self.jobs: dict[int, ExportJobDTO] = {}

    def seed(self, job: ExportJobDTO) -> None:
        """Insert a pre-built job row directly, bypassing create()."""
        self.jobs[job.id] = job

    async def create(
        self, lookback_days: int, forward_days: int, export_kind: str = ""
    ) -> int:
        """Unused by these tests -- jobs are seeded directly via seed()."""
        raise NotImplementedError

    async def mark_running(self, job_id: int) -> None:
        """Unused by these route tests."""

    async def mark_succeeded(
        self, job_id: int, rows_written: int, file_id: str
    ) -> None:
        """Unused by these route tests."""

    async def mark_failed(self, job_id: int, error_message: str) -> None:
        """Unused by these route tests."""

    async def mark_cancelled(self, job_id: int) -> None:
        """Unused by these route tests -- RunExportJob owns this transition."""

    async def update_progress(
        self, job_id: int, processed_items: int, total_items: int
    ) -> None:
        """Unused by these route tests -- RunExportJob owns progress updates."""

    async def get(self, job_id: int) -> ExportJobDTO | None:
        """Return the seeded job, or None if it doesn't exist."""
        return self.jobs.get(job_id)

    async def list_jobs(
        self,
        status: str | None = None,
        created_from: dt | None = None,
        created_to: dt | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ExportJobDTO]:
        """Filter/paginate the seeded jobs the same way the SQL repo would."""
        jobs = sorted(self.jobs.values(), key=lambda j: j.created_at, reverse=True)
        if status is not None:
            jobs = [j for j in jobs if j.status == status]
        if created_from is not None:
            jobs = [j for j in jobs if j.created_at >= created_from]
        if created_to is not None:
            jobs = [j for j in jobs if j.created_at <= created_to]
        return jobs[offset : offset + limit]

    async def request_cancel(self, job_id: int) -> ExportJobDTO | None:
        """Set cancel_requested_at if the job is active; otherwise no-op."""
        job = self.jobs.get(job_id)
        if job is None:
            return None
        if job.status not in EXPORT_JOB_ACTIVE_STATUSES:
            return job
        if job.cancel_requested_at is not None:
            return job
        updated = ExportJobDTO(
            id=job.id,
            status=job.status,
            lookback_days=job.lookback_days,
            forward_days=job.forward_days,
            export_kind=job.export_kind,
            rows_written=job.rows_written,
            file_id=job.file_id,
            error_message=job.error_message,
            cancel_requested_at=dt.now(UTC),
            total_items=job.total_items,
            processed_items=job.processed_items,
            created_at=job.created_at,
            updated_at=dt.now(UTC),
        )
        self.jobs[job_id] = updated
        return updated

    async def is_cancel_requested(self, job_id: int) -> bool:
        """Unused by these route tests."""
        job = self.jobs.get(job_id)
        return job is not None and job.cancel_requested_at is not None

    async def list_active_ids(self) -> list[int]:
        """Return ids of every seeded job in an active status."""
        return [
            job.id
            for job in self.jobs.values()
            if job.status in EXPORT_JOB_ACTIVE_STATUSES
        ]


def _job(
    job_id: int,
    status: str,
    created_at: dt | None = None,
    cancel_requested_at: dt | None = None,
    total_items: int | None = None,
    processed_items: int = 0,
) -> ExportJobDTO:
    """Build a minimal ExportJobDTO for seeding the stub repository."""
    now = created_at or dt.now(UTC)
    return ExportJobDTO(
        id=job_id,
        status=status,
        lookback_days=90,
        forward_days=30,
        export_kind=EXPORT_KIND_EXCHANGE_RATES,
        rows_written=500 if status == "succeeded" else None,
        file_id="drive-x" if status == "succeeded" else None,
        error_message="boom" if status == "failed" else None,
        cancel_requested_at=cancel_requested_at,
        total_items=total_items,
        processed_items=processed_items,
        created_at=now,
        updated_at=now,
    )


def _override(job_repository: _StubExportJobRepository) -> None:
    """Wire the stub repository and a no-op sync use case into the app."""
    app.dependency_overrides[get_export_job_repository] = lambda: job_repository
    app.dependency_overrides[get_sync_use_case] = lambda: StubSyncUseCase()


@pytest.mark.asyncio
async def test_get_export_job_returns_current_status() -> None:
    """GET /exports/jobs/{id} returns the job's stored state."""
    job_repository = _StubExportJobRepository()
    job_repository.seed(_job(1, "succeeded"))
    _override(job_repository)
    try:
        async with AsyncClient(**AUTHED) as client:
            response = await client.get("/exports/jobs/1")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "succeeded"
        assert body["rows_written"] == 500
        assert body["file_id"] == "drive-x"
        assert body["cancel_requested_at"] is None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_export_job_reports_progress_percent_while_running() -> None:
    """A running job with known totals exposes a derived progress_percent."""
    job_repository = _StubExportJobRepository()
    job_repository.seed(_job(1, "running", total_items=200, processed_items=50))
    _override(job_repository)
    try:
        async with AsyncClient(**AUTHED) as client:
            response = await client.get("/exports/jobs/1")
        assert response.status_code == 200
        body = response.json()
        assert body["total_items"] == 200
        assert body["processed_items"] == 50
        assert body["progress_percent"] == 25.0
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_export_job_progress_percent_is_null_before_total_is_known() -> None:
    """A pending job (total_items not yet resolved) reports no percentage."""
    job_repository = _StubExportJobRepository()
    job_repository.seed(_job(1, "pending"))
    _override(job_repository)
    try:
        async with AsyncClient(**AUTHED) as client:
            response = await client.get("/exports/jobs/1")
        assert response.status_code == 200
        body = response.json()
        assert body["total_items"] is None
        assert body["processed_items"] == 0
        assert body["progress_percent"] is None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_export_job_returns_404_when_missing() -> None:
    """GET /exports/jobs/{id} returns 404 for an unknown job."""
    _override(_StubExportJobRepository())
    try:
        async with AsyncClient(**AUTHED) as client:
            response = await client.get("/exports/jobs/999999")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_export_jobs_returns_every_job_newest_first() -> None:
    """GET /exports/jobs with no filters lists everything."""
    job_repository = _StubExportJobRepository()
    older = dt.now(UTC) - timedelta(hours=1)
    newer = dt.now(UTC)
    job_repository.seed(_job(1, "succeeded", created_at=older))
    job_repository.seed(_job(2, "running", created_at=newer))
    _override(job_repository)
    try:
        async with AsyncClient(**AUTHED) as client:
            response = await client.get("/exports/jobs")
        assert response.status_code == 200
        body = response.json()
        assert [job["job_id"] for job in body] == [2, 1]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_export_jobs_filters_by_status() -> None:
    """GET /exports/jobs?status=... only returns matching jobs."""
    job_repository = _StubExportJobRepository()
    job_repository.seed(_job(1, "succeeded"))
    job_repository.seed(_job(2, "failed"))
    _override(job_repository)
    try:
        async with AsyncClient(**AUTHED) as client:
            response = await client.get("/exports/jobs", params={"status": "failed"})
        assert response.status_code == 200
        body = response.json()
        assert [job["job_id"] for job in body] == [2]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_export_jobs_rejects_invalid_status() -> None:
    """An unrecognised status value is rejected with 400, not silently ignored."""
    _override(_StubExportJobRepository())
    try:
        async with AsyncClient(**AUTHED) as client:
            response = await client.get(
                "/exports/jobs", params={"status": "not-a-real-status"}
            )
        assert response.status_code == 400
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_export_jobs_filters_by_created_range() -> None:
    """created_from/created_to narrow the results to that window."""
    job_repository = _StubExportJobRepository()
    old = dt.now(UTC) - timedelta(days=10)
    recent = dt.now(UTC)
    job_repository.seed(_job(1, "succeeded", created_at=old))
    job_repository.seed(_job(2, "succeeded", created_at=recent))
    _override(job_repository)
    try:
        async with AsyncClient(**AUTHED) as client:
            response = await client.get(
                "/exports/jobs",
                params={"created_from": (recent - timedelta(hours=1)).isoformat()},
            )
        assert response.status_code == 200
        body = response.json()
        assert [job["job_id"] for job in body] == [2]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_stop_export_job_sets_cancel_requested_at() -> None:
    """POST .../jobs/{id}/stop flags a running job without failing it."""
    job_repository = _StubExportJobRepository()
    job_repository.seed(_job(1, "running"))
    _override(job_repository)
    try:
        async with AsyncClient(**AUTHED) as client:
            response = await client.post("/exports/jobs/1/stop")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "running"  # not flipped synchronously
        assert body["cancel_requested_at"] is not None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_stop_export_job_returns_404_when_missing() -> None:
    """POST .../jobs/{id}/stop returns 404 for an unknown job."""
    _override(_StubExportJobRepository())
    try:
        async with AsyncClient(**AUTHED) as client:
            response = await client.post("/exports/jobs/999999/stop")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_stop_export_job_returns_409_when_already_terminal() -> None:
    """POST .../jobs/{id}/stop rejects a job that already finished."""
    job_repository = _StubExportJobRepository()
    job_repository.seed(_job(1, "succeeded"))
    _override(job_repository)
    try:
        async with AsyncClient(**AUTHED) as client:
            response = await client.post("/exports/jobs/1/stop")
        assert response.status_code == 409
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_stop_export_job_is_idempotent() -> None:
    """Calling stop twice on the same active job is safe and returns 200 both times."""
    job_repository = _StubExportJobRepository()
    job_repository.seed(_job(1, "pending"))
    _override(job_repository)
    try:
        async with AsyncClient(**AUTHED) as client:
            first = await client.post("/exports/jobs/1/stop")
            second = await client.post("/exports/jobs/1/stop")
        assert first.status_code == 200
        assert second.status_code == 200
        assert (
            first.json()["cancel_requested_at"] == second.json()["cancel_requested_at"]
        )
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_stop_all_export_jobs_only_touches_active_ones() -> None:
    """POST /exports/jobs/stop stops pending/running jobs only."""
    job_repository = _StubExportJobRepository()
    job_repository.seed(_job(1, "pending"))
    job_repository.seed(_job(2, "running"))
    job_repository.seed(_job(3, "succeeded"))
    _override(job_repository)
    try:
        async with AsyncClient(**AUTHED) as client:
            response = await client.post("/exports/jobs/stop")
        assert response.status_code == 200
        body = response.json()
        stopped_ids = {job["job_id"] for job in body["jobs"]}
        assert stopped_ids == {1, 2}
        assert job_repository.jobs[3].cancel_requested_at is None
    finally:
        app.dependency_overrides.clear()
