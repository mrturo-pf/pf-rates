"""Shared pure helpers and types for CSV-export use cases.

Kept dependency-free of ports/infrastructure (only the DTO and stdlib) so
`ExportExchangeRatesCsv`, `ExportCombinedFinancialDataCsv`, and
`RunExportJob` can all share the exact same date-window arithmetic,
callback types, and cancellation signal without one importing private
internals from another.
"""

from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from typing import Protocol

from rates.application.dto import ExportExchangeRatesResultDTO

CancellationCheck = Callable[[], Awaitable[bool]]
ProgressReport = Callable[[int, int], Awaitable[None]]
SessionRefresh = Callable[[], Awaitable[None]]


class ExportCancelledSignal(Exception):
    """Internal control-flow signal: an export was stopped cooperatively.

    Deliberately does not subclass FinancialDataError -- it must never be
    translated into an HTTP response. It is raised and caught entirely
    within the background-job boundary (a CSV-export use case and
    RunExportJob), never escaping to a request/response cycle. Shared by
    every CSV-export use case so RunExportJob can catch one exception
    type regardless of which kind of export raised it.
    """


def build_export_date_range(
    today: date, lookback_days: int, forward_days: int
) -> list[date]:
    """Return the inclusive date list from today-lookback to today+forward."""
    start = today - timedelta(days=lookback_days)
    span_days = lookback_days + forward_days
    return [start + timedelta(days=offset) for offset in range(span_days + 1)]


async def raise_if_cancelled(cancellation_check: CancellationCheck | None) -> None:
    """Raise ExportCancelledSignal if a cancellation has been requested.

    Shared by every CSV-export use case -- previously duplicated as an
    identical private staticmethod on each one.
    """
    if cancellation_check is not None and await cancellation_check():
        raise ExportCancelledSignal


async def report_progress(
    progress_report: ProgressReport | None,
    processed_items: int,
    total_items: int,
) -> None:
    """Invoke progress_report(processed_items, total_items) if given.

    Shared by every CSV-export use case -- previously duplicated as an
    identical private staticmethod on each one.
    """
    if progress_report is not None:
        await progress_report(processed_items, total_items)


class CsvExportUseCase(Protocol):
    """Structural type for any CSV-export use case `RunExportJob` can drive.

    Both `ExportExchangeRatesCsv` and `ExportCombinedFinancialDataCsv`
    satisfy this shape -- `RunExportJob` only needs *an* `execute()` with
    this signature, not a specific concrete class, so the exact same job
    orchestration (cancellation, progress, session refresh) drives either
    kind of export without knowing which one it got.
    """

    async def execute(
        self,
        lookback_days: int,
        forward_days: int,
        filename: str | None = None,
        cancellation_check: CancellationCheck | None = None,
        progress_report: ProgressReport | None = None,
        session_refresh: SessionRefresh | None = None,
    ) -> ExportExchangeRatesResultDTO:
        """Build the CSV for the configured window and upload it."""
        ...
