"""Tests for the ExportExchangeRatesCsv use case."""

import csv
import io
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from rates.application.dto import (
    CurrencyDTO,
    ExchangeRateWriteDTO,
    RefreshRatesCommandDTO,
    RefreshRatesResultDTO,
)
from rates.application.use_cases.export_exchange_rates_csv import (
    ExportCancelledSignal,
    ExportExchangeRatesCsv,
)
from rates.application.use_cases.get_exchange_rate_value import (
    GetExchangeRateValue,
)

_MODULE = "rates.application.use_cases.export_exchange_rates_csv"

# Fixed "today" the module's datetime.now() is patched to return, so the
# resulting date window is fully deterministic.
_TODAY = date(2024, 6, 15)


def _currency(code: str) -> CurrencyDTO:
    """Build a minimal CurrencyDTO for the given code."""
    return CurrencyDTO(code=code, name=code, is_fiat=True, unit_kind="currency")


class _StubReferenceDataRepository:
    """Minimal ReferenceDataRepository test double."""

    def __init__(self, currencies: list[CurrencyDTO]) -> None:
        self._currencies = currencies

    async def list_currencies(self) -> list[CurrencyDTO]:
        """Return the preconfigured currency list."""
        return self._currencies


class _StubMarketDataRepository:
    """Minimal MarketDataRepository test double, DB-value-only."""

    def __init__(self, db_values: dict[date, Decimal]) -> None:
        self._db_values = db_values

    async def get_exchange_rate_value(
        self, currency_code: str, rate_date: date
    ) -> Decimal | None:
        """Return a preconfigured DB value, ignoring currency_code."""
        return self._db_values.get(rate_date)

    async def get_latest_exchange_rate_value_before(
        self, code: str, before: date, on_or_after: date | None = None
    ) -> Decimal | None:
        """Return None -- fallback is out of scope for these tests."""
        return None

    async def list_exchange_rate_values(
        self, code: str, start: date, end: date
    ) -> dict[date, Decimal]:
        """Return the preconfigured DB values that fall within [start, end]."""
        return {
            rate_date: value
            for rate_date, value in self._db_values.items()
            if start <= rate_date <= end
        }

    async def refresh_rates(
        self, command: RefreshRatesCommandDTO
    ) -> RefreshRatesResultDTO:
        """Record nothing; never expected to be called in these tests."""
        return RefreshRatesResultDTO(
            upserted_exchange_rates=len(command.exchange_rates),
            upserted_economic_indices=0,
        )


class _StubFxRateProvider:
    """FxRateProvider test double that never has data."""

    async def fetch_rate_entry(self, currency_code: str, on: date) -> None:
        """Return None unconditionally."""
        return None


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


def _read_csv_rows(content: bytes) -> list[list[str]]:
    """Parse uploaded CSV bytes into a list of rows (including the header)."""
    text = content.decode("utf-8")
    return list(csv.reader(io.StringIO(text)))


def _build_use_case(
    currencies: list[CurrencyDTO],
    db_values: dict[date, Decimal],
    file_export: _StubFileExport,
) -> ExportExchangeRatesCsv:
    """Wire an ExportExchangeRatesCsv with the given stub data."""
    reference_data_repository = _StubReferenceDataRepository(currencies)
    market_data_repository = _StubMarketDataRepository(db_values)
    get_exchange_rate_value = GetExchangeRateValue(
        market_data_repository, _StubFxRateProvider()
    )
    return ExportExchangeRatesCsv(
        reference_data_repository,
        market_data_repository,
        get_exchange_rate_value,
        file_export,
    )


@pytest.mark.asyncio
async def test_excludes_clp_and_omits_unresolved_dates() -> None:
    """CLP is never queried; dates with nothing to resolve from stay omitted."""
    # Window: lookback=10, forward=1 around _TODAY (2024-06-15) -> 06-05..06-16.
    # Only 06-14 has a DB value: 06-15/06-16 carry it forward (within the
    # in-memory nearest-prior probe window), while every date before 06-14
    # has nothing earlier to carry forward from and stays unresolved.
    db_values = {date(2024, 6, 14): Decimal("980.50")}
    file_export = _StubFileExport()
    use_case = _build_use_case(
        [_currency("CLP"), _currency("USD")], db_values, file_export
    )

    with patch(f"{_MODULE}.datetime") as mock_dt:
        mock_dt.now.return_value.date.return_value = _TODAY
        result = await use_case.execute(lookback_days=10, forward_days=1)

    assert result.rows_written == 3
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
        ["USD", "2024-06-16", "980.50"],
    ]


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
