"""HTTP tests for batched market-data lookup routes."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from rates.application.dto import (
    EconomicIndexValueLookupDTO,
    ExchangeRateValueLookupDTO,
)
from rates.interfaces.api.dependencies import (
    get_economic_index_values_use_case,
    get_exchange_rate_values_use_case,
)
from rates.interfaces.api.main import app

_AUTHED = {
    "transport": ASGITransport(app=app),
    "base_url": "http://test",
    "headers": {"X-API-Key": "test-key"},
}


class _ExchangeUseCase:
    """Stub exchange-rate batch use case."""

    async def execute(
        self, pairs: list[tuple[str, date]], today: date
    ) -> list[ExchangeRateValueLookupDTO]:
        """Return one deterministic result per input pair."""
        return [
            ExchangeRateValueLookupDTO(code, rate_date, Decimal("950"))
            for code, rate_date in pairs
        ]


class _IndexUseCase:
    """Stub economic-index batch use case."""

    async def execute(
        self, pairs: list[tuple[str, int, int]]
    ) -> list[EconomicIndexValueLookupDTO]:
        """Return one deterministic result per input pair."""
        return [
            EconomicIndexValueLookupDTO(code, year, month, Decimal("112.5"))
            for code, year, month in pairs
        ]


async def _post_with_override(
    dependency: Any, use_case: Any, path: str, payload: dict[str, object]
) -> Any:
    """POST with a temporary dependency override."""
    app.dependency_overrides[dependency] = lambda: use_case
    try:
        async with AsyncClient(**_AUTHED) as client:
            return await client.post(path, json=payload)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_batch_exchange_rate_route_preserves_results() -> None:
    """POST /exchange-rates/values serializes all requested pairs."""
    response = await _post_with_override(
        get_exchange_rate_values_use_case,
        _ExchangeUseCase(),
        "/exchange-rates/values",
        {
            "pairs": [
                {"currency_code": "USD", "rate_date": "2026-01-15"},
                {"currency_code": "EUR", "rate_date": "2026-01-15"},
            ]
        },
    )
    assert response.status_code == 200
    assert response.json()["results"][1]["currency_code"] == "EUR"
    assert response.json()["results"][0]["value_clp"] == "950"


@pytest.mark.asyncio
async def test_batch_economic_index_route_preserves_results() -> None:
    """POST /economic-indices/values serializes all requested pairs."""
    response = await _post_with_override(
        get_economic_index_values_use_case,
        _IndexUseCase(),
        "/economic-indices/values",
        {"pairs": [{"code": "IPC_CL", "period_year": 2026, "period_month": 1}]},
    )
    assert response.status_code == 200
    assert response.json()["results"][0]["index_value"] == "112.5"


@pytest.mark.asyncio
async def test_batch_exchange_rate_route_rejects_more_than_500_pairs() -> None:
    """POST /exchange-rates/values enforces the documented batch cap."""
    response = await _post_with_override(
        get_exchange_rate_values_use_case,
        _ExchangeUseCase(),
        "/exchange-rates/values",
        {"pairs": [{"currency_code": "USD", "rate_date": "2026-01-15"}] * 501},
    )
    assert response.status_code == 422
