"""FastAPI dependency wiring."""

import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from pathlib import Path
from typing import Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from rates.application.errors import FinancialDataDependencyConfigurationError
from rates.application.ports.export_job_repository import ExportJobRepository
from rates.application.ports.file_export_port import FileExportPort
from rates.application.ports.market_data_repository import MarketDataRepository
from rates.application.ports.reference_data_repository import (
    ReferenceDataRepository,
)
from rates.application.use_cases.export_exchange_rates_csv import (
    ExportExchangeRatesCsv,
)
from rates.application.use_cases.get_exchange_rate_value import (
    GetExchangeRateValue,
)
from rates.application.use_cases.refresh_rates import RefreshRates
from rates.application.use_cases.refresh_income_tax_brackets import (
    RefreshIncomeTaxBrackets,
)
from rates.application.use_cases.run_export_job import RunExportJob
from rates.application.use_cases.sync_recent_market_data import (
    SyncRecentMarketData,
)
from rates.config import settings
from rates.infrastructure.db.repositories.export_job_repository import (
    SqlAlchemyExportJobRepository,
)
from rates.infrastructure.db.repositories.market_data_repository import (
    SqlAlchemyMarketDataRepository,
)
from rates.infrastructure.db.repositories.reference_data_repository import (
    SqlAlchemyReferenceDataRepository,
)
from rates.infrastructure.db.session import SessionLocal
from rates.infrastructure.gdrive.drive_file_export import GoogleDriveFileExport
from rates.infrastructure.rate_providers.chained_provider import (
    ChainedEconomicIndexProvider,
    ChainedFxProvider,
)
from rates.infrastructure.rate_providers.official_providers import (
    BcchSeriesProvider,
    MindicadorRateProvider,
    SiiIncomeTaxBracketProvider,
    SiiIndicatorsProvider,
    make_fetcher,
)
from rates.shared.constants import EXPORT_SESSION_REFRESH_INTERVAL_SECONDS

_fetcher = make_fetcher(settings.http_proxy)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a database session."""
    async with SessionLocal() as session:
        yield session


def get_market_data_repository(
    session: AsyncSession = Depends(get_session),
) -> MarketDataRepository:
    """Get market data repository."""
    return SqlAlchemyMarketDataRepository(session)


def get_reference_data_repository(
    session: AsyncSession = Depends(get_session),
) -> ReferenceDataRepository:
    """Get reference data repository."""
    return SqlAlchemyReferenceDataRepository(session)


def get_fx_rate_provider() -> ChainedFxProvider:
    """Build the chained FX rate provider."""
    bcch = BcchSeriesProvider(
        user=settings.bcch_api_user,
        password=settings.bcch_api_password,
        series_codes={
            "UF": settings.bcch_series_uf,
            "USD": settings.bcch_series_usd,
            "EUR": settings.bcch_series_eur,
            "UTM": settings.bcch_series_utm,
        },
        base_url=settings.bcch_api_base_url,
        timeout_seconds=settings.rate_provider_timeout_seconds,
        fetcher=_fetcher,
    )
    return ChainedFxProvider(
        [
            bcch,
            SiiIndicatorsProvider(
                base_url=settings.sii_base_url,
                timeout_seconds=settings.rate_provider_timeout_seconds,
                fetcher=_fetcher,
            ),
            MindicadorRateProvider(
                base_url=settings.mindicador_base_url,
                timeout_seconds=settings.rate_provider_timeout_seconds,
                fetcher=_fetcher,
            ),
        ]
    )


def get_economic_index_provider() -> ChainedEconomicIndexProvider:
    """Build the chained economic-index provider."""
    return ChainedEconomicIndexProvider(
        [
            BcchSeriesProvider(
                user=settings.bcch_api_user,
                password=settings.bcch_api_password,
                series_codes={"IPC_CL": settings.bcch_series_ipc_cl},
                base_url=settings.bcch_api_base_url,
                timeout_seconds=settings.rate_provider_timeout_seconds,
                fetcher=_fetcher,
            ),
            SiiIndicatorsProvider(
                base_url=settings.sii_base_url,
                timeout_seconds=settings.rate_provider_timeout_seconds,
                fetcher=_fetcher,
            ),
        ]
    )


def get_income_tax_bracket_provider() -> SiiIncomeTaxBracketProvider:
    """Build the income tax bracket provider."""
    return SiiIncomeTaxBracketProvider(
        base_url=settings.sii_base_url,
        timeout_seconds=settings.rate_provider_timeout_seconds,
        fetcher=_fetcher,
    )


def get_exchange_rate_value_use_case(
    repository: MarketDataRepository = Depends(get_market_data_repository),
) -> GetExchangeRateValue:
    """Build the GetExchangeRateValue use case."""
    return GetExchangeRateValue(repository, get_fx_rate_provider())


def get_refresh_rates_use_case(
    repository: MarketDataRepository = Depends(get_market_data_repository),
) -> RefreshRates:
    """Build the RefreshRates use case."""
    return RefreshRates(
        repository,
        get_fx_rate_provider(),
        get_economic_index_provider(),
    )


def get_refresh_income_tax_brackets_use_case(
    repository: ReferenceDataRepository = Depends(get_reference_data_repository),
) -> RefreshIncomeTaxBrackets:
    """Build the RefreshIncomeTaxBrackets use case."""
    return RefreshIncomeTaxBrackets(repository, get_income_tax_bracket_provider())


def build_sync_use_case(session: AsyncSession) -> SyncRecentMarketData:
    """Build the SyncRecentMarketData use case directly from a session."""
    return SyncRecentMarketData(
        SqlAlchemyMarketDataRepository(session),
        get_fx_rate_provider(),
        get_economic_index_provider(),
        SqlAlchemyReferenceDataRepository(session),
        get_income_tax_bracket_provider(),
    )


def get_sync_use_case(
    session: AsyncSession = Depends(get_session),
) -> SyncRecentMarketData:
    """Build the SyncRecentMarketData use case as a FastAPI dependency."""
    return build_sync_use_case(session)


def _resolve_gdrive_oauth_token_json() -> str | None:
    """Return the OAuth token JSON content from either configured source.

    Prefers the file-path setting (local development, see
    ../../../../secrets/pf-rates/ at the repo root) when both are set;
    otherwise falls back to the raw-content setting (production, injected
    by Secret Manager).
    """
    if settings.gdrive_oauth_token_json_path:
        return Path(settings.gdrive_oauth_token_json_path).read_text()
    return settings.gdrive_oauth_token_json


def get_file_export_port() -> FileExportPort:
    """Build the Google Drive file-export adapter.

    Raises FinancialDataDependencyConfigurationError (-> HTTP 503) when the
    OAuth token or destination folder are not configured yet, instead of
    failing app startup -- the rest of the service must keep working even
    before Drive export is wired up.
    """
    oauth_token_json = _resolve_gdrive_oauth_token_json()
    if not oauth_token_json or not settings.gdrive_export_folder_id:
        raise FinancialDataDependencyConfigurationError(
            "Google Drive export is not configured: set "
            "PF_RATES_GDRIVE_OAUTH_TOKEN_JSON_PATH (local) or "
            "PF_RATES_GDRIVE_OAUTH_TOKEN_JSON (production), plus "
            "PF_RATES_GDRIVE_EXPORT_FOLDER_ID. Run scripts/gdrive_oauth_setup.py "
            "once to produce the token file."
        )
    return GoogleDriveFileExport(oauth_token_json, settings.gdrive_export_folder_id)


def get_export_job_repository(
    session: AsyncSession = Depends(get_session),
) -> ExportJobRepository:
    """Get export job repository."""
    return SqlAlchemyExportJobRepository(session)


def get_export_exchange_rates_csv_use_case(
    reference_data_repository: ReferenceDataRepository = Depends(
        get_reference_data_repository
    ),
    market_data_repository: MarketDataRepository = Depends(get_market_data_repository),
    exchange_rate_value_use_case: GetExchangeRateValue = Depends(
        get_exchange_rate_value_use_case
    ),
) -> ExportExchangeRatesCsv:
    """Build the ExportExchangeRatesCsv use case."""
    return ExportExchangeRatesCsv(
        reference_data_repository,
        market_data_repository,
        exchange_rate_value_use_case,
        get_file_export_port(),
    )


class _SessionRebindable(Protocol):
    """Structural protocol for a repository that can swap its session."""

    def rebind(self, session: AsyncSession) -> None:
        """Replace the underlying session used for future calls."""
        ...


class ExportJobSessionSwapper:
    """Own the DB session for a running export job, refreshing it periodically.

    A large export can run for many minutes. Holding one DB session open
    the whole time defeats pool_pre_ping/pool_recycle (session.py) --
    both only act when a connection is checked back into the pool, which
    never happens for a single session held continuously by one
    background task. That mismatch surfaced in production as a job
    failing partway through with a DB-side error after several minutes
    of otherwise-successful progress.

    refresh_if_due() is wired as RunExportJob's session_refresh callback,
    so it runs at the same checkpoints already used for cancellation
    polling and progress reporting -- no extra loop iterations, just one
    more cheap monotonic-clock check piggybacked on checkpoints that
    already exist. It only actually replaces the session once
    EXPORT_SESSION_REFRESH_INTERVAL_SECONDS have elapsed, closing the
    stale one and rebinding every repository that shares it to the fresh
    one in a single step, so they never disagree about which session is
    current.
    """

    def __init__(
        self, session: AsyncSession, rebindables: Sequence[_SessionRebindable]
    ) -> None:
        """Initialize the instance with the job's starting session."""
        self._session = session
        self._rebindables = rebindables
        self._last_refresh = time.monotonic()

    async def refresh_if_due(self) -> None:
        """Replace the session if the refresh interval has elapsed."""
        elapsed = time.monotonic() - self._last_refresh
        if elapsed < EXPORT_SESSION_REFRESH_INTERVAL_SECONDS:
            return
        stale_session = self._session
        self._session = SessionLocal()
        for rebindable in self._rebindables:
            rebindable.rebind(self._session)
        await stale_session.close()
        self._last_refresh = time.monotonic()

    async def close(self) -> None:
        """Close whichever session is currently active."""
        await self._session.close()


def build_run_export_job_use_case(
    session: AsyncSession,
) -> tuple[RunExportJob, ExportJobSessionSwapper]:
    """Build the RunExportJob use case directly from a session.

    Used by the background task scheduled from an async export trigger,
    which runs *after* the triggering request's own session (and its
    Depends-injected use case instances) has already been closed -- it
    needs a fresh session of its own, exactly like build_sync_use_case
    does for the same reason.

    Also returns the ExportJobSessionSwapper wrapping that session: the
    caller must call `.close()` on it once RunExportJob.execute()
    returns, since the swapper -- not this function -- owns whichever
    session ends up being the active one by the time the job finishes
    (it may have replaced the original one or more times along the way).
    """
    market_data_repository = SqlAlchemyMarketDataRepository(session)
    reference_data_repository = SqlAlchemyReferenceDataRepository(session)
    export_job_repository = SqlAlchemyExportJobRepository(session)
    swapper = ExportJobSessionSwapper(
        session,
        (market_data_repository, reference_data_repository, export_job_repository),
    )
    return (
        RunExportJob(
            export_job_repository,
            lambda: ExportExchangeRatesCsv(
                reference_data_repository,
                market_data_repository,
                GetExchangeRateValue(market_data_repository, get_fx_rate_provider()),
                get_file_export_port(),
            ),
            session_refresh=swapper.refresh_if_due,
        ),
        swapper,
    )


async def run_export_job_in_background(
    job_id: int, lookback_days: int, forward_days: int
) -> None:
    """Run a triggered export job to completion in its own DB session.

    Scheduled via FastAPI's BackgroundTasks, which only start executing
    after the HTTP response has been sent -- by then the request-scoped
    session is gone, so this opens a new one for the lifetime of the job.

    That session is not necessarily the one still open by the time the
    job finishes: ExportJobSessionSwapper may have replaced it one or
    more times along the way for a long-running export (see its
    docstring). `swapper.close()` always closes whichever one is
    currently active, so no connection is leaked either way.
    """
    session = SessionLocal()
    use_case, swapper = build_run_export_job_use_case(session)
    try:
        await use_case.execute(job_id, lookback_days, forward_days)
    finally:
        await swapper.close()


def get_export_job_background_runner() -> Callable[[int, int, int], Awaitable[None]]:
    """Return the callable that runs a triggered export job in the background.

    Exposed as a Depends() indirection (instead of the route importing and
    calling run_export_job_in_background directly) so tests can substitute
    a stub that never touches a real database session.
    """
    return run_export_job_in_background
