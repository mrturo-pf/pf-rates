"""Tests for the RunExportJob use case."""

from decimal import Decimal

import pytest

from rates.application.dto import ExportExchangeRatesResultDTO
from rates.application.use_cases.export_exchange_rates_csv import (
    ExportCancelledSignal,
)
from rates.application.use_cases.run_export_job import RunExportJob


class _StubExportJobRepository:
    """Records every state transition applied to a fake job row."""

    def __init__(self, cancel_requested_from_start: bool = False) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self._cancel_requested = cancel_requested_from_start

    async def mark_running(self, job_id: int) -> None:
        """Record the transition to 'running'."""
        self.calls.append(("mark_running", (job_id,)))

    async def mark_succeeded(
        self, job_id: int, rows_written: int, file_id: str
    ) -> None:
        """Record the transition to 'succeeded'."""
        self.calls.append(("mark_succeeded", (job_id, rows_written, file_id)))

    async def mark_failed(self, job_id: int, error_message: str) -> None:
        """Record the transition to 'failed'."""
        self.calls.append(("mark_failed", (job_id, error_message)))

    async def mark_cancelled(self, job_id: int) -> None:
        """Record the transition to 'cancelled'."""
        self.calls.append(("mark_cancelled", (job_id,)))

    async def is_cancel_requested(self, job_id: int) -> bool:
        """Return the preconfigured cancellation flag."""
        return self._cancel_requested

    async def get(self, job_id: int) -> None:
        """Unused by RunExportJob; present only to satisfy the port shape."""
        return None


class _StubExportExchangeRatesCsv:
    """Stub CSV export use case that either succeeds, raises, or cancels."""

    def __init__(
        self,
        result: ExportExchangeRatesResultDTO | None = None,
        error: Exception | None = None,
        cancel: bool = False,
    ) -> None:
        self._result = result
        self._error = error
        self._cancel = cancel

    async def execute(
        self,
        lookback_days: int,
        forward_days: int,
        cancellation_check: object = None,
    ) -> ExportExchangeRatesResultDTO:
        """Return the stub result, raise the stub error, or signal cancellation."""
        if self._cancel:
            raise ExportCancelledSignal
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


@pytest.mark.asyncio
async def test_run_export_job_marks_running_then_succeeded() -> None:
    """A successful export transitions pending -> running -> succeeded."""
    repository = _StubExportJobRepository()
    csv_export = _StubExportExchangeRatesCsv(
        result=ExportExchangeRatesResultDTO(rows_written=123, file_id="drive-abc")
    )
    use_case = RunExportJob(repository, lambda: csv_export)

    await use_case.execute(job_id=1, lookback_days=90, forward_days=30)

    assert repository.calls == [
        ("mark_running", (1,)),
        ("mark_succeeded", (1, 123, "drive-abc")),
    ]


@pytest.mark.asyncio
async def test_run_export_job_marks_failed_when_execute_raises() -> None:
    """An error during execute() transitions running -> failed, never raises."""
    repository = _StubExportJobRepository()
    csv_export = _StubExportExchangeRatesCsv(error=ValueError("boom"))
    use_case = RunExportJob(repository, lambda: csv_export)

    await use_case.execute(job_id=2, lookback_days=90, forward_days=30)

    assert repository.calls == [
        ("mark_running", (2,)),
        ("mark_failed", (2, "boom")),
    ]


@pytest.mark.asyncio
async def test_run_export_job_marks_failed_when_factory_raises() -> None:
    """A factory that raises during construction still records a failure.

    Covers the case where building ExportExchangeRatesCsv itself fails
    (e.g. Google Drive not configured) -- the lazy factory ensures this
    still lands inside the try/except instead of leaving the job stuck
    in 'running' forever.
    """
    repository = _StubExportJobRepository()

    def _failing_factory() -> _StubExportExchangeRatesCsv:
        raise RuntimeError("Google Drive export is not configured")

    use_case = RunExportJob(repository, _failing_factory)

    await use_case.execute(job_id=3, lookback_days=90, forward_days=30)

    assert repository.calls == [
        ("mark_running", (3,)),
        ("mark_failed", (3, "Google Drive export is not configured")),
    ]


@pytest.mark.asyncio
async def test_run_export_job_result_carries_decimal_safe_types() -> None:
    """rows_written/file_id pass through untouched (no float coercion)."""
    repository = _StubExportJobRepository()
    csv_export = _StubExportExchangeRatesCsv(
        result=ExportExchangeRatesResultDTO(rows_written=0, file_id="drive-empty")
    )
    use_case = RunExportJob(repository, lambda: csv_export)

    await use_case.execute(job_id=4, lookback_days=1, forward_days=0)

    _, (job_id, rows_written, file_id) = repository.calls[-1]
    assert job_id == 4
    assert rows_written == 0
    assert file_id == "drive-empty"
    assert not isinstance(rows_written, Decimal)


@pytest.mark.asyncio
async def test_run_export_job_skips_to_cancelled_when_flagged_upfront() -> None:
    """A cancellation requested before the task ever ran skips execution entirely.

    Covers the narrow window where a 'pending' job is stopped before its
    BackgroundTask starts -- there is no running loop yet to cooperate, so
    RunExportJob checks the flag itself before doing any work.
    """
    repository = _StubExportJobRepository(cancel_requested_from_start=True)
    csv_export = _StubExportExchangeRatesCsv(
        result=ExportExchangeRatesResultDTO(rows_written=999, file_id="never-used")
    )
    use_case = RunExportJob(repository, lambda: csv_export)

    await use_case.execute(job_id=5, lookback_days=90, forward_days=30)

    # mark_running is never called -- the job goes straight to cancelled.
    assert repository.calls == [("mark_cancelled", (5,))]


@pytest.mark.asyncio
async def test_run_export_job_marks_cancelled_when_signal_raised_mid_run() -> None:
    """ExportCancelledSignal raised mid-execution transitions to 'cancelled'.

    Treated as a normal, expected outcome -- not routed through
    mark_failed the way a real error would be.
    """
    repository = _StubExportJobRepository()
    csv_export = _StubExportExchangeRatesCsv(cancel=True)
    use_case = RunExportJob(repository, lambda: csv_export)

    await use_case.execute(job_id=6, lookback_days=90, forward_days=30)

    assert repository.calls == [
        ("mark_running", (6,)),
        ("mark_cancelled", (6,)),
    ]
