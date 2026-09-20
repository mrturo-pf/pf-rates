"""Tests for the ExportCombinedFinancialDataCsv use case."""

from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from rates.application.dto import CurrencyDTO, EconomicIndexDTO
from rates.application.use_cases._export_csv_shared import ExportCancelledSignal
from rates.application.use_cases.export_combined_financial_data_csv import (
    ExportCombinedFinancialDataCsv,
    SERIES_TYPE_ECONOMIC_INDEX,
    SERIES_TYPE_EXCHANGE_RATE,
)
from tests.unit.application._export_csv_test_doubles import (
    StubFileExport as _StubFileExport,
    StubMarketDataRepositoryBase,
    build_currency as _currency,
    build_exchange_rates_csv_use_case,
    read_csv_rows as _read_csv_rows,
)

_MODULE = "rates.application.use_cases.export_combined_financial_data_csv"
_EXCHANGE_MODULE = "rates.application.use_cases.export_exchange_rates_csv"

# Fixed "today" both this module's and export_exchange_rates_csv's
# datetime.now() are patched to return, so the date window is deterministic.
_TODAY = date(2024, 6, 15)


@contextmanager
def _frozen_today():
    """Patch datetime.now().date() to _TODAY in both exporter modules.

    ExportCombinedFinancialDataCsv delegates exchange-rate resolution to
    ExportExchangeRatesCsv, so both modules' `datetime` need patching for
    every test -- centralized here instead of repeating the same 6-line
    `with (patch(...), patch(...))` block in every single test.
    """
    with (
        patch(f"{_MODULE}.datetime") as mock_dt_combined,
        patch(f"{_EXCHANGE_MODULE}.datetime") as mock_dt_exchange,
    ):
        mock_dt_combined.now.return_value.date.return_value = _TODAY
        mock_dt_exchange.now.return_value.date.return_value = _TODAY
        yield


def _index(code: str, year: int, month: int, value: Decimal) -> EconomicIndexDTO:
    """Build a minimal EconomicIndexDTO for the given (code, year, month)."""
    return EconomicIndexDTO(
        code=code,
        period_year=year,
        period_month=month,
        index_value=value,
        monthly_change=None,
        yearly_change=None,
        base_period="DIC-2018",
        source="test",
    )


class _StubMarketDataRepository(StubMarketDataRepositoryBase):
    """Extend the shared base stub with economic-index storage."""

    def __init__(
        self,
        db_values: dict[date, Decimal],
        economic_indices: list[EconomicIndexDTO] | None = None,
    ) -> None:
        super().__init__(db_values)
        self._economic_indices = economic_indices or []

    async def list_economic_indices(self, code: str) -> list[EconomicIndexDTO]:
        """Return the preconfigured entries matching *code*."""
        return [entry for entry in self._economic_indices if entry.code == code]


def _build_use_case(
    currencies: list[CurrencyDTO],
    db_values: dict[date, Decimal],
    economic_indices: list[EconomicIndexDTO],
    file_export: _StubFileExport,
) -> ExportCombinedFinancialDataCsv:
    """Wire an ExportCombinedFinancialDataCsv with the given stub data."""
    market_data_repository = _StubMarketDataRepository(db_values, economic_indices)
    exchange_rates_csv = build_exchange_rates_csv_use_case(
        currencies, market_data_repository, file_export
    )
    return ExportCombinedFinancialDataCsv(
        market_data_repository, exchange_rates_csv, file_export
    )


@pytest.mark.asyncio
async def test_combines_exchange_rate_and_economic_index_rows() -> None:
    """A single CSV contains rows for both series types, correctly tagged."""
    db_values = {date(2024, 6, 15): Decimal("950.00")}
    economic_indices = [_index("IPC_CL", 2024, 6, Decimal("125.50"))]
    file_export = _StubFileExport()
    use_case = _build_use_case(
        [_currency("CLP"), _currency("USD")], db_values, economic_indices, file_export
    )

    with _frozen_today():
        result = await use_case.execute(lookback_days=0, forward_days=0)

    assert result.file_id == "drive-file-id"
    rows = _read_csv_rows(file_export.uploads[0][1])
    assert rows[0] == ["series_type", "code", "period_date", "value"]
    assert [SERIES_TYPE_EXCHANGE_RATE, "USD", "2024-06-15", "950.00"] in rows[1:]
    assert [SERIES_TYPE_ECONOMIC_INDEX, "IPC_CL", "2024-06-15", "125.50"] in rows[1:]
    assert result.rows_written == 2


@pytest.mark.asyncio
async def test_economic_index_value_expands_across_every_day_in_month() -> None:
    """One stored monthly value repeats for every day of the window in that month."""
    economic_indices = [_index("IPC_CL", 2024, 6, Decimal("125.50"))]
    file_export = _StubFileExport()
    use_case = _build_use_case([_currency("CLP")], {}, economic_indices, file_export)

    with _frozen_today():
        # lookback=2, forward=2 -> 2024-06-13..2024-06-17, all in June.
        result = await use_case.execute(lookback_days=2, forward_days=2)

    rows = _read_csv_rows(file_export.uploads[0][1])
    index_rows = [row for row in rows[1:] if row[0] == SERIES_TYPE_ECONOMIC_INDEX]
    assert {row[2] for row in index_rows} == {
        "2024-06-13",
        "2024-06-14",
        "2024-06-15",
        "2024-06-16",
        "2024-06-17",
    }
    assert all(row[3] == "125.50" for row in index_rows)
    assert result.rows_written == 5


@pytest.mark.asyncio
async def test_economic_index_month_with_no_stored_value_is_omitted() -> None:
    """Days in a month with nothing stored are omitted, not errored."""
    file_export = _StubFileExport()
    use_case = _build_use_case([_currency("CLP")], {}, [], file_export)

    with _frozen_today():
        result = await use_case.execute(lookback_days=0, forward_days=0)

    assert result.rows_written == 0
    rows = _read_csv_rows(file_export.uploads[0][1])
    assert rows == [["series_type", "code", "period_date", "value"]]


@pytest.mark.asyncio
async def test_never_invents_future_exchange_rate_values() -> None:
    """The combined export inherits the same future-date safety as exchange rates.

    Regression guard mirroring
    test_future_dates_never_carry_forward_a_past_cached_value in
    test_export_exchange_rates_csv.py -- this use case must not
    re-introduce that bug via a parallel resolution path.
    """
    db_values = {date(2024, 6, 15): Decimal("950.00")}
    file_export = _StubFileExport()
    use_case = _build_use_case(
        [_currency("CLP"), _currency("USD")], db_values, [], file_export
    )

    with _frozen_today():
        result = await use_case.execute(lookback_days=0, forward_days=5)

    rows = _read_csv_rows(file_export.uploads[0][1])
    exchange_rows = [row for row in rows[1:] if row[0] == SERIES_TYPE_EXCHANGE_RATE]
    assert exchange_rows == [[SERIES_TYPE_EXCHANGE_RATE, "USD", "2024-06-15", "950.00"]]
    assert result.rows_written == 1


@pytest.mark.asyncio
async def test_excludes_clp_from_exchange_rate_rows() -> None:
    """CLP is never queried as an exchange-rate series, same as the base export."""
    file_export = _StubFileExport()
    use_case = _build_use_case(
        [_currency("CLP")], {date(2024, 6, 15): Decimal("1")}, [], file_export
    )

    with _frozen_today():
        result = await use_case.execute(lookback_days=0, forward_days=0)

    assert result.rows_written == 0


@pytest.mark.asyncio
async def test_cancellation_check_stops_before_any_upload() -> None:
    """A cancellation flagged upfront skips the CSV upload entirely."""
    file_export = _StubFileExport()
    use_case = _build_use_case(
        [_currency("CLP"), _currency("USD")], {}, [], file_export
    )

    async def _always_cancelled() -> bool:
        return True

    with _frozen_today():
        with pytest.raises(ExportCancelledSignal):
            await use_case.execute(
                lookback_days=0, forward_days=0, cancellation_check=_always_cancelled
            )

    assert file_export.uploads == []


@pytest.mark.asyncio
async def test_progress_report_counts_both_series_types_up_front() -> None:
    """total_items counts (currencies + economic index codes) * dates."""
    file_export = _StubFileExport()
    use_case = _build_use_case(
        [_currency("CLP"), _currency("USD"), _currency("EUR")], {}, [], file_export
    )
    updates: list[tuple[int, int]] = []

    async def _record_progress(processed_items: int, total_items: int) -> None:
        updates.append((processed_items, total_items))

    with _frozen_today():
        # lookback=0, forward=0 -> 1 date; 2 currencies + 1 index code = 3.
        await use_case.execute(
            lookback_days=0, forward_days=0, progress_report=_record_progress
        )

    assert updates[0] == (0, 3)


@pytest.mark.asyncio
async def test_explicit_filename_overrides_default() -> None:
    """An explicit filename is forwarded to the file-export port as-is."""
    file_export = _StubFileExport()
    use_case = _build_use_case([_currency("USD")], {}, [], file_export)

    with _frozen_today():
        await use_case.execute(
            lookback_days=0, forward_days=0, filename="custom-financial-data.csv"
        )

    assert file_export.uploads[0][0] == "custom-financial-data.csv"
