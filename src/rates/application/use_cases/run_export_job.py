"""Use case for running a triggered async CSV export job to completion."""

from collections.abc import Awaitable, Callable

from rates.application.ports.export_job_repository import ExportJobRepository
from rates.application.use_cases._export_csv_shared import (
    CsvExportUseCase,
    ExportCancelledSignal,
)
from rates.infrastructure.logging.logger import logger


class RunExportJob:
    """Execute a previously-created export job and record its outcome.

    This is the background-task boundary for the async export flow: it
    runs outside any HTTP request/response cycle (scheduled via FastAPI's
    `BackgroundTasks`), so there is no caller left to propagate an
    exception to. Catching broadly here and recording the failure on the
    job row is therefore the correct behavior, not a silent fallback --
    the alternative (letting an exception escape) would leave the job
    stuck in 'running' forever with the real error only visible in logs.

    `csv_export_factory` is a *lazy* constructor, not a ready instance:
    building the underlying use case (`ExportExchangeRatesCsv` or
    `ExportCombinedFinancialDataCsv` -- this class only depends on the
    structural `CsvExportUseCase` shape, not a specific concrete class)
    can itself raise (e.g. Google Drive not configured yet ->
    FinancialDataDependencyConfigurationError), and that failure must land
    inside the try/except below too -- otherwise a misconfigured
    dependency would leave the job stuck in 'pending' forever instead of
    recording a clear 'failed' status.

    Cooperative cancellation: before doing any work, checks whether a
    stop was already requested (covers the narrow window where a
    'pending' job is cancelled before this task ever runs). Once running,
    the cancellation flag is polled periodically inside
    `ExportExchangeRatesCsv.execute` itself -- see
    EXPORT_CANCELLATION_CHECK_INTERVAL -- and surfaces here as
    `ExportCancelledSignal`, which is treated as a normal, expected
    outcome (not a failure).

    Progress reporting: wires a `progress_report` callback into the same
    `execute()` call, persisting (processed_items, total_items) on the
    job row at the same checkpoints as cancellation polling. Purely
    additive detail on a job already 'running' -- never changes `status`,
    and a callback that itself fails would be indistinguishable from any
    other mid-run error (caught by the broad except below like everything
    else in this method).

    Session refresh: `session_refresh`, if given, is also wired through
    to `execute()` at the same checkpoints. This use case has no idea
    what it does -- the actual DB-session-swapping logic lives in
    dependencies.py, which is the only layer that owns the session's
    lifecycle. Exists because a large export can run for many minutes,
    long enough for a single held-open DB connection to go stale on a
    managed Postgres provider that recycles idle/long-lived connections
    (Neon, in production) -- without this, the job fails with a DB error
    partway through instead of completing.
    """

    def __init__(
        self,
        export_job_repository: ExportJobRepository,
        csv_export_factory: Callable[[], CsvExportUseCase],
        session_refresh: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        """Initialize the instance."""
        self._export_job_repository = export_job_repository
        self._csv_export_factory = csv_export_factory
        self._session_refresh = session_refresh

    async def execute(self, job_id: int, lookback_days: int, forward_days: int) -> None:
        """Run the export for *job_id*, updating its status as it progresses."""
        if await self._export_job_repository.is_cancel_requested(job_id):
            await self._export_job_repository.mark_cancelled(job_id)
            return

        await self._export_job_repository.mark_running(job_id)
        try:
            csv_export_use_case = self._csv_export_factory()
            job_repository = self._export_job_repository

            async def _report_progress(processed_items: int, total_items: int) -> None:
                await job_repository.update_progress(
                    job_id, processed_items, total_items
                )

            result = await csv_export_use_case.execute(
                lookback_days=lookback_days,
                forward_days=forward_days,
                cancellation_check=lambda: job_repository.is_cancel_requested(job_id),
                progress_report=_report_progress,
                session_refresh=self._session_refresh,
            )
        except ExportCancelledSignal:
            logger.info("export_job_cancelled", job_id=job_id)
            await self._export_job_repository.mark_cancelled(job_id)
            return
        except Exception as exc:  # noqa: BLE001 -- top-level background job boundary
            logger.exception("export_job_failed", job_id=job_id)
            await self._export_job_repository.mark_failed(job_id, str(exc))
            return
        await self._export_job_repository.mark_succeeded(
            job_id, result.rows_written, result.file_id
        )
