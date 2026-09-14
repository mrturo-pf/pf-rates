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
async def test_repository_rebind_swaps_to_a_real_new_session(
    pg_url: str, db_session: AsyncSession
) -> None:
    """rebind() to a second, independent real session keeps working correctly.

    Mirrors what ExportJobSessionSwapper does mid-export: replace a
    (possibly stale) session with a fresh one on an already-constructed
    repository. Uses a genuinely separate SQLAlchemy session/connection
    from the same DB (not just the same db_session fixture) so this
    exercises the real rebind path, not merely a Python attribute swap.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from tests.conftest import _TC_ENGINE_KWARGS

    repo = SqlAlchemyExportJobRepository(db_session)
    job_id = await repo.create(lookback_days=1, forward_days=0)

    engine = create_async_engine(pg_url, **_TC_ENGINE_KWARGS)
    other_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with other_factory() as other_session:
        repo.rebind(other_session)
        await repo.mark_running(job_id)
        await repo.update_progress(job_id, processed_items=5, total_items=10)

        job = await repo.get(job_id)
        assert job is not None
        assert job.status == "running"
        assert job.processed_items == 5
        assert job.total_items == 10
    await engine.dispose()


@pytest.mark.asyncio
async def test_repository_update_progress(db_session: AsyncSession) -> None:
    """update_progress persists processed_items/total_items on the row."""
    repo = SqlAlchemyExportJobRepository(db_session)
    job_id = await repo.create(lookback_days=1, forward_days=0)

    await repo.update_progress(job_id, processed_items=5, total_items=20)

    job = await repo.get(job_id)
    assert job is not None
    assert job.processed_items == 5
    assert job.total_items == 20


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
async def test_get_export_job_endpoint_reports_progress_percent(
    http_client: AsyncClient, db_session: AsyncSession
) -> None:
    """GET /exchange-rates/export/jobs/{id} derives progress_percent from the DB row."""
    repo = SqlAlchemyExportJobRepository(db_session)
    job_id = await repo.create(lookback_days=1, forward_days=0)
    await repo.mark_running(job_id)
    await repo.update_progress(job_id, processed_items=3, total_items=12)
    await db_session.commit()

    response = await http_client.get(f"/exchange-rates/export/jobs/{job_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["total_items"] == 12
    assert body["processed_items"] == 3
    assert body["progress_percent"] == 25.0


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


@pytest.mark.asyncio
async def test_run_export_job_in_background_survives_a_forced_session_refresh(
    pg_url: str, monkeypatch: object
) -> None:
    """A mid-run DB session swap doesn't break the job -- it still completes.

    Forces ExportJobSessionSwapper to refresh at every single checkpoint
    (interval=0, always due) instead of the real 120s, and forces a
    checkpoint on every processed item (EXPORT_CANCELLATION_CHECK_INTERVAL=1)
    so several real session swaps happen mid-loop against a real Postgres --
    this is the actual reliability fix for the production failure where a
    single long-held session went stale partway through a large export.
    """
    from datetime import datetime
    from decimal import Decimal
    from zoneinfo import ZoneInfo

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    import rates.application.use_cases.export_exchange_rates_csv as csv_module
    import rates.interfaces.api.dependencies as deps_module
    from rates.application.dto import ExchangeRateWriteDTO, RefreshRatesCommandDTO
    from rates.domain.normalization import normalize_exchange_rate_lookup_date
    from rates.infrastructure.db.repositories.market_data_repository import (
        SqlAlchemyMarketDataRepository,
    )
    from tests.conftest import _TC_ENGINE_KWARGS

    monkeypatch.setattr(deps_module, "EXPORT_SESSION_REFRESH_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(csv_module, "EXPORT_CANCELLATION_CHECK_INTERVAL", 1)

    engine = create_async_engine(pg_url, **_TC_ENGINE_KWARGS)
    test_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(deps_module, "SessionLocal", test_factory)

    class _StubFileExport:
        async def upload(self, filename: str, content: bytes, mime_type: str) -> str:
            """Return a fixed fake storage id without touching any network."""
            return "drive-refresh-stub"

    monkeypatch.setattr(deps_module, "get_file_export_port", lambda: _StubFileExport())

    seeded_codes = ("USD", "EUR", "UF", "UTM")
    today = datetime.now(tz=ZoneInfo("America/Santiago")).date()
    try:
        async with test_factory() as seed_session:
            repo = SqlAlchemyMarketDataRepository(seed_session)
            await repo.refresh_rates(
                RefreshRatesCommandDTO(
                    exchange_rates=[
                        ExchangeRateWriteDTO(
                            currency_code=code,
                            rate_date=normalize_exchange_rate_lookup_date(code, today),
                            value_clp=Decimal("1000.00"),
                            source="test",
                        )
                        for code in seeded_codes
                    ]
                )
            )

            job_repository = SqlAlchemyExportJobRepository(seed_session)
            # 3-day window x 4 currencies = 12 items -> 12 forced checkpoints,
            # each one triggering a real session close + fresh session open.
            job_id = await job_repository.create(lookback_days=2, forward_days=0)

        await deps_module.run_export_job_in_background(
            job_id, lookback_days=2, forward_days=0
        )

        async with test_factory() as check_session:
            job = await SqlAlchemyExportJobRepository(check_session).get(job_id)
        assert job is not None
        assert job.status == "succeeded"
        assert job.file_id == "drive-refresh-stub"
        assert job.processed_items == job.total_items
    finally:
        # This module's tests share one DB/table across the whole test
        # session (see the list_active_ids comment above) -- clean up the
        # rows this test seeded so other integration test files (which
        # assert exact exchange-rate contents, e.g. test_market_data_api.py)
        # never see them, regardless of file/test execution order.
        async with test_factory() as cleanup_session:
            await cleanup_session.execute(
                text('DELETE FROM "RAT_EXCH_RATE" WHERE currency_code = ANY(:codes)'),
                {"codes": list(seeded_codes)},
            )
            await cleanup_session.commit()
        await engine.dispose()
