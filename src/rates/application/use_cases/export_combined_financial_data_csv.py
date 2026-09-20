"""Use case for exporting a combined CSV of exchange rates + economic indices."""

import csv
import io
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from rates.application.dto import ExportExchangeRatesResultDTO
from rates.application.ports.file_export_port import FileExportPort
from rates.application.ports.market_data_repository import MarketDataRepository
from rates.application.use_cases._export_csv_shared import (
    CancellationCheck,
    ProgressReport,
    SessionRefresh,
    build_export_date_range,
    raise_if_cancelled,
    report_progress,
)
from rates.application.use_cases.export_exchange_rates_csv import (
    ExportExchangeRatesCsv,
)
from rates.shared.constants import (
    EXPORT_CANCELLATION_CHECK_INTERVAL,
    MONTHLY_ECONOMIC_INDEX_CODES,
)

_CHILE_TZ = ZoneInfo("America/Santiago")

DEFAULT_LOOKBACK_DAYS = 90
DEFAULT_FORWARD_DAYS = 30
DEFAULT_FILENAME = "financial-data.csv"

_CSV_HEADER = ("series_type", "code", "period_date", "value")
SERIES_TYPE_EXCHANGE_RATE = "EXCHANGE_RATE"
SERIES_TYPE_ECONOMIC_INDEX = "ECONOMIC_INDEX"


class ExportCombinedFinancialDataCsv:
    """Build a combined CSV of exchange-rate + economic-index values and upload it.

    Produces one CSV with a uniform row shape
    (`series_type,code,period_date,value`) covering both RAT_EXCH_RATE
    (`series_type=EXCHANGE_RATE`) and RAT_ECON_INDEX
    (`series_type=ECONOMIC_INDEX`) data, across the same rolling date
    window (*lookback_days* in the past, *forward_days* in the future)
    for both series types.

    Exchange-rate rows reuse `ExportExchangeRatesCsv`'s exact resolution
    chain verbatim (`bulk_fetch_currency_values` + `resolve_value_for_date`)
    -- see that class's docstring for the fallback chain and the
    production bug it fixed ("never invent a value for a date that
    hasn't happened yet"). This use case does not re-implement any of
    that logic, and does not add a resolution path of its own for
    exchange rates.

    Economic-index rows (e.g. IPC_CL) are expanded the same way
    `ExportExchangeRatesCsv` already expands UTM: RAT_ECON_INDEX is a
    monthly series exactly like UTM is within RAT_EXCH_RATE. For every
    calendar day in the window, the day's (year, month) is looked up in a
    map built from a single bulk `list_economic_indices(code)` call per
    code, and that month's value is repeated for every day in the window
    that falls in that month. There is no provider fallback for economic
    indices (matches `GET /economic-indices/value` today, which doesn't
    have one either); a month with nothing stored simply has its days
    omitted -- the same "omit what can't be resolved" behavior exchange
    rates already use, not an error.
    """

    def __init__(
        self,
        market_data_repository: MarketDataRepository,
        exchange_rates_csv: ExportExchangeRatesCsv,
        file_export: FileExportPort,
    ) -> None:
        """Initialize the instance."""
        self._market_data_repository = market_data_repository
        self._exchange_rates_csv = exchange_rates_csv
        self._file_export = file_export

    # jscpd:ignore-start -- this signature is mandated verbatim by the
    # shared CsvExportUseCase Protocol in _export_csv_shared.py, which
    # RunExportJob depends on structurally. Every implementation (this
    # one and ExportExchangeRatesCsv) must repeat it exactly to satisfy
    # the Protocol -- there is no way to factor out a method signature
    # itself in Python without runtime code-generation, which would cost
    # far more in readability/type-safety than the duplication it removes.
    async def execute(
        self,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
        forward_days: int = DEFAULT_FORWARD_DAYS,
        filename: str | None = None,
        cancellation_check: CancellationCheck | None = None,
        progress_report: ProgressReport | None = None,
        session_refresh: SessionRefresh | None = None,
    ) -> ExportExchangeRatesResultDTO:
        """Build the combined CSV for the configured window and upload it.

        Same cancellation/progress/session-refresh contract as
        `ExportExchangeRatesCsv.execute` -- see its docstring for the
        exact semantics of each callback. `total_items` here counts both
        series types: `(len(currency_codes) + len(economic_index_codes))
        * len(rate_dates)`.
        """
        currency_codes = await self._exchange_rates_csv.list_exportable_currency_codes()
        economic_index_codes = list(MONTHLY_ECONOMIC_INDEX_CODES)
        today = datetime.now(tz=_CHILE_TZ).date()
        rate_dates = build_export_date_range(today, lookback_days, forward_days)
        total_items = (len(currency_codes) + len(economic_index_codes)) * len(
            rate_dates
        )

        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        writer.writerow(_CSV_HEADER)
        rows_written = 0
        items_checked = 0

        await report_progress(progress_report, items_checked, total_items)

        for currency_code in currency_codes:
            await raise_if_cancelled(cancellation_check)
            cached_values = await self._exchange_rates_csv.bulk_fetch_currency_values(
                currency_code, rate_dates[0], rate_dates[-1]
            )
            for rate_date in rate_dates:
                items_checked = await self._checkpoint(
                    items_checked,
                    total_items,
                    cancellation_check,
                    progress_report,
                    session_refresh,
                )
                value = await self._exchange_rates_csv.resolve_value_for_date(
                    currency_code, rate_date, cached_values, today
                )
                if value is None:
                    continue
                writer.writerow(
                    (
                        SERIES_TYPE_EXCHANGE_RATE,
                        currency_code,
                        rate_date.isoformat(),
                        value,
                    )
                )
                rows_written += 1

        for index_code in economic_index_codes:
            await raise_if_cancelled(cancellation_check)
            monthly_values = await self._bulk_fetch_economic_index_values(index_code)
            for rate_date in rate_dates:
                items_checked = await self._checkpoint(
                    items_checked,
                    total_items,
                    cancellation_check,
                    progress_report,
                    session_refresh,
                )
                index_value = monthly_values.get((rate_date.year, rate_date.month))
                if index_value is None:
                    continue
                writer.writerow(
                    (
                        SERIES_TYPE_ECONOMIC_INDEX,
                        index_code,
                        rate_date.isoformat(),
                        str(index_value),
                    )
                )
                rows_written += 1

        await raise_if_cancelled(cancellation_check)
        await report_progress(progress_report, items_checked, total_items)
        file_id = await self._file_export.upload(
            filename=filename or DEFAULT_FILENAME,
            content=buffer.getvalue().encode("utf-8"),
            mime_type="text/csv",
        )
        return ExportExchangeRatesResultDTO(rows_written=rows_written, file_id=file_id)

    # jscpd:ignore-end

    async def _checkpoint(
        self,
        items_checked: int,
        total_items: int,
        cancellation_check: CancellationCheck | None,
        progress_report: ProgressReport | None,
        session_refresh: SessionRefresh | None,
    ) -> int:
        """Advance the item counter, polling cancellation/progress/refresh."""
        items_checked += 1
        if items_checked % EXPORT_CANCELLATION_CHECK_INTERVAL == 0:
            await raise_if_cancelled(cancellation_check)
            await report_progress(progress_report, items_checked, total_items)
            if session_refresh is not None:
                await session_refresh()
        return items_checked

    async def _bulk_fetch_economic_index_values(
        self, code: str
    ) -> dict[tuple[int, int], Decimal]:
        """Fetch every stored value for *code* in one query, keyed by (year, month).

        Mirrors `ExportExchangeRatesCsv.bulk_fetch_currency_values`'s
        one-query-per-series philosophy: RAT_ECON_INDEX is small (one row
        per code per month, going back at most a few decades), so a
        single unfiltered-by-date `list_economic_indices(code)` call is
        simpler than computing a (year, month) range to filter by first.
        """
        entries = await self._market_data_repository.list_economic_indices(code)
        return {
            (entry.period_year, entry.period_month): entry.index_value
            for entry in entries
        }
