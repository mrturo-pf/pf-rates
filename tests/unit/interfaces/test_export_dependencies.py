"""Unit tests for Google Drive export dependency wiring."""

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from rates.application.errors import FinancialDataDependencyConfigurationError
from rates.application.ports.reference_data_repository import (
    ReferenceDataRepository,
)
from rates.application.use_cases.export_exchange_rates_csv import (
    ExportExchangeRatesCsv,
)
from rates.application.use_cases.get_exchange_rate_value import (
    GetExchangeRateValue,
)
from rates.interfaces.api.dependencies import (
    get_export_exchange_rates_csv_use_case,
    get_file_export_port,
)

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
    exchange_rate_value_use_case = Mock(spec=GetExchangeRateValue)

    with patch(f"{_MODULE}.get_file_export_port") as mock_get_port:
        mock_get_port.return_value = Mock()
        use_case = get_export_exchange_rates_csv_use_case(
            reference_data_repository, exchange_rate_value_use_case
        )

    assert isinstance(use_case, ExportExchangeRatesCsv)
