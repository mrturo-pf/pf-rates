"""Tests for the ExportExchangeRatesCsv use case."""

import csv
import io
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from rates.application.dto import (
    CurrencyDTO,
    RefreshRatesCommandDTO,
    RefreshRatesResultDTO,
)
from rates.application.use_cases.export_exchange_rates_csv import (
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
    get_exchange_rate_value = GetExchangeRateValue(
        _StubMarketDataRepository(db_values), _StubFxRateProvider()
    )
    return ExportExchangeRatesCsv(
        reference_data_repository, get_exchange_rate_value, file_export
    )


@pytest.mark.asyncio
async def test_excludes_clp_and_omits_unresolved_dates() -> None:
    """CLP is never queried; only resolvable (currency, date) pairs become rows."""
    # Window: lookback=2, forward=1 around _TODAY -> 06-13, 06-14, 06-15, 06-16.
    # Only 06-14 has a DB value; the rest miss every resolution step.
    db_values = {date(2024, 6, 14): Decimal("980.50")}
    file_export = _StubFileExport()
    use_case = _build_use_case(
        [_currency("CLP"), _currency("USD")], db_values, file_export
    )

    with patch(f"{_MODULE}.datetime") as mock_dt:
        mock_dt.now.return_value.date.return_value = _TODAY
        result = await use_case.execute(lookback_days=2, forward_days=1)

    assert result.rows_written == 1
    assert result.file_id == "drive-file-id"
    assert len(file_export.uploads) == 1

    filename, content, mime_type = file_export.uploads[0]
    assert filename == "exchange-rates.csv"
    assert mime_type == "text/csv"

    rows = _read_csv_rows(content)
    assert rows[0] == ["currency_code", "rate_date", "value_clp"]
    assert rows[1:] == [["USD", "2024-06-14", "980.50"]]


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
