"""FastAPI dependency wiring."""

from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from rates.application.errors import FinancialDataDependencyConfigurationError
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
from rates.application.use_cases.sync_recent_market_data import (
    SyncRecentMarketData,
)
from rates.config import settings
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


def get_export_exchange_rates_csv_use_case(
    reference_data_repository: ReferenceDataRepository = Depends(
        get_reference_data_repository
    ),
    exchange_rate_value_use_case: GetExchangeRateValue = Depends(
        get_exchange_rate_value_use_case
    ),
) -> ExportExchangeRatesCsv:
    """Build the ExportExchangeRatesCsv use case."""
    return ExportExchangeRatesCsv(
        reference_data_repository,
        exchange_rate_value_use_case,
        get_file_export_port(),
    )
