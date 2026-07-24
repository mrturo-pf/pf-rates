"""Unit tests for reference data repository mapper methods."""

from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import pytest

from financial_data.application.dto import CurrencyDTO, IncomeTaxBracketDTO
from financial_data.infrastructure.db.repositories.reference_data_repository import (
    SqlAlchemyReferenceDataRepository,
)


@pytest.fixture
def repository() -> SqlAlchemyReferenceDataRepository:
    """Create a repository instance with a mock session."""
    mock_session = Mock()
    return SqlAlchemyReferenceDataRepository(session=mock_session)


def test_map_currency_rows_empty(
    repository: SqlAlchemyReferenceDataRepository,
) -> None:
    """Empty list of rows returns empty list of DTOs."""
    result = repository._map_currency_rows([])
    assert result == []


def test_map_currency_rows_single(
    repository: SqlAlchemyReferenceDataRepository,
) -> None:
    """Single row is correctly mapped to DTO."""
    mock_row = Mock()
    mock_row.code = "USD  "  # trailing spaces
    mock_row.name = "US Dollar"
    mock_row.is_fiat = True
    mock_row.unit_kind = "monetary"

    result = repository._map_currency_rows([mock_row])

    assert len(result) == 1
    dto = result[0]
    assert isinstance(dto, CurrencyDTO)
    assert dto.code == "USD"
    assert dto.name == "US Dollar"
    assert dto.is_fiat is True
    assert dto.unit_kind == "monetary"


def test_map_currency_rows_multiple(
    repository: SqlAlchemyReferenceDataRepository,
) -> None:
    """Multiple rows are correctly mapped."""
    row1 = Mock()
    row1.code = "USD"
    row1.name = "US Dollar"
    row1.is_fiat = True
    row1.unit_kind = "monetary"

    row2 = Mock()
    row2.code = "EUR"
    row2.name = "Euro"
    row2.is_fiat = True
    row2.unit_kind = "monetary"

    result = repository._map_currency_rows([row1, row2])

    assert len(result) == 2
    assert result[0].code == "USD"
    assert result[1].code == "EUR"


def test_map_income_tax_bracket_rows_empty(
    repository: SqlAlchemyReferenceDataRepository,
) -> None:
    """Empty list of rows returns empty list of DTOs."""
    result = repository._map_income_tax_bracket_rows([])
    assert result == []


def test_map_income_tax_bracket_rows_single(
    repository: SqlAlchemyReferenceDataRepository,
) -> None:
    """Single row is correctly mapped to DTO."""
    mock_row = Mock()
    mock_row.valid_from = date(2024, 1, 1)
    mock_row.valid_to = date(2024, 12, 31)
    mock_row.lower_bound_utm = Decimal("0")
    mock_row.upper_bound_utm = Decimal("13.5")
    mock_row.marginal_rate = Decimal("0.04")
    mock_row.rebate_utm = Decimal("0")

    result = repository._map_income_tax_bracket_rows([mock_row])

    assert len(result) == 1
    dto = result[0]
    assert isinstance(dto, IncomeTaxBracketDTO)
    assert dto.valid_from == date(2024, 1, 1)
    assert dto.valid_to == date(2024, 12, 31)
    assert dto.lower_bound_utm == Decimal("0")
    assert dto.upper_bound_utm == Decimal("13.5")
    assert dto.marginal_rate == Decimal("0.04")
    assert dto.rebate_utm == Decimal("0")


def test_map_income_tax_bracket_rows_multiple(
    repository: SqlAlchemyReferenceDataRepository,
) -> None:
    """Multiple rows are correctly mapped."""
    row1 = Mock()
    row1.valid_from = date(2024, 1, 1)
    row1.valid_to = date(2024, 12, 31)
    row1.lower_bound_utm = Decimal("0")
    row1.upper_bound_utm = Decimal("13.5")
    row1.marginal_rate = Decimal("0.04")
    row1.rebate_utm = Decimal("0")

    row2 = Mock()
    row2.valid_from = date(2024, 1, 1)
    row2.valid_to = date(2024, 12, 31)
    row2.lower_bound_utm = Decimal("13.5")
    row2.upper_bound_utm = Decimal("30")
    row2.marginal_rate = Decimal("0.08")
    row2.rebate_utm = Decimal("0.54")

    result = repository._map_income_tax_bracket_rows([row1, row2])

    assert len(result) == 2
    assert result[0].lower_bound_utm == Decimal("0")
    assert result[1].lower_bound_utm == Decimal("13.5")
