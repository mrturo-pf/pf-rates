"""Tests for the RunExportJob use case."""

from decimal import Decimal

import pytest

from rates.application.dto import ExportExchangeRatesResultDTO
from rates.application.use_cases.run_export_job import RunExportJob


class _StubExportJobRepository:
    """Records every state transition applied to a fake job row."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

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

    async def get(self, job_id: int) -> None:
        """Unused by RunExportJob; present only to satisfy the port shape."""
        return None


class _StubExportExchangeRatesCsv:
    """Stub CSV export use case that either succeeds or raises."""

    def __init__(
        self,
        result: ExportExchangeRatesResultDTO | None = None,
        error: Exception | None = None,
    ) -> None:
        self._result = result
        self._error = error

    async def execute(
        self, lookback_days: int, forward_days: int
    ) -> ExportExchangeRatesResultDTO:
        """Return the stub result or raise the stub error."""
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
