"""Port definition for async export-job persistence."""

from datetime import datetime
from typing import Protocol

from rates.application.dto import ExportJobDTO
from rates.shared.constants import EXPORT_KIND_EXCHANGE_RATES


class ExportJobRepository(Protocol):
    """Persistence port for RAT_EXPORT_JOB rows.

    Backs the `POST /exchange-rates/export {"async": true}` flow, plus the
    cooperative-cancellation flow (`POST .../jobs/{id}/stop` and the bulk
    `POST .../jobs/stop`) and the `GET .../jobs` listing endpoint. State
    lives in the DB (not in-process memory) because Cloud Run can run
    multiple instances and scale to zero -- any instance must be able to
    create/update/read/cancel a job regardless of which instance handled
    the triggering request or the background execution.
    """

    async def create(
        self,
        lookback_days: int,
        forward_days: int,
        export_kind: str = EXPORT_KIND_EXCHANGE_RATES,
    ) -> int:
        """Insert a new job row in 'pending' status and return its id.

        `export_kind` records which CSV-export use case the background
        runner must build for this job (see shared.constants.EXPORT_KINDS)
        -- decided once at creation time by the triggering route, not
        re-derived later.
        """
        ...

    async def mark_running(self, job_id: int) -> None:
        """Transition the job to 'running'."""
        ...

    async def mark_succeeded(
        self, job_id: int, rows_written: int, file_id: str
    ) -> None:
        """Transition the job to 'succeeded' and record the export result."""
        ...

    async def mark_failed(self, job_id: int, error_message: str) -> None:
        """Transition the job to 'failed' and record the error message."""
        ...

    async def mark_cancelled(self, job_id: int) -> None:
        """Transition the job to 'cancelled' once execution actually stops.

        Called by RunExportJob after the export loop observes a
        cancellation request and unwinds cleanly -- never uploads a
        partial file.
        """
        ...

    async def update_progress(
        self, job_id: int, processed_items: int, total_items: int
    ) -> None:
        """Record how far a running job has gotten.

        Called periodically by the export loop itself (see
        EXPORT_CANCELLATION_CHECK_INTERVAL, whose cadence this reuses --
        no extra DB round-trips beyond what cancellation polling already
        costs), plus once up front as soon as the total is known. Does
        not change `status` -- purely additive detail for a job already
        'running'. `total_items` is passed on every call rather than set
        once separately: it never changes mid-run, so re-sending it costs
        nothing and avoids a second method for what is, from the caller's
        side, one atomic "here's my progress" update.
        """
        ...

    async def get(self, job_id: int) -> ExportJobDTO | None:
        """Return the job's current state, or None if it does not exist."""
        ...

    async def list_jobs(
        self,
        status: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ExportJobDTO]:
        """Return jobs matching the given filters, newest first.

        All filters are optional and combine with AND. `limit`/`offset`
        back simple pagination; callers are expected to clamp `limit` to
        a sane maximum (see EXPORT_JOB_LIST_MAX_LIMIT) before calling.

        Named `list_jobs`, not `list` -- a method named `list` inside this
        class body would shadow the builtin `list` for every `list[...]`
        annotation written below it in the same class (mypy: "Function ...
        is not valid as a type"), including in `list_active_ids`.
        """
        ...

    async def request_cancel(self, job_id: int) -> ExportJobDTO | None:
        """Request cancellation of a pending/running job.

        Atomically sets `cancel_requested_at` (only if not already set)
        and returns the job's resulting state. Returns None if the job
        does not exist. If the job is already in a terminal state
        (succeeded/failed/cancelled), the row is returned unchanged --
        the caller decides whether that should surface as a 409.

        Does NOT flip status to 'cancelled' itself for a 'running' job --
        that only happens once the running export loop actually observes
        the flag and stops (see mark_cancelled). A 'pending' job with no
        loop running yet to cooperate is the one exception RunExportJob
        handles by cancelling immediately at the start of execute().
        """
        ...

    async def is_cancel_requested(self, job_id: int) -> bool:
        """Cheap read-only check polled by the running export loop."""
        ...

    async def list_active_ids(self) -> list[int]:
        """Return ids of every job in 'pending' or 'running' status.

        Backs the bulk `POST /exchange-rates/export/jobs/stop` endpoint.
        """
        ...
