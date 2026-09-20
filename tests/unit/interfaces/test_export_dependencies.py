"""Unit tests for Google Drive export dependency wiring."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from rates.application.errors import FinancialDataDependencyConfigurationError
from rates.application.ports.market_data_repository import MarketDataRepository
from rates.application.ports.reference_data_repository import (
    ReferenceDataRepository,
)
from rates.application.use_cases.export_combined_financial_data_csv import (
    ExportCombinedFinancialDataCsv,
)
from rates.application.use_cases.export_exchange_rates_csv import (
    ExportExchangeRatesCsv,
)
from rates.application.use_cases.get_exchange_rate_value import (
    GetExchangeRateValue,
)
from rates.interfaces.api.dependencies import (
    ExportJobSessionSwapper,
    build_run_export_job_use_case,
    get_export_combined_financial_data_csv_use_case,
    get_export_exchange_rates_csv_use_case,
    get_file_export_port,
)
from rates.shared.constants import EXPORT_KIND_COMBINED

_MODULE = "rates.interfaces.api.dependencies"


def test_get_file_export_port_raises_when_not_configured() -> None:
    """Neither JSON content, path, nor folder id set -> 503-mapped config error."""
    with patch(f"{_MODULE}.settings") as mock_settings:
        mock_settings.gdrive_oauth_token_json = None
        mock_settings.gdrive_oauth_token_json_path = None
        mock_settings.gdrive_export_folder_id = None
        with pytest.raises(FinancialDataDependencyConfigurationError):
            get_file_export_port()


def test_get_file_export_port_builds_drive_adapter_from_raw_json() -> None:
    """Raw JSON content setting (production/Secret Manager path)."""
    with (
        patch(f"{_MODULE}.settings") as mock_settings,
        patch(f"{_MODULE}.GoogleDriveFileExport") as mock_export_cls,
    ):
        mock_settings.gdrive_oauth_token_json = json.dumps({"refresh_token": "x"})
        mock_settings.gdrive_oauth_token_json_path = None
        mock_settings.gdrive_export_folder_id = "folder-1"
        mock_export_cls.return_value = Mock()

        result = get_file_export_port()

        mock_export_cls.assert_called_once_with(
            mock_settings.gdrive_oauth_token_json, "folder-1"
        )
        assert result is mock_export_cls.return_value


def test_get_file_export_port_builds_drive_adapter_from_file_path(
    tmp_path: Path,
) -> None:
    """File-path setting (local development) is read and its content used."""
    token_file = tmp_path / "gdrive-oauth-token.json"
    token_file.write_text(json.dumps({"refresh_token": "x"}))

    with (
        patch(f"{_MODULE}.settings") as mock_settings,
        patch(f"{_MODULE}.GoogleDriveFileExport") as mock_export_cls,
    ):
        mock_settings.gdrive_oauth_token_json = None
        mock_settings.gdrive_oauth_token_json_path = str(token_file)
        mock_settings.gdrive_export_folder_id = "folder-1"
        mock_export_cls.return_value = Mock()

        result = get_file_export_port()

        mock_export_cls.assert_called_once_with(token_file.read_text(), "folder-1")
        assert result is mock_export_cls.return_value


def test_get_export_exchange_rates_csv_use_case_wires_dependencies() -> None:
    """The FastAPI dependency builds a fully wired ExportExchangeRatesCsv."""
    reference_data_repository = Mock(spec=ReferenceDataRepository)
    market_data_repository = Mock(spec=MarketDataRepository)
    exchange_rate_value_use_case = Mock(spec=GetExchangeRateValue)

    with patch(f"{_MODULE}.get_file_export_port") as mock_get_port:
        mock_get_port.return_value = Mock()
        use_case = get_export_exchange_rates_csv_use_case(
            reference_data_repository,
            market_data_repository,
            exchange_rate_value_use_case,
        )

    assert isinstance(use_case, ExportExchangeRatesCsv)


def test_get_export_combined_financial_data_csv_use_case_wires_dependencies() -> None:
    """The FastAPI dependency builds a fully wired ExportCombinedFinancialDataCsv.

    Composes an already-built ExportExchangeRatesCsv rather than deriving
    its own reference-data/get-exchange-rate-value dependencies -- see
    the docstring on the real function for why.
    """
    market_data_repository = Mock(spec=MarketDataRepository)
    exchange_rates_csv = Mock(spec=ExportExchangeRatesCsv)

    with patch(f"{_MODULE}.get_file_export_port") as mock_get_port:
        mock_get_port.return_value = Mock()
        use_case = get_export_combined_financial_data_csv_use_case(
            market_data_repository, exchange_rates_csv
        )

    assert isinstance(use_case, ExportCombinedFinancialDataCsv)


def test_build_run_export_job_use_case_combined_kind_wires_combined_use_case() -> None:
    """export_kind=combined makes the lazy factory build the combined use case.

    The factory is lazy precisely so this branch (see
    build_run_export_job_use_case's docstring) only runs when the
    background job actually executes -- exercised here directly since
    RunExportJob.execute() is the only other caller, and it's already
    covered end to end by the async-export integration tests.
    """

    class _FakeSession:
        pass

    with (
        patch(f"{_MODULE}.get_fx_rate_provider") as mock_get_fx_provider,
        patch(f"{_MODULE}.get_file_export_port") as mock_get_port,
    ):
        mock_get_fx_provider.return_value = Mock()
        mock_get_port.return_value = Mock()
        run_export_job, _swapper = build_run_export_job_use_case(
            _FakeSession(),  # type: ignore[arg-type]
            export_kind=EXPORT_KIND_COMBINED,
        )
        use_case = run_export_job._csv_export_factory()

    assert isinstance(use_case, ExportCombinedFinancialDataCsv)


def _fake_session(name: str) -> Mock:
    """Build a Mock standing in for an AsyncSession, with an async close()."""
    session = Mock(name=name)
    session.close = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_session_swapper_does_not_refresh_before_interval_elapses() -> None:
    """No session replacement (and no rebind calls) before the interval elapses."""
    original_session = _fake_session("original")
    rebindable = Mock()

    with patch(f"{_MODULE}.time") as mock_time:
        mock_time.monotonic.side_effect = [0.0, 1.0]  # constructor, then check
        swapper = ExportJobSessionSwapper(original_session, [rebindable])
        await swapper.refresh_if_due()

    rebindable.rebind.assert_not_called()
    original_session.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_session_swapper_refreshes_and_rebinds_after_interval_elapses() -> None:
    """Past the interval: closes the stale session and rebinds every repository."""
    original_session = _fake_session("original")
    fresh_session = _fake_session("fresh")
    first_rebindable = Mock()
    second_rebindable = Mock()

    with (
        patch(f"{_MODULE}.time") as mock_time,
        patch(f"{_MODULE}.SessionLocal", return_value=fresh_session),
    ):
        mock_time.monotonic.side_effect = [0.0, 999.0, 999.0]
        swapper = ExportJobSessionSwapper(
            original_session, [first_rebindable, second_rebindable]
        )
        await swapper.refresh_if_due()

    first_rebindable.rebind.assert_called_once_with(fresh_session)
    second_rebindable.rebind.assert_called_once_with(fresh_session)
    original_session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_session_swapper_close_closes_whichever_session_is_current() -> None:
    """close() closes the currently-active session, even after a refresh."""
    original_session = _fake_session("original")
    fresh_session = _fake_session("fresh")

    with (
        patch(f"{_MODULE}.time") as mock_time,
        patch(f"{_MODULE}.SessionLocal", return_value=fresh_session),
    ):
        mock_time.monotonic.side_effect = [0.0, 999.0, 999.0]
        swapper = ExportJobSessionSwapper(original_session, [])
        await swapper.refresh_if_due()
        await swapper.close()

    fresh_session.close.assert_awaited_once()
    original_session.close.assert_awaited_once()
