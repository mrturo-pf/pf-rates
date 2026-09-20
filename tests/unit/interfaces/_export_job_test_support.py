"""Shared test doubles for the export-job routes.

`POST /exports/financial-data` and the generic `/exports/jobs/...`
status/list/stop routes share the same `ExportJobRepository`/background-
runner/`CsvExportUseCase` shapes -- centralized here instead of
copy-pasted per route test module, which is what triggered jscpd's
duplicate-code gate. (The sibling `POST /exchange-rates/export` endpoint
that originally motivated this extraction was removed once `pf-sheets`
fully migrated to the combined export; the shared fakes stayed useful on
their own merits.)
"""

from datetime import UTC, datetime as dt

from rates.application.dto import ExportExchangeRatesResultDTO, ExportJobDTO


class StubCsvExportUseCase:
    """Generic stub for any CsvExportUseCase-shaped use case.

    Shared by both export-kind route tests since
    ExportExchangeRatesCsv.execute and
    ExportCombinedFinancialDataCsv.execute have the identical
    (lookback_days, forward_days, filename) -> result contract at the
    call sites these route tests exercise.
    """

    def __init__(
        self,
        result: ExportExchangeRatesResultDTO | None = None,
        error: Exception | None = None,
    ) -> None:
        self._result = result
        self._error = error
        self.calls: list[tuple[int, int]] = []

    async def execute(
        self, lookback_days: int, forward_days: int, filename: str | None = None
    ) -> ExportExchangeRatesResultDTO:
        """Record the call, then return the stub result or raise the stub error."""
        self.calls.append((lookback_days, forward_days))
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


class StubExportJobRepository:
    """In-memory stand-in for ExportJobRepository, keyed by an incrementing id."""

    def __init__(self) -> None:
        self._next_id = 1
        self.jobs: dict[int, ExportJobDTO] = {}
        self.create_calls: list[tuple[int, int]] = []

    async def create(self, lookback_days: int, forward_days: int) -> int:
        """Insert a fake pending job and return its id."""
        self.create_calls.append((lookback_days, forward_days))
        job_id = self._next_id
        self._next_id += 1
        now = dt.now(UTC)
        self.jobs[job_id] = ExportJobDTO(
            id=job_id,
            status="pending",
            lookback_days=lookback_days,
            forward_days=forward_days,
            rows_written=None,
            file_id=None,
            error_message=None,
            cancel_requested_at=None,
            total_items=None,
            processed_items=0,
            created_at=now,
            updated_at=now,
        )
        return job_id

    async def mark_running(self, job_id: int) -> None:
        """Unused by these route tests -- the stub runner never calls it."""

    async def mark_succeeded(
        self, job_id: int, rows_written: int, file_id: str
    ) -> None:
        """Unused by these route tests -- the stub runner never calls it."""

    async def mark_failed(self, job_id: int, error_message: str) -> None:
        """Unused by these route tests -- the stub runner never calls it."""

    async def get(self, job_id: int) -> ExportJobDTO | None:
        """Return the fake job DTO, or None if it was never created."""
        return self.jobs.get(job_id)


async def noop_background_runner(
    job_id: int, lookback_days: int, forward_days: int
) -> None:
    """Stub background runner that never touches a real database session."""
