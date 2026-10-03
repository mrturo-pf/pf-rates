"""Tests for batched market-data lookup use cases."""

from datetime import date
from decimal import Decimal
import pytest

from rates.application.dto import EconomicIndexDTO
from rates.application.use_cases.get_economic_index_values import GetEconomicIndexValues
from rates.application.use_cases.get_exchange_rate_values import GetExchangeRateValues


class _Repository:
    """Minimal market-data repository fake for batch tests."""

    def __init__(self) -> None:
        self.exchange_values: dict[date, Decimal] = {}
        self.index_entries: list[EconomicIndexDTO] = []
        self.exchange_calls: list[tuple[str, date, date]] = []
        self.index_calls: list[str | None] = []

    async def list_exchange_rate_values(
        self, code: str, start: date, end: date
    ) -> dict[date, Decimal]:
        """Return stored values and record the requested span."""
        self.exchange_calls.append((code, start, end))
        return self.exchange_values

    async def list_economic_indices(
        self, code: str | None = None
    ) -> list[EconomicIndexDTO]:
        """Return stored index entries and record the code."""
        self.index_calls.append(code)
        return self.index_entries


class _SingularExchangeRate:
    """Singular fallback fake that should not run for cached values."""

    async def execute(self, currency_code: str, rate_date: date) -> Decimal:
        """Fail if the bulk cache did not resolve the pair."""
        raise AssertionError(f"unexpected fallback for {currency_code} {rate_date}")


@pytest.mark.asyncio
async def test_exchange_rate_batch_groups_pairs_by_currency() -> None:
    """One range fetch is made per distinct currency and input order is preserved."""
    repository = _Repository()
    repository.exchange_values = {
        date(2026, 1, 15): Decimal("950"),
        date(2026, 2, 15): Decimal("960"),
    }
    pairs = [
        ("USD", date(2026, 1, 15)),
        ("EUR", date(2026, 2, 15)),
        ("USD", date(2026, 2, 15)),
    ]
    use_case = GetExchangeRateValues(repository, _SingularExchangeRate())

    result = await use_case.execute(pairs, date(2026, 3, 1))

    assert [item.currency_code for item in result] == ["USD", "EUR", "USD"]
    assert len(repository.exchange_calls) == 2
    assert {call[0] for call in repository.exchange_calls} == {"USD", "EUR"}


@pytest.mark.asyncio
async def test_exchange_rate_batch_empty_input_does_not_query() -> None:
    """An empty exchange-rate batch returns empty without repository calls."""
    repository = _Repository()
    use_case = GetExchangeRateValues(repository, _SingularExchangeRate())

    assert await use_case.execute([], date(2026, 3, 1)) == []
    assert repository.exchange_calls == []


@pytest.mark.asyncio
async def test_economic_index_batch_groups_by_code_and_degrades_missing_pair() -> None:
    """One full-series fetch serves multiple periods and missing values become None."""
    repository = _Repository()
    repository.index_entries = [
        EconomicIndexDTO(
            code="IPC_CL",
            period_year=2026,
            period_month=1,
            index_value=Decimal("110"),
            monthly_change=None,
            yearly_change=None,
            base_period="DIC-2018",
            source="test",
        )
    ]
    use_case = GetEconomicIndexValues(repository)

    result = await use_case.execute(
        [("IPC_CL", 2026, 1), ("IPC_CL", 2026, 2), ("IPC_CL", 2026, 1)]
    )

    assert [item.index_value for item in result] == [
        Decimal("110"),
        None,
        Decimal("110"),
    ]
    assert repository.index_calls == ["IPC_CL"]


@pytest.mark.asyncio
async def test_economic_index_batch_empty_input_does_not_query() -> None:
    """An empty economic-index batch returns empty without repository calls."""
    repository = _Repository()
    use_case = GetEconomicIndexValues(repository)

    assert await use_case.execute([]) == []
    assert repository.index_calls == []
