"""Tests for reference-data repository query branches."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from rates.infrastructure.db.repositories.reference_data_repository import (
    SqlAlchemyReferenceDataRepository,
)


@pytest.mark.asyncio
async def test_list_income_tax_brackets_maps_query_rows() -> None:
    """Filtered bracket queries map rows returned by the async session."""
    row = SimpleNamespace(
        valid_from=date(2026, 1, 1),
        valid_to=None,
        lower_bound_utm=Decimal("0"),
        upper_bound_utm=None,
        marginal_rate=Decimal("0.04"),
        rebate_utm=Decimal("0"),
    )
    result = Mock()
    result.scalars.return_value.all.return_value = [row]
    session = Mock()
    session.execute = AsyncMock(return_value=result)

    values = await SqlAlchemyReferenceDataRepository(session).list_income_tax_brackets(
        2026
    )

    assert values[0].valid_from == date(2026, 1, 1)


@pytest.mark.asyncio
async def test_get_income_tax_bracket_maps_matching_row() -> None:
    """Bracket lookup maps a matching database row."""
    row = SimpleNamespace(
        valid_from=date(2026, 1, 1),
        valid_to=None,
        lower_bound_utm=Decimal("0"),
        upper_bound_utm=None,
        marginal_rate=Decimal("0.04"),
        rebate_utm=Decimal("0"),
    )
    result = Mock()
    result.scalar_one_or_none.return_value = row
    session = Mock()
    session.execute = AsyncMock(return_value=result)

    value = await SqlAlchemyReferenceDataRepository(session).get_income_tax_bracket(
        date(2026, 1, 1), Decimal("1")
    )

    assert value is not None
    assert value.marginal_rate == Decimal("0.04")


@pytest.mark.asyncio
async def test_get_income_tax_bracket_returns_none_when_unmatched() -> None:
    """Bracket lookup returns None when no row matches."""
    result = Mock()
    result.scalar_one_or_none.return_value = None
    session = Mock()
    session.execute = AsyncMock(return_value=result)

    value = await SqlAlchemyReferenceDataRepository(session).get_income_tax_bracket(
        date(2026, 1, 1), Decimal("999")
    )

    assert value is None
