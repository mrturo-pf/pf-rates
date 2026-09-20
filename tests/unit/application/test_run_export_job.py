"""Tests for the RunExportJob use case."""

from decimal import Decimal

import pytest

from rates.application.dto import ExportExchangeRatesResultDTO
from rates.application.use_cases._export_csv_shared import ExportCancelledSignal
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

    async def update_progress(
        self, job_id: int, processed_items: int, total_items: int
    ) -> None:
        """Record a progress update."""
        self.calls.append(("update_progress", (job_id, processed_items, total_items)))

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
        progress_updates: list[tuple[int, int]] | None = None,
        session_refresh_calls: int = 0,
    ) -> None:
        self._result = result
        self._error = error
        self._cancel = cancel
        self._progress_updates = progress_updates or []
        self._session_refresh_calls = session_refresh_calls

    async def execute(
        self,
        lookback_days: int,
        forward_days: int,
        cancellation_check: object = None,
        progress_report: object = None,
        session_refresh: object = None,
    ) -> ExportExchangeRatesResultDTO:
        """Return the stub result, raise the stub error, or signal cancellation.

        Replays any preconfigured progress_updates through progress_report,
        mirroring how the real use case calls it mid-execution -- lets
        RunExportJob tests verify the callback is correctly wired through
        to the repository without re-testing ExportExchangeRatesCsv itself.
        Same idea for session_refresh_calls/session_refresh.
        """
        if progress_report is not None:
            for processed_items, total_items in self._progress_updates:
                await progress_report(processed_items, total_items)
        if session_refresh is not None:
            for _ in range(self._session_refresh_calls):
                await session_refresh()
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


@pytest.mark.asyncio
async def test_run_export_job_forwards_progress_updates_to_repository() -> None:
    """Every progress_report(...) call from the export loop reaches the repo.

    RunExportJob's callback must inject job_id -- the use case underneath
    only knows (processed_items, total_items), not which job it's running.
    """
    repository = _StubExportJobRepository()
    csv_export = _StubExportExchangeRatesCsv(
        result=ExportExchangeRatesResultDTO(rows_written=10, file_id="drive-p"),
        progress_updates=[(0, 40), (20, 40), (40, 40)],
    )
    use_case = RunExportJob(repository, lambda: csv_export)

    await use_case.execute(job_id=7, lookback_days=10, forward_days=0)

    assert repository.calls == [
        ("mark_running", (7,)),
        ("update_progress", (7, 0, 40)),
        ("update_progress", (7, 20, 40)),
        ("update_progress", (7, 40, 40)),
        ("mark_succeeded", (7, 10, "drive-p")),
    ]


@pytest.mark.asyncio
async def test_run_export_job_forwards_session_refresh_to_execute() -> None:
    """The constructor's session_refresh callback reaches execute() unchanged.

    RunExportJob has no idea what session_refresh does -- it is an opaque
    maintenance hook owned entirely by dependencies.py
    (ExportJobSessionSwapper). This only verifies the plumbing: the exact
    same callable passed to __init__ is the one execute() ends up calling.
    """
    repository = _StubExportJobRepository()
    refresh_calls = 0

    async def _session_refresh() -> None:
        nonlocal refresh_calls
        refresh_calls += 1

    csv_export = _StubExportExchangeRatesCsv(
        result=ExportExchangeRatesResultDTO(rows_written=1, file_id="drive-r"),
        session_refresh_calls=3,
    )
    use_case = RunExportJob(
        repository, lambda: csv_export, session_refresh=_session_refresh
    )

    await use_case.execute(job_id=8, lookback_days=1, forward_days=0)

    assert refresh_calls == 3
