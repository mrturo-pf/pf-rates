"""Tests for market-data repository query and validation branches."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from rates.application.dto import ExchangeRateWriteDTO, RefreshRatesCommandDTO
from rates.application.errors import FinancialDataValidationError
from rates.infrastructure.db.repositories.market_data_repository import (
    SqlAlchemyMarketDataRepository,
)


@pytest.mark.asyncio
async def test_list_exchange_rates_maps_query_rows() -> None:
    """List exchange rates maps rows returned by the async session."""
    row = SimpleNamespace(
        currency_code="USD ",
        rate_date=date(2026, 1, 2),
        value_clp=Decimal("950"),
        source="test",
    )
    result = Mock()
    result.scalars.return_value.all.return_value = [row]
    session = Mock()
    session.execute = AsyncMock(return_value=result)

    values = await SqlAlchemyMarketDataRepository(session).list_exchange_rates("USD")

    assert values[0].currency_code == "USD"
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_economic_index_value_returns_scalar() -> None:
    """Economic index lookup returns the scalar database value."""
    result = Mock()
    result.scalar_one_or_none.return_value = Decimal("38000")
    session = Mock()
    session.execute = AsyncMock(return_value=result)

    value = await SqlAlchemyMarketDataRepository(session).get_economic_index_value(
        "UF", 2026, 1
    )

    assert value == Decimal("38000")


@pytest.mark.asyncio
async def test_refresh_rates_rejects_unknown_currency() -> None:
    """Refresh rejects rates whose currency is absent from the reference table."""
    result = Mock()
    result.scalars.return_value.all.return_value = []
    session = Mock()
    session.execute = AsyncMock(return_value=result)
    command = RefreshRatesCommandDTO(
        exchange_rates=[
            ExchangeRateWriteDTO(
                currency_code="ZZZ",
                rate_date=date(2026, 1, 2),
                value_clp=Decimal("1"),
            )
        ]
    )

    with pytest.raises(FinancialDataValidationError, match="Unknown currencies"):
        await SqlAlchemyMarketDataRepository(session).refresh_rates(command)
