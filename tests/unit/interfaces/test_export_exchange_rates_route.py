"""Unit tests for the POST /exchange-rates/export route."""

from datetime import UTC, datetime as dt

import pytest
from httpx import AsyncClient

from rates.application.dto import ExportExchangeRatesResultDTO, ExportJobDTO
from rates.application.errors import FinancialDataDependencyConfigurationError
from rates.interfaces.api.dependencies import (
    get_export_exchange_rates_csv_use_case,
    get_export_job_background_runner,
    get_export_job_repository,
    get_sync_use_case,
)
from rates.interfaces.api.main import app
from rates.shared.constants import EXPORT_KIND_EXCHANGE_RATES
from tests.unit.interfaces._http_client_support import AUTHED, StubSyncUseCase


class _StubExportExchangeRatesCsv:
    """Stub ExportExchangeRatesCsv use case recording every call."""

    def __init__(
        self,
        result: ExportExchangeRatesResultDTO | None = None,
        error: Exception | None = None,
    ) -> None:
        self._result = result
        self._error = error
        self.calls: list[tuple[int, int]] = []

    async def execute(
        self, lookback_days: int, forward_days: int, filename: str | None = None
    ) -> ExportExchangeRatesResultDTO:
        """Record the call, then return the stub result or raise the stub error."""
        self.calls.append((lookback_days, forward_days))
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


class _StubExportJobRepository:
    """In-memory stand-in for ExportJobRepository, keyed by an incrementing id."""

    def __init__(self) -> None:
        self._next_id = 1
        self.jobs: dict[int, ExportJobDTO] = {}
        self.create_calls: list[tuple[int, int, str]] = []

    async def create(
        self,
        lookback_days: int,
        forward_days: int,
        export_kind: str = EXPORT_KIND_EXCHANGE_RATES,
    ) -> int:
        """Insert a fake pending job and return its id."""
        self.create_calls.append((lookback_days, forward_days, export_kind))
        job_id = self._next_id
        self._next_id += 1
        now = dt.now(UTC)
        self.jobs[job_id] = ExportJobDTO(
            id=job_id,
            status="pending",
            lookback_days=lookback_days,
            forward_days=forward_days,
            export_kind=export_kind,
            rows_written=None,
            file_id=None,
            error_message=None,
            cancel_requested_at=None,
            total_items=None,
            processed_items=0,
            created_at=now,
            updated_at=now,
        )
        return job_id

    async def mark_running(self, job_id: int) -> None:
        """Unused by these route tests -- the stub runner never calls it."""

    async def mark_succeeded(
        self, job_id: int, rows_written: int, file_id: str
    ) -> None:
        """Unused by these route tests -- the stub runner never calls it."""

    async def mark_failed(self, job_id: int, error_message: str) -> None:
        """Unused by these route tests -- the stub runner never calls it."""

    async def get(self, job_id: int) -> ExportJobDTO | None:
        """Return the fake job DTO, or None if it was never created."""
        return self.jobs.get(job_id)


async def _noop_background_runner(
    job_id: int,
    lookback_days: int,
    forward_days: int,
    export_kind: str = EXPORT_KIND_EXCHANGE_RATES,
) -> None:
    """Stub background runner that never touches a real database session."""


@pytest.mark.asyncio
async def test_export_exchange_rates_returns_rows_and_file_id() -> None:
    """POST /exchange-rates/export returns the use case's row count and file id."""
    stub = _StubExportExchangeRatesCsv(
        result=ExportExchangeRatesResultDTO(rows_written=42, file_id="drive-abc")
    )
    app.dependency_overrides[get_export_exchange_rates_csv_use_case] = lambda: stub
    app.dependency_overrides[get_sync_use_case] = lambda: StubSyncUseCase()
    try:
        async with AsyncClient(**AUTHED) as client:
            response = await client.post("/exchange-rates/export", json={})
        assert response.status_code == 200
        body = response.json()
        assert body == {"rows_written": 42, "file_id": "drive-abc"}
        assert stub.calls == [(90, 30)]  # defaults
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_export_exchange_rates_forwards_custom_window() -> None:
    """Custom lookback_days/forward_days are passed through to the use case."""
    stub = _StubExportExchangeRatesCsv(
        result=ExportExchangeRatesResultDTO(rows_written=0, file_id="drive-xyz")
    )
    app.dependency_overrides[get_export_exchange_rates_csv_use_case] = lambda: stub
    app.dependency_overrides[get_sync_use_case] = lambda: StubSyncUseCase()
    try:
        async with AsyncClient(**AUTHED) as client:
            response = await client.post(
                "/exchange-rates/export",
                json={"lookback_days": 5, "forward_days": 2},
            )
        assert response.status_code == 200
        assert stub.calls == [(5, 2)]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_export_exchange_rates_returns_503_when_drive_not_configured() -> None:
    """A dependency-configuration error (Drive not set up yet) surfaces as 503."""
    stub = _StubExportExchangeRatesCsv(
        error=FinancialDataDependencyConfigurationError(
            "Google Drive export is not configured."
        )
    )
    app.dependency_overrides[get_export_exchange_rates_csv_use_case] = lambda: stub
    app.dependency_overrides[get_sync_use_case] = lambda: StubSyncUseCase()
    try:
        async with AsyncClient(**AUTHED) as client:
            response = await client.post("/exchange-rates/export", json={})
        assert response.status_code == 503
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_export_exchange_rates_async_returns_202_with_job_id() -> None:
    """Setting the async flag returns 202 with a job_id, skipping the sync path."""
    sync_stub = _StubExportExchangeRatesCsv()
    job_repository = _StubExportJobRepository()
    app.dependency_overrides[get_export_exchange_rates_csv_use_case] = lambda: sync_stub
    app.dependency_overrides[get_export_job_repository] = lambda: job_repository
    app.dependency_overrides[get_export_job_background_runner] = lambda: (
        _noop_background_runner
    )
    app.dependency_overrides[get_sync_use_case] = lambda: StubSyncUseCase()
    try:
        payload = {"lookback_days": 6100, "forward_days": 30}
        payload["async"] = True
        async with AsyncClient(**AUTHED) as client:
            response = await client.post("/exchange-rates/export", json=payload)
        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "pending"
        assert body["monitor_url"] == f"/exchange-rates/export/jobs/{body['job_id']}"
        assert job_repository.create_calls == [(6100, 30, EXPORT_KIND_EXCHANGE_RATES)]
        # The synchronous use case must never be invoked in the async path.
        assert sync_stub.calls == []
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_export_exchange_rates_defaults_to_sync_without_async_flag() -> None:
    """Omitting the async flag keeps the existing synchronous behavior."""
    stub = _StubExportExchangeRatesCsv(
        result=ExportExchangeRatesResultDTO(rows_written=7, file_id="drive-def")
    )
    app.dependency_overrides[get_export_exchange_rates_csv_use_case] = lambda: stub
    app.dependency_overrides[get_sync_use_case] = lambda: StubSyncUseCase()
    try:
        async with AsyncClient(**AUTHED) as client:
            response = await client.post("/exchange-rates/export", json={})
        assert response.status_code == 200
        assert response.json() == {"rows_written": 7, "file_id": "drive-def"}
    finally:
        app.dependency_overrides.clear()


# GET /exchange-rates/export/jobs/{id} (and the list/stop endpoints) are
# tested in test_export_jobs_route.py, alongside the routes' own module.
