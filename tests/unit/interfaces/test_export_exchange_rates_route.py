"""Unit tests for the POST /exchange-rates/export route."""

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from rates.application.dto import ExportExchangeRatesResultDTO
from rates.application.errors import FinancialDataDependencyConfigurationError
from rates.interfaces.api.dependencies import (
    get_export_exchange_rates_csv_use_case,
    get_sync_use_case,
)
from rates.interfaces.api.main import app

_AUTHED: dict[str, Any] = {
    "transport": ASGITransport(app=app),
    "base_url": "http://test",
    "headers": {"X-API-Key": "test-key"},
}


class _StubSyncUseCase:
    """No-op stub so app startup/route wiring never triggers a real sync."""

    async def execute(self, **_: object) -> None:
        """Do nothing."""
        return None


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


@pytest.mark.asyncio
async def test_export_exchange_rates_returns_rows_and_file_id() -> None:
    """POST /exchange-rates/export returns the use case's row count and file id."""
    stub = _StubExportExchangeRatesCsv(
        result=ExportExchangeRatesResultDTO(rows_written=42, file_id="drive-abc")
    )
    app.dependency_overrides[get_export_exchange_rates_csv_use_case] = lambda: stub
    app.dependency_overrides[get_sync_use_case] = lambda: _StubSyncUseCase()
    try:
        async with AsyncClient(**_AUTHED) as client:
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
    app.dependency_overrides[get_sync_use_case] = lambda: _StubSyncUseCase()
    try:
        async with AsyncClient(**_AUTHED) as client:
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
    app.dependency_overrides[get_sync_use_case] = lambda: _StubSyncUseCase()
    try:
        async with AsyncClient(**_AUTHED) as client:
            response = await client.post("/exchange-rates/export", json={})
        assert response.status_code == 503
    finally:
        app.dependency_overrides.clear()
