"""Use case for exporting resolved exchange-rate values to a CSV file."""

import csv
import io
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from rates.application.dto import ExportExchangeRatesResultDTO
from rates.application.errors import ExchangeRateNotFoundError
from rates.application.ports.file_export_port import FileExportPort
from rates.application.ports.market_data_repository import MarketDataRepository
from rates.application.ports.reference_data_repository import (
    ReferenceDataRepository,
)
from rates.application.use_cases.get_exchange_rate_value import (
    GetExchangeRateValue,
)
from rates.domain.normalization import normalize_exchange_rate_lookup_date
from rates.shared.constants import (
    EXPORT_CANCELLATION_CHECK_INTERVAL,
    MAX_PROVIDER_LOOKBACK_DAYS,
    MONTHLY_EXCHANGE_RATE_CODES,
)

_CHILE_TZ = ZoneInfo("America/Santiago")

DEFAULT_LOOKBACK_DAYS = 90
DEFAULT_FORWARD_DAYS = 30
DEFAULT_FILENAME = "exchange-rates.csv"

_CSV_HEADER = ("currency_code", "rate_date", "value_clp")
_BASE_CURRENCY_CODE = "CLP"

CancellationCheck = Callable[[], Awaitable[bool]]
ProgressReport = Callable[[int, int], Awaitable[None]]


class ExportCancelledSignal(Exception):
    """Internal control-flow signal: the export was stopped cooperatively.

    Deliberately does not subclass FinancialDataError -- it must never be
    translated into an HTTP response. It is raised and caught entirely
    within the background-job boundary (this use case and RunExportJob),
    never escaping to a request/response cycle.
    """


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

    Performance note: for each currency, one bulk range query fetches
    every already-stored value for the whole window up front (via
    `MarketDataRepository.list_exchange_rate_values`) instead of hitting
    the DB once per date. Weekend/holiday gaps -- the vast majority of
    dates that miss an exact match, since Chile's FX market is closed
    those days -- resolve to the nearest prior cached value entirely in
    memory (mirroring `GetExchangeRateValue`'s own nearest-prior-date
    step, just without the DB round-trip). Only dates that are still
    unresolved after that in-memory pass fall through to
    `GetExchangeRateValue`'s full DB/provider resolution chain -- expected
    to be a small remainder once `POST /sync` has warmed the window.
    Skipping this and resolving every date one at a time (exact DB match
    *and* nearest-prior DB lookup, per date) does not scale: a multi-year
    window times several currencies means tens of thousands of sequential
    round-trips, comfortably enough to blow through both Cloud Run's
    request timeout and any corporate proxy in front of it -- confirmed in
    production even after the bulk-fetch-only version of this fix.
    """

    def __init__(
        self,
        reference_data_repository: ReferenceDataRepository,
        market_data_repository: MarketDataRepository,
        get_exchange_rate_value: GetExchangeRateValue,
        file_export: FileExportPort,
    ) -> None:
        """Initialize the instance."""
        self._reference_data_repository = reference_data_repository
        self._market_data_repository = market_data_repository
        self._get_exchange_rate_value = get_exchange_rate_value
        self._file_export = file_export

    async def execute(
        self,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
        forward_days: int = DEFAULT_FORWARD_DAYS,
        filename: str | None = None,
        cancellation_check: CancellationCheck | None = None,
        progress_report: ProgressReport | None = None,
    ) -> ExportExchangeRatesResultDTO:
        """Build the CSV for the configured window and upload it.

        Returns the number of rows written and the storage identifier
        returned by the file-export port.

        If cancellation_check is given, it is polled periodically (see
        EXPORT_CANCELLATION_CHECK_INTERVAL) and raises ExportCancelledSignal
        as soon as it returns True. The CSV is never uploaded in that case
        -- DEFAULT_FILENAME is a stable name that overwrites the last good
        export in place, so uploading a partial file on cancellation would
        silently corrupt it.

        If progress_report is given, it is called with
        (processed_items, total_items) once up front -- as soon as the
        total is known, before any resolution work happens -- and again at
        the same checkpoints as cancellation_check. `total_items` is the
        number of (currency, date) pairs this run will visit, i.e.
        `len(currency_codes) * len(rate_dates)`.
        """
        currency_codes = await self._list_exportable_currency_codes()
        rate_dates = self._build_date_range(lookback_days, forward_days)
        total_items = len(currency_codes) * len(rate_dates)

        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        writer.writerow(_CSV_HEADER)
        rows_written = 0
        dates_checked = 0

        await self._report_progress(progress_report, dates_checked, total_items)

        for currency_code in currency_codes:
            await self._raise_if_cancelled(cancellation_check)
            cached_values = await self._bulk_fetch_values(
                currency_code, rate_dates[0], rate_dates[-1]
            )
            for rate_date in rate_dates:
                dates_checked += 1
                if dates_checked % EXPORT_CANCELLATION_CHECK_INTERVAL == 0:
                    await self._raise_if_cancelled(cancellation_check)
                    await self._report_progress(
                        progress_report, dates_checked, total_items
                    )
                value = self._lookup_cached_value(
                    currency_code, rate_date, cached_values
                )
                if value is None:
                    value = self._lookup_nearest_prior_cached_value(
                        currency_code, rate_date, cached_values
                    )
                if value is None:
                    value = await self._resolve_value(currency_code, rate_date)
                if value is None:
                    continue
                writer.writerow((currency_code, rate_date.isoformat(), value))
                rows_written += 1

        await self._raise_if_cancelled(cancellation_check)
        await self._report_progress(progress_report, dates_checked, total_items)
        file_id = await self._file_export.upload(
            filename=filename or self._default_filename(),
            content=buffer.getvalue().encode("utf-8"),
            mime_type="text/csv",
        )
        return ExportExchangeRatesResultDTO(rows_written=rows_written, file_id=file_id)

    @staticmethod
    async def _raise_if_cancelled(cancellation_check: CancellationCheck | None) -> None:
        """Raise ExportCancelledSignal if a cancellation has been requested."""
        if cancellation_check is not None and await cancellation_check():
            raise ExportCancelledSignal

    @staticmethod
    async def _report_progress(
        progress_report: ProgressReport | None,
        processed_items: int,
        total_items: int,
    ) -> None:
        """Invoke progress_report(processed_items, total_items) if given."""
        if progress_report is not None:
            await progress_report(processed_items, total_items)

    async def _bulk_fetch_values(
        self, currency_code: str, start: date, end: date
    ) -> dict[date, Decimal]:
        """Fetch every already-stored value for *currency_code* in one query.

        Monthly series (e.g. UTM) store one row per month, keyed by the 1st
        -- widen the query's start to that month's 1st so the whole window
        resolves from this single bulk map instead of falling through to
        the slow per-date path for every day that isn't itself the 1st.
        """
        query_start = start
        if currency_code.upper() in MONTHLY_EXCHANGE_RATE_CODES:
            query_start = date(start.year, start.month, 1)
        return await self._market_data_repository.list_exchange_rate_values(
            currency_code, query_start, end
        )

    @staticmethod
    def _lookup_cached_value(
        currency_code: str, rate_date: date, cached_values: dict[date, Decimal]
    ) -> str | None:
        """Return the bulk-fetched value for this pair, or None if not cached."""
        lookup_date = normalize_exchange_rate_lookup_date(currency_code, rate_date)
        value = cached_values.get(lookup_date)
        return str(value) if value is not None else None

    @staticmethod
    def _lookup_nearest_prior_cached_value(
        currency_code: str, rate_date: date, cached_values: dict[date, Decimal]
    ) -> str | None:
        """Probe up to MAX_PROVIDER_LOOKBACK_DAYS back within the cached map.

        Purely in-memory equivalent of `GetExchangeRateValue`'s DB-backed
        nearest-prior-date step -- resolves the common weekend/holiday gap
        without an extra round-trip per date.
        """
        lookup_date = normalize_exchange_rate_lookup_date(currency_code, rate_date)
        for days_back in range(1, MAX_PROVIDER_LOOKBACK_DAYS + 1):
            value = cached_values.get(lookup_date - timedelta(days=days_back))
            if value is not None:
                return str(value)
        return None

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
