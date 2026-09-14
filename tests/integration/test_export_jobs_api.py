"""Integration tests for export-job listing and cooperative cancellation.

Split out from test_market_data_api.py (which already covers the basic
create/mark_running/mark_succeeded/mark_failed lifecycle) to keep each
file focused and under a manageable size -- this one owns everything
added for GET /exchange-rates/export/jobs (list) and the stop endpoints.

Uses testcontainers (PostgreSQL) + httpx AsyncClient against the real
FastAPI app. Fixtures (pg_url, db_session, http_client) are defined in
conftest.py.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from rates.infrastructure.db.repositories.export_job_repository import (
    SqlAlchemyExportJobRepository,
)


@pytest.mark.asyncio
async def test_repository_mark_cancelled(db_session: AsyncSession) -> None:
    """mark_cancelled transitions a job straight to 'cancelled'."""
    repo = SqlAlchemyExportJobRepository(db_session)
    job_id = await repo.create(lookback_days=1, forward_days=0)

    await repo.mark_cancelled(job_id)

    job = await repo.get(job_id)
    assert job is not None
    assert job.status == "cancelled"


@pytest.mark.asyncio
async def test_repository_list_jobs_filters_by_status(
    db_session: AsyncSession,
) -> None:
    """list_jobs(status=...) only returns jobs in that status."""
    repo = SqlAlchemyExportJobRepository(db_session)
    succeeded_id = await repo.create(lookback_days=1, forward_days=0)
    await repo.mark_succeeded(succeeded_id, rows_written=10, file_id="drive-a")
    failed_id = await repo.create(lookback_days=2, forward_days=0)
    await repo.mark_failed(failed_id, "boom")

    succeeded_jobs = await repo.list_jobs(status="succeeded")
    assert {job.id for job in succeeded_jobs} == {succeeded_id}

    failed_jobs = await repo.list_jobs(status="failed")
    assert {job.id for job in failed_jobs} == {failed_id}


@pytest.mark.asyncio
async def test_repository_list_jobs_filters_by_created_range(
    db_session: AsyncSession,
) -> None:
    """list_jobs(created_from=..., created_to=...) narrows by created_at."""
    repo = SqlAlchemyExportJobRepository(db_session)
    job_id = await repo.create(lookback_days=1, forward_days=0)
    job = await repo.get(job_id)
    assert job is not None

    one_year_ahead = job.created_at.replace(year=job.created_at.year + 1)
    future_window = await repo.list_jobs(created_from=one_year_ahead)
    assert future_window == []

    one_year_ago = job.created_at.replace(year=job.created_at.year - 1)
    past_window = await repo.list_jobs(created_from=one_year_ago)
    assert any(j.id == job_id for j in past_window)

    # created_to excludes anything created after the given upper bound.
    excluded_by_upper_bound = await repo.list_jobs(created_to=one_year_ago)
    assert job_id not in {j.id for j in excluded_by_upper_bound}

    included_by_upper_bound = await repo.list_jobs(created_to=one_year_ahead)
    assert any(j.id == job_id for j in included_by_upper_bound)


@pytest.mark.asyncio
async def test_repository_request_cancel_active_job(db_session: AsyncSession) -> None:
    """request_cancel sets cancel_requested_at on a pending/running job."""
    repo = SqlAlchemyExportJobRepository(db_session)
    job_id = await repo.create(lookback_days=1, forward_days=0)

    updated = await repo.request_cancel(job_id)

    assert updated is not None
    assert updated.status == "pending"
    assert updated.cancel_requested_at is not None
    assert await repo.is_cancel_requested(job_id) is True


@pytest.mark.asyncio
async def test_repository_request_cancel_is_idempotent(
    db_session: AsyncSession,
) -> None:
    """Calling request_cancel twice keeps the original timestamp."""
    repo = SqlAlchemyExportJobRepository(db_session)
    job_id = await repo.create(lookback_days=1, forward_days=0)

    first = await repo.request_cancel(job_id)
    second = await repo.request_cancel(job_id)

    assert first is not None and second is not None
    assert first.cancel_requested_at == second.cancel_requested_at


@pytest.mark.asyncio
async def test_repository_request_cancel_on_terminal_job_is_a_noop(
    db_session: AsyncSession,
) -> None:
    """A succeeded job cannot be cancelled -- the row comes back unchanged."""
    repo = SqlAlchemyExportJobRepository(db_session)
    job_id = await repo.create(lookback_days=1, forward_days=0)
    await repo.mark_succeeded(job_id, rows_written=1, file_id="drive-a")

    updated = await repo.request_cancel(job_id)

    assert updated is not None
    assert updated.status == "succeeded"
    assert updated.cancel_requested_at is None


@pytest.mark.asyncio
async def test_repository_request_cancel_unknown_job_returns_none(
    db_session: AsyncSession,
) -> None:
    """request_cancel on a nonexistent id returns None, not an error."""
    repo = SqlAlchemyExportJobRepository(db_session)
    assert await repo.request_cancel(999999) is None


@pytest.mark.asyncio
async def test_repository_list_active_ids(db_session: AsyncSession) -> None:
    """list_active_ids returns only pending/running jobs."""
    repo = SqlAlchemyExportJobRepository(db_session)
    pending_id = await repo.create(lookback_days=1, forward_days=0)
    running_id = await repo.create(lookback_days=1, forward_days=0)
    await repo.mark_running(running_id)
    succeeded_id = await repo.create(lookback_days=1, forward_days=0)
    await repo.mark_succeeded(succeeded_id, rows_written=1, file_id="drive-a")

    active_ids = set(await repo.list_active_ids())

    # Other tests in this module share the same DB session/table and may
    # leave their own pending/running rows behind, so assert a superset
    # (this job's ids are present) plus the one hard exclusion that
    # actually matters: a succeeded job must never show up as "active".
    assert {pending_id, running_id} <= active_ids
    assert succeeded_id not in active_ids


@pytest.mark.asyncio
async def test_list_export_jobs_endpoint_filters_by_status(
    http_client: AsyncClient, db_session: AsyncSession
) -> None:
    """GET /exchange-rates/export/jobs?status=... filters through the real DB."""
    repo = SqlAlchemyExportJobRepository(db_session)
    succeeded_id = await repo.create(lookback_days=1, forward_days=0)
    await repo.mark_succeeded(succeeded_id, rows_written=1, file_id="drive-a")
    await db_session.commit()

    response = await http_client.get(
        "/exchange-rates/export/jobs", params={"status": "succeeded"}
    )

    assert response.status_code == 200
    job_ids = {job["job_id"] for job in response.json()}
    assert succeeded_id in job_ids


@pytest.mark.asyncio
async def test_stop_endpoint_flags_a_pending_job(
    http_client: AsyncClient, db_session: AsyncSession
) -> None:
    """POST .../jobs/{id}/stop sets the DB flag without changing status yet."""
    repo = SqlAlchemyExportJobRepository(db_session)
    job_id = await repo.create(lookback_days=1, forward_days=0)
    await db_session.commit()

    response = await http_client.post(f"/exchange-rates/export/jobs/{job_id}/stop")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert body["cancel_requested_at"] is not None


@pytest.mark.asyncio
async def test_stop_endpoint_returns_409_for_succeeded_job(
    http_client: AsyncClient, db_session: AsyncSession
) -> None:
    """POST .../jobs/{id}/stop refuses to cancel a job that already finished."""
    repo = SqlAlchemyExportJobRepository(db_session)
    job_id = await repo.create(lookback_days=1, forward_days=0)
    await repo.mark_succeeded(job_id, rows_written=1, file_id="drive-a")
    await db_session.commit()

    response = await http_client.post(f"/exchange-rates/export/jobs/{job_id}/stop")

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_bulk_stop_endpoint_stops_every_active_job(
    http_client: AsyncClient, db_session: AsyncSession
) -> None:
    """POST /exchange-rates/export/jobs/stop cancels every pending/running job."""
    repo = SqlAlchemyExportJobRepository(db_session)
    pending_id = await repo.create(lookback_days=1, forward_days=0)
    succeeded_id = await repo.create(lookback_days=1, forward_days=0)
    await repo.mark_succeeded(succeeded_id, rows_written=1, file_id="drive-a")
    await db_session.commit()

    response = await http_client.post("/exchange-rates/export/jobs/stop")

    assert response.status_code == 200
    stopped_ids = {job["job_id"] for job in response.json()["jobs"]}
    assert pending_id in stopped_ids
    assert succeeded_id not in stopped_ids


@pytest.mark.asyncio
async def test_run_export_job_in_background_stops_when_cancelled_upfront(
    pg_url: str, monkeypatch: object
) -> None:
    """A job cancelled before its BackgroundTask ever runs never touches Drive.

    Mirrors test_run_export_job_in_background_persists_success in
    test_market_data_api.py, but for the cancellation path: get_file_export_port
    is stubbed to raise if called at all, asserting the upload step is truly
    skipped -- not just that the final status happens to read 'cancelled'.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    import rates.interfaces.api.dependencies as deps_module
    from tests.conftest import _TC_ENGINE_KWARGS

    engine = create_async_engine(pg_url, **_TC_ENGINE_KWARGS)
    test_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(deps_module, "SessionLocal", test_factory)

    def _fail_if_called() -> None:
        raise AssertionError(
            "get_file_export_port must never be called once cancellation "
            "was requested before the job started running"
        )

    monkeypatch.setattr(deps_module, "get_file_export_port", _fail_if_called)

    async with test_factory() as seed_session:
        job_repository = SqlAlchemyExportJobRepository(seed_session)
        job_id = await job_repository.create(lookback_days=0, forward_days=0)
        await job_repository.request_cancel(job_id)

    await deps_module.run_export_job_in_background(
        job_id, lookback_days=0, forward_days=0
    )

    async with test_factory() as check_session:
        job = await SqlAlchemyExportJobRepository(check_session).get(job_id)
    assert job is not None
    assert job.status == "cancelled"
    assert job.file_id is None
    await engine.dispose()
