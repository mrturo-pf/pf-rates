"""Tests for the ExportExchangeRatesCsv use case."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from rates.application.dto import CurrencyDTO, ExchangeRateWriteDTO
from rates.application.use_cases._export_csv_shared import ExportCancelledSignal
from rates.application.use_cases.export_exchange_rates_csv import (
    ExportExchangeRatesCsv,
)
from rates.application.use_cases.get_exchange_rate_value import (
    GetExchangeRateValue,
)
from tests.unit.application._export_csv_test_doubles import (
    StubMarketDataRepositoryBase as _StubMarketDataRepository,
    StubReferenceDataRepository as _StubReferenceDataRepository,
    build_currency as _currency,
    build_exchange_rates_csv_use_case,
    read_csv_rows as _read_csv_rows,
)

_MODULE = "rates.application.use_cases.export_exchange_rates_csv"

# Fixed "today" the module's datetime.now() is patched to return, so the
# resulting date window is fully deterministic.
_TODAY = date(2024, 6, 15)


class _StubFxRateProviderWithEntry:
    """FxRateProvider test double that resolves exactly one (code, date) pair."""

    def __init__(self, currency_code: str, rate_date: date, value: Decimal) -> None:
        self._currency_code = currency_code
        self._rate_date = rate_date
        self._value = value

    async def fetch_rate_entry(
        self, currency_code: str, on: date
    ) -> ExchangeRateWriteDTO | None:
        """Return the preconfigured entry for the matching pair, else None."""
        if currency_code == self._currency_code and on == self._rate_date:
            return ExchangeRateWriteDTO(
                currency_code=currency_code,
                rate_date=on,
                value_clp=self._value,
                source="provider",
            )
        return None


class _StubFileExport:
    """FileExportPort test double that records the last upload call."""

    def __init__(self, file_id: str = "drive-file-id") -> None:
        self._file_id = file_id
        self.uploads: list[tuple[str, bytes, str]] = []

    async def upload(self, filename: str, content: bytes, mime_type: str) -> str:
        """Record the call and return the preconfigured file id."""
        self.uploads.append((filename, content, mime_type))
        return self._file_id


def _build_use_case(
    currencies: list[CurrencyDTO],
    db_values: dict[date, Decimal],
    file_export: _StubFileExport,
) -> ExportExchangeRatesCsv:
    """Wire an ExportExchangeRatesCsv with the given stub data."""
    market_data_repository = _StubMarketDataRepository(db_values)
    return build_exchange_rates_csv_use_case(
        currencies, market_data_repository, file_export
    )


@pytest.mark.asyncio
async def test_excludes_clp_and_omits_unresolved_dates() -> None:
    """CLP is never queried; dates with nothing to resolve from stay omitted."""
    # Window: lookback=10, forward=1 around _TODAY (2024-06-15) -> 06-05..06-16.
    # Only 06-14 has a DB value: 06-15 (today) carries it forward (within the
    # in-memory nearest-prior probe window). 06-16 is in the future, so it
    # must NOT carry anything forward -- it stays unresolved and omitted.
    # Every date before 06-14 has nothing earlier to carry forward from and
    # stays unresolved too.
    db_values = {date(2024, 6, 14): Decimal("980.50")}
    file_export = _StubFileExport()
    use_case = _build_use_case(
        [_currency("CLP"), _currency("USD")], db_values, file_export
    )

    with patch(f"{_MODULE}.datetime") as mock_dt:
        mock_dt.now.return_value.date.return_value = _TODAY
        result = await use_case.execute(lookback_days=10, forward_days=1)

    assert result.rows_written == 2
    assert result.file_id == "drive-file-id"
    assert len(file_export.uploads) == 1

    filename, content, mime_type = file_export.uploads[0]
    assert filename == "exchange-rates.csv"
    assert mime_type == "text/csv"

    rows = _read_csv_rows(content)
    assert rows[0] == ["currency_code", "rate_date", "value_clp"]
    assert rows[1:] == [
        ["USD", "2024-06-14", "980.50"],
        ["USD", "2024-06-15", "980.50"],
    ]


@pytest.mark.asyncio
async def test_future_dates_never_carry_forward_a_past_cached_value() -> None:
    """A future date is never filled from an older cached value.

    Regression test for a production bug: the in-memory nearest-prior
    lookup had no upper bound on how far it could look, so a future date
    with no exact rate silently inherited the most recent past value --
    e.g. a CSV exported today showing EUR/USD rates for next month, or a
    UF value days past SII's actual last-published date. Weekend/holiday
    gaps in the past (and today itself) legitimately carry forward; a
    date that simply hasn't happened yet must not.
    """
    # today=2024-06-15, forward=5 -> window extends to 2024-06-20, all
    # strictly in the future. The only cached value (06-15) sits well
    # within MAX_PROVIDER_LOOKBACK_DAYS of every one of those future
    # dates, so under the old bug every single one would have inherited it.
    db_values = {date(2024, 6, 15): Decimal("980.50")}
    file_export = _StubFileExport()
    use_case = _build_use_case(
        [_currency("CLP"), _currency("USD")], db_values, file_export
    )

    with patch(f"{_MODULE}.datetime") as mock_dt:
        mock_dt.now.return_value.date.return_value = _TODAY
        result = await use_case.execute(lookback_days=0, forward_days=5)

    # Only today (06-15, an exact cache hit) resolves; 06-16..06-20 do not.
    assert result.rows_written == 1
    rows = _read_csv_rows(file_export.uploads[0][1])
    assert rows[1:] == [["USD", "2024-06-15", "980.50"]]


@pytest.mark.asyncio
async def test_iterates_every_non_clp_currency() -> None:
    """Every configured non-CLP currency/index is queried across the window."""
    db_values = {
        date(2024, 6, 15): Decimal("900.00"),
    }
    file_export = _StubFileExport()
    use_case = _build_use_case(
        [_currency("CLP"), _currency("USD"), _currency("EUR"), _currency("UF")],
        db_values,
        file_export,
    )

    with patch(f"{_MODULE}.datetime") as mock_dt:
        mock_dt.now.return_value.date.return_value = _TODAY
        result = await use_case.execute(lookback_days=0, forward_days=0)

    # One resolvable date, three non-CLP currencies -> three rows.
    assert result.rows_written == 3
    rows = _read_csv_rows(file_export.uploads[0][1])
    currency_codes = {row[0] for row in rows[1:]}
    assert currency_codes == {"USD", "EUR", "UF"}


@pytest.mark.asyncio
async def test_widens_bulk_fetch_start_for_monthly_currencies() -> None:
    """UTM resolves via its 1st-of-month row even when the window starts later."""
    # _TODAY (2024-06-15) is not the 1st; UTM's only stored row is dated the 1st
    # of that month, which sits before the naive per-date query start.
    db_values = {date(2024, 6, 1): Decimal("65000.00")}
    file_export = _StubFileExport()
    use_case = _build_use_case(
        [_currency("CLP"), _currency("UTM")], db_values, file_export
    )

    with patch(f"{_MODULE}.datetime") as mock_dt:
        mock_dt.now.return_value.date.return_value = _TODAY
        result = await use_case.execute(lookback_days=0, forward_days=0)

    assert result.rows_written == 1
    rows = _read_csv_rows(file_export.uploads[0][1])
    assert rows[1] == ["UTM", "2024-06-15", "65000.00"]


@pytest.mark.asyncio
async def test_falls_back_to_slow_resolution_for_dates_outside_bulk_fetch() -> None:
    """A date the bulk fetch didn't cover still resolves via the provider chain."""
    file_export = _StubFileExport()
    reference_data_repository = _StubReferenceDataRepository(
        [_currency("CLP"), _currency("USD")]
    )
    market_data_repository = _StubMarketDataRepository({})
    get_exchange_rate_value = GetExchangeRateValue(
        market_data_repository,
        _StubFxRateProviderWithEntry("USD", _TODAY, Decimal("950.00")),
    )
    use_case = ExportExchangeRatesCsv(
        reference_data_repository,
        market_data_repository,
        get_exchange_rate_value,
        file_export,
    )

    with patch(f"{_MODULE}.datetime") as mock_dt:
        mock_dt.now.return_value.date.return_value = _TODAY
        result = await use_case.execute(lookback_days=0, forward_days=0)

    assert result.rows_written == 1
    rows = _read_csv_rows(file_export.uploads[0][1])
    assert rows[1] == ["USD", "2024-06-15", "950.00"]


@pytest.mark.asyncio
async def test_explicit_filename_overrides_default() -> None:
    """An explicit filename is forwarded to the file-export port as-is."""
    file_export = _StubFileExport()
    use_case = _build_use_case([_currency("USD")], {}, file_export)

    with patch(f"{_MODULE}.datetime") as mock_dt:
        mock_dt.now.return_value.date.return_value = _TODAY
        await use_case.execute(
            lookback_days=0, forward_days=0, filename="custom-name.csv"
        )

    assert file_export.uploads[0][0] == "custom-name.csv"


@pytest.mark.asyncio
async def test_cancellation_check_stops_before_any_work() -> None:
    """A cancellation flagged before the loop starts skips the CSV upload."""
    file_export = _StubFileExport()
    use_case = _build_use_case([_currency("CLP"), _currency("USD")], {}, file_export)

    async def _always_cancelled() -> bool:
        return True

    with patch(f"{_MODULE}.datetime") as mock_dt:
        mock_dt.now.return_value.date.return_value = _TODAY
        with pytest.raises(ExportCancelledSignal):
            await use_case.execute(
                lookback_days=0, forward_days=0, cancellation_check=_always_cancelled
            )

    assert file_export.uploads == []


@pytest.mark.asyncio
async def test_cancellation_check_stops_mid_loop_without_uploading() -> None:
    """A cancellation flagged mid-window stops before the CSV is uploaded.

    DEFAULT_FILENAME overwrites the last good export in place, so an
    upload must never happen once cancellation is observed -- otherwise a
    good file could be silently clobbered by an incomplete one.
    """
    file_export = _StubFileExport()
    use_case = _build_use_case(
        [_currency("CLP"), _currency("USD"), _currency("EUR")], {}, file_export
    )

    calls = {"count": 0}

    async def _cancel_after_one_check() -> bool:
        calls["count"] += 1
        return calls["count"] > 1

    with (
        patch(f"{_MODULE}.datetime") as mock_dt,
        patch(f"{_MODULE}.EXPORT_CANCELLATION_CHECK_INTERVAL", 1),
    ):
        mock_dt.now.return_value.date.return_value = _TODAY
        with pytest.raises(ExportCancelledSignal):
            await use_case.execute(
                lookback_days=5,
                forward_days=5,
                cancellation_check=_cancel_after_one_check,
            )

    assert file_export.uploads == []
    assert calls["count"] >= 2


@pytest.mark.asyncio
async def test_progress_report_receives_total_items_up_front() -> None:
    """progress_report is called with (0, total) before any date is resolved.

    total_items = non-CLP currencies * dates in the window, known as soon
    as the currency list and date range are resolved -- before any actual
    value-lookup work happens.
    """
    file_export = _StubFileExport()
    use_case = _build_use_case(
        [_currency("CLP"), _currency("USD"), _currency("EUR")], {}, file_export
    )
    updates: list[tuple[int, int]] = []

    async def _record_progress(processed_items: int, total_items: int) -> None:
        updates.append((processed_items, total_items))

    with patch(f"{_MODULE}.datetime") as mock_dt:
        mock_dt.now.return_value.date.return_value = _TODAY
        # lookback=4, forward=0 -> 5 dates * 2 non-CLP currencies = 10 items.
        await use_case.execute(
            lookback_days=4, forward_days=0, progress_report=_record_progress
        )

    assert updates[0] == (0, 10)


@pytest.mark.asyncio
async def test_progress_report_advances_and_reaches_full_total() -> None:
    """progress_report fires at each checkpoint and ends at (total, total)."""
    file_export = _StubFileExport()
    use_case = _build_use_case(
        [_currency("CLP"), _currency("USD"), _currency("EUR")], {}, file_export
    )
    updates: list[tuple[int, int]] = []

    async def _record_progress(processed_items: int, total_items: int) -> None:
        updates.append((processed_items, total_items))

    with (
        patch(f"{_MODULE}.datetime") as mock_dt,
        patch(f"{_MODULE}.EXPORT_CANCELLATION_CHECK_INTERVAL", 2),
    ):
        mock_dt.now.return_value.date.return_value = _TODAY
        # lookback=3, forward=0 -> 4 dates * 2 non-CLP currencies = 8 items.
        await use_case.execute(
            lookback_days=3, forward_days=0, progress_report=_record_progress
        )

    assert updates[0] == (0, 8)
    assert updates[-1] == (8, 8)
    # Strictly non-decreasing processed_items across every reported update.
    processed_sequence = [processed for processed, _ in updates]
    assert processed_sequence == sorted(processed_sequence)


@pytest.mark.asyncio
async def test_progress_report_is_optional() -> None:
    """execute() works exactly as before when progress_report is omitted."""
    file_export = _StubFileExport()
    use_case = _build_use_case([_currency("CLP"), _currency("USD")], {}, file_export)

    with patch(f"{_MODULE}.datetime") as mock_dt:
        mock_dt.now.return_value.date.return_value = _TODAY
        result = await use_case.execute(lookback_days=0, forward_days=0)

    assert result.rows_written == 0
    assert len(file_export.uploads) == 1


@pytest.mark.asyncio
async def test_session_refresh_is_called_at_each_checkpoint() -> None:
    """session_refresh fires at the same checkpoints as cancellation/progress.

    Purely a plumbing test from this use case's side -- it has no idea
    session_refresh does anything DB-related, it just calls it. The
    actual session-swapping behavior lives in ExportJobSessionSwapper
    (dependencies.py) and is covered by its own tests.
    """
    file_export = _StubFileExport()
    use_case = _build_use_case(
        [_currency("CLP"), _currency("USD"), _currency("EUR")], {}, file_export
    )
    refresh_calls = 0

    async def _session_refresh() -> None:
        nonlocal refresh_calls
        refresh_calls += 1

    with (
        patch(f"{_MODULE}.datetime") as mock_dt,
        patch(f"{_MODULE}.EXPORT_CANCELLATION_CHECK_INTERVAL", 2),
    ):
        mock_dt.now.return_value.date.return_value = _TODAY
        # lookback=3, forward=0 -> 4 dates * 2 non-CLP currencies = 8 items,
        # checkpoint every 2 -> 4 checkpoints.
        await use_case.execute(
            lookback_days=3, forward_days=0, session_refresh=_session_refresh
        )

    assert refresh_calls == 4
