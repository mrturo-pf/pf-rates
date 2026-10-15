"""Tests for financial-data ORM column mappings."""

from rates.infrastructure.db.models.financial_data import EconomicIndexModel


def test_economic_index_maps_period_attributes_to_accrual_columns() -> None:
    """Keep Python compatibility while targeting the accrual schema columns."""
    assert EconomicIndexModel.__table__.c.accrual_year.name == "accrual_year"
    assert EconomicIndexModel.__table__.c.accrual_month.name == "accrual_month"
