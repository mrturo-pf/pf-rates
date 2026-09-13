"""Use case for exporting resolved exchange-rate values to a CSV file."""

import csv
import io
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from rates.application.dto import ExportExchangeRatesResultDTO
from rates.application.errors import ExchangeRateNotFoundError
from rates.application.ports.file_export_port import FileExportPort
from rates.application.ports.reference_data_repository import (
    ReferenceDataRepository,
)
from rates.application.use_cases.get_exchange_rate_value import (
    GetExchangeRateValue,
)

_CHILE_TZ = ZoneInfo("America/Santiago")

DEFAULT_LOOKBACK_DAYS = 90
DEFAULT_FORWARD_DAYS = 30
DEFAULT_FILENAME = "exchange-rates.csv"

_CSV_HEADER = ("currency_code", "rate_date", "value_clp")
_BASE_CURRENCY_CODE = "CLP"


class ExportExchangeRatesCsv:
    """Build a CSV of resolved exchange-rate values and upload it.

    Iterates every non-CLP currency/index unit across a rolling date
    window (*lookback_days* in the past, *forward_days* in the future),
    resolving each value through `GetExchangeRateValue`'s fallback chain
    (DB hit -> provider fetch -> nearest-prior-date fallback). Dates that
    cannot be resolved at all (`ExchangeRateNotFoundError`) are simply
    omitted from the CSV -- this is expected for most future dates on true
    FX currencies (USD/EUR), which have no "tomorrow's rate" to publish.

    Exception worth knowing about: Chile has no FX market on weekends, so
    the official USD/EUR rate for the next Monday is calculated from the
    preceding Friday and published in advance, dated for that Monday. A
    CSV generated on a Friday, Saturday, or Sunday can therefore contain a
    real, correctly-dated USD/EUR value 1-2 days into the future -- that
    is not a timezone bug, just Chile's official rate-publication
    schedule working as intended (verified directly against
    mindicador.cl on 2026-09-13, a Sunday: the series already had a real
    entry for Monday 2026-09-14, with nothing for the Sat/Sun gap).

    Calls are made sequentially, not concurrently: `GetExchangeRateValue`
    is backed by a single SQLAlchemy AsyncSession, which is not safe for
    concurrent use across coroutines. Sequential calls are also naturally
    rate-limit-friendly toward the external providers this use case may
    fall back to.
    """

    def __init__(
        self,
        reference_data_repository: ReferenceDataRepository,
        get_exchange_rate_value: GetExchangeRateValue,
        file_export: FileExportPort,
    ) -> None:
        """Initialize the instance."""
        self._reference_data_repository = reference_data_repository
        self._get_exchange_rate_value = get_exchange_rate_value
        self._file_export = file_export

    async def execute(
        self,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
        forward_days: int = DEFAULT_FORWARD_DAYS,
        filename: str | None = None,
    ) -> ExportExchangeRatesResultDTO:
        """Build the CSV for the configured window and upload it.

        Returns the number of rows written and the storage identifier
        returned by the file-export port.
        """
        currency_codes = await self._list_exportable_currency_codes()
        rate_dates = self._build_date_range(lookback_days, forward_days)

        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        writer.writerow(_CSV_HEADER)
        rows_written = 0

        for currency_code in currency_codes:
            for rate_date in rate_dates:
                value = await self._resolve_value(currency_code, rate_date)
                if value is None:
                    continue
                writer.writerow((currency_code, rate_date.isoformat(), value))
                rows_written += 1

        file_id = await self._file_export.upload(
            filename=filename or self._default_filename(),
            content=buffer.getvalue().encode("utf-8"),
            mime_type="text/csv",
        )
        return ExportExchangeRatesResultDTO(rows_written=rows_written, file_id=file_id)

    async def _list_exportable_currency_codes(self) -> list[str]:
        """Return every supported currency/index code except the base currency."""
        currencies = await self._reference_data_repository.list_currencies()
        return [
            currency.code
            for currency in currencies
            if currency.code != _BASE_CURRENCY_CODE
        ]

    async def _resolve_value(self, currency_code: str, rate_date: date) -> str | None:
        """Resolve one (currency, date) pair, or None if it cannot be found."""
        try:
            value = await self._get_exchange_rate_value.execute(
                currency_code, rate_date
            )
        except ExchangeRateNotFoundError:
            return None
        return str(value)

    @staticmethod
    def _build_date_range(lookback_days: int, forward_days: int) -> list[date]:
        """Return the inclusive date list from today-lookback to today+forward."""
        today = datetime.now(tz=_CHILE_TZ).date()
        start = today - timedelta(days=lookback_days)
        span_days = lookback_days + forward_days
        return [start + timedelta(days=offset) for offset in range(span_days + 1)]

    @staticmethod
    def _default_filename() -> str:
        """Return the stable default filename, always overwritten in place.

        Deliberately NOT date-stamped: a stable name lets every run update
        the same file in place (via GoogleDriveFileExport, matching by
        name) instead of accumulating one file per run, and lets the
        export self-heal (recreate the file) if it's ever deleted by
        accident -- no dependency on a specific prior run having succeeded.
        """
        return DEFAULT_FILENAME
