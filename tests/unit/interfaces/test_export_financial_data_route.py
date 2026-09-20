"""Unit tests for the POST /exports/financial-data route."""

import pytest
from httpx import AsyncClient

from rates.application.dto import ExportExchangeRatesResultDTO
from rates.application.errors import FinancialDataDependencyConfigurationError
from rates.interfaces.api.dependencies import (
    get_export_combined_financial_data_csv_use_case,
    get_export_job_background_runner,
    get_export_job_repository,
    get_sync_use_case,
)
from rates.interfaces.api.main import app
from rates.shared.constants import EXPORT_KIND_COMBINED
from tests.unit.interfaces._export_job_test_support import (
    StubCsvExportUseCase as _StubExportCombinedFinancialDataCsv,
    StubExportJobRepository as _StubExportJobRepository,
    noop_background_runner as _noop_background_runner,
)
from tests.unit.interfaces._http_client_support import AUTHED, StubSyncUseCase

# Short alias: the real dependency name is long enough that every override
# line using it verbatim blows past the line-length limit.
_get_combined_csv_use_case = get_export_combined_financial_data_csv_use_case


@pytest.mark.asyncio
async def test_export_financial_data_returns_rows_and_file_id() -> None:
    """POST /exports/financial-data returns the use case's row count and file id."""
    stub = _StubExportCombinedFinancialDataCsv(
        result=ExportExchangeRatesResultDTO(rows_written=7, file_id="drive-combo")
    )
    app.dependency_overrides[_get_combined_csv_use_case] = lambda: stub
    app.dependency_overrides[get_sync_use_case] = lambda: StubSyncUseCase()
    try:
        async with AsyncClient(**AUTHED) as client:
            response = await client.post("/exports/financial-data", json={})
        assert response.status_code == 200
        assert response.json() == {"rows_written": 7, "file_id": "drive-combo"}
        assert stub.calls == [(90, 30)]  # defaults
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_export_financial_data_returns_503_when_drive_not_configured() -> None:
    """A dependency-configuration error (Drive not set up yet) surfaces as 503."""
    stub = _StubExportCombinedFinancialDataCsv(
        error=FinancialDataDependencyConfigurationError(
            "Google Drive export is not configured."
        )
    )
    app.dependency_overrides[_get_combined_csv_use_case] = lambda: stub
    app.dependency_overrides[get_sync_use_case] = lambda: StubSyncUseCase()
    try:
        async with AsyncClient(**AUTHED) as client:
            response = await client.post("/exports/financial-data", json={})
        assert response.status_code == 503
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_export_financial_data_async_returns_202_with_combined_kind() -> None:
    """The async flag creates a job tagged with the 'combined' export_kind."""
    sync_stub = _StubExportCombinedFinancialDataCsv()
    job_repository = _StubExportJobRepository()
    app.dependency_overrides[_get_combined_csv_use_case] = lambda: sync_stub
    app.dependency_overrides[get_export_job_repository] = lambda: job_repository
    app.dependency_overrides[get_export_job_background_runner] = lambda: (
        _noop_background_runner
    )
    app.dependency_overrides[get_sync_use_case] = lambda: StubSyncUseCase()
    try:
        payload = {"lookback_days": 10, "forward_days": 5, "async": True}
        async with AsyncClient(**AUTHED) as client:
            response = await client.post("/exports/financial-data", json=payload)
        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "pending"
        assert body["monitor_url"] == f"/exchange-rates/export/jobs/{body['job_id']}"
        assert job_repository.create_calls == [(10, 5, EXPORT_KIND_COMBINED)]
        assert sync_stub.calls == []
    finally:
        app.dependency_overrides.clear()
