"""Unit tests for market data repository mapper methods."""

from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import pytest

from financial_data.application.dto import EconomicIndexDTO, ExchangeRateDTO
from financial_data.infrastructure.db.repositories.market_data_repository import (
    SqlAlchemyMarketDataRepository,
)


@pytest.fixture
def repository() -> SqlAlchemyMarketDataRepository:
    """Create a repository instance with a mock session."""
    mock_session = Mock()
    return SqlAlchemyMarketDataRepository(session=mock_session)


def test_map_exchange_rate_rows_empty(
    repository: SqlAlchemyMarketDataRepository,
) -> None:
    """Empty list of rows returns empty list of DTOs."""
    result = repository._map_exchange_rate_rows([])
    assert result == []


def test_map_exchange_rate_rows_single(
    repository: SqlAlchemyMarketDataRepository,
) -> None:
    """Single row is correctly mapped to DTO."""
    mock_row = Mock()
    mock_row.currency_code = "USD  "  # trailing spaces
    mock_row.rate_date = date(2024, 1, 15)
    mock_row.value_clp = Decimal("920.50")
    mock_row.source = "test_source"

    result = repository._map_exchange_rate_rows([mock_row])

    assert len(result) == 1
    dto = result[0]
    assert isinstance(dto, ExchangeRateDTO)
    assert dto.currency_code == "USD"
    assert dto.rate_date == date(2024, 1, 15)
    assert dto.value_clp == Decimal("920.50")
    assert dto.source == "test_source"


def test_map_exchange_rate_rows_multiple(
    repository: SqlAlchemyMarketDataRepository,
) -> None:
    """Multiple rows are correctly mapped."""
    row1 = Mock()
    row1.currency_code = "USD"
    row1.rate_date = date(2024, 1, 15)
    row1.value_clp = Decimal("920.50")
    row1.source = "source1"

    row2 = Mock()
    row2.currency_code = "EUR"
    row2.rate_date = date(2024, 1, 16)
    row2.value_clp = Decimal("1000.00")
    row2.source = "source2"

    result = repository._map_exchange_rate_rows([row1, row2])

    assert len(result) == 2
    assert result[0].currency_code == "USD"
    assert result[1].currency_code == "EUR"


def test_map_economic_index_rows_empty(
    repository: SqlAlchemyMarketDataRepository,
) -> None:
    """Empty list of rows returns empty list of DTOs."""
    result = repository._map_economic_index_rows([])
    assert result == []


def test_map_economic_index_rows_single(
    repository: SqlAlchemyMarketDataRepository,
) -> None:
    """Single row is correctly mapped to DTO."""
    mock_row = Mock()
    mock_row.code = "UF"
    mock_row.period_year = 2024
    mock_row.period_month = 1
    mock_row.index_value = Decimal("36000.50")
    mock_row.monthly_change = Decimal("0.5")
    mock_row.yearly_change = Decimal("3.2")
    mock_row.base_period = "2013"
    mock_row.source = "test_source"

    result = repository._map_economic_index_rows([mock_row])

    assert len(result) == 1
    dto = result[0]
    assert isinstance(dto, EconomicIndexDTO)
    assert dto.code == "UF"
    assert dto.period_year == 2024
    assert dto.period_month == 1
    assert dto.index_value == Decimal("36000.50")
    assert dto.monthly_change == Decimal("0.5")
    assert dto.yearly_change == Decimal("3.2")
    assert dto.base_period == "2013"
    assert dto.source == "test_source"


def test_map_economic_index_rows_multiple(
    repository: SqlAlchemyMarketDataRepository,
) -> None:
    """Multiple rows are correctly mapped."""
    row1 = Mock()
    row1.code = "UF"
    row1.period_year = 2024
    row1.period_month = 1
    row1.index_value = Decimal("36000.50")
    row1.monthly_change = Decimal("0.5")
    row1.yearly_change = Decimal("3.2")
    row1.base_period = "2013"
    row1.source = "source1"

    row2 = Mock()
    row2.code = "UTM"
    row2.period_year = 2024
    row2.period_month = 2
    row2.index_value = Decimal("65000.00")
    row2.monthly_change = Decimal("1.0")
    row2.yearly_change = Decimal("4.5")
    row2.base_period = "2014"
    row2.source = "source2"

    result = repository._map_economic_index_rows([row1, row2])

    assert len(result) == 2
    assert result[0].code == "UF"
    assert result[1].code == "UTM"
