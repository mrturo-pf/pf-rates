"""Tests for the GoogleDriveFileExport adapter."""

from unittest.mock import Mock, patch

import pytest
from googleapiclient.errors import HttpError

from rates.application.errors import FinancialDataDependencyError
from rates.infrastructure.gdrive.drive_file_export import GoogleDriveFileExport

_MODULE = "rates.infrastructure.gdrive.drive_file_export"
_FOLDER_ID = "folder-123"


def _build_export(mock_service: Mock) -> GoogleDriveFileExport:
    """Build a GoogleDriveFileExport with ADC/build() mocked out."""
    with (
        patch(f"{_MODULE}.google_auth_default") as mock_default,
        patch(f"{_MODULE}.build", return_value=mock_service) as mock_build,
    ):
        mock_default.return_value = (Mock(), "fake-project")
        instance = GoogleDriveFileExport(_FOLDER_ID)
    mock_default.assert_called_once_with(
        scopes=["https://www.googleapis.com/auth/drive"]
    )
    mock_build.assert_called_once_with(
        "drive", "v3", credentials=mock_default.return_value[0]
    )
    return instance


def _service_with_no_existing_file(create_id: str = "new-id") -> Mock:
    """Build a mock Drive service reporting no existing file, create() stubbed."""
    mock_service = Mock()
    mock_service.files.return_value.list.return_value.execute.return_value = {
        "files": []
    }
    mock_service.files.return_value.create.return_value.execute.return_value = {
        "id": create_id
    }
    return mock_service


@pytest.mark.asyncio
async def test_upload_creates_new_file_when_none_exists() -> None:
    """No existing file with that name -> files().create() is used."""
    mock_service = _service_with_no_existing_file()
    export = _build_export(mock_service)

    file_id = await export.upload("rates.csv", b"a,b\n1,2", "text/csv")

    assert file_id == "new-id"
    create_kwargs = mock_service.files.return_value.create.call_args.kwargs
    assert create_kwargs["body"] == {"name": "rates.csv", "parents": [_FOLDER_ID]}


@pytest.mark.asyncio
async def test_upload_updates_existing_file() -> None:
    """An existing file with that name -> files().update() is used instead."""
    mock_service = Mock()
    mock_service.files.return_value.list.return_value.execute.return_value = {
        "files": [{"id": "existing-id"}]
    }
    mock_service.files.return_value.update.return_value.execute.return_value = {
        "id": "existing-id"
    }
    export = _build_export(mock_service)

    file_id = await export.upload("rates.csv", b"a,b\n1,2", "text/csv")

    assert file_id == "existing-id"
    update_kwargs = mock_service.files.return_value.update.call_args.kwargs
    assert update_kwargs["fileId"] == "existing-id"
    mock_service.files.return_value.create.assert_not_called()


@pytest.mark.asyncio
async def test_upload_wraps_http_error_as_dependency_error() -> None:
    """A Drive API failure surfaces as FinancialDataDependencyError (502)."""
    mock_service = Mock()
    mock_service.files.return_value.list.return_value.execute.return_value = {
        "files": []
    }
    mock_service.files.return_value.create.return_value.execute.side_effect = HttpError(
        Mock(status=500, reason="Internal Error"), b"boom"
    )
    export = _build_export(mock_service)

    with pytest.raises(FinancialDataDependencyError):
        await export.upload("rates.csv", b"a,b\n1,2", "text/csv")


@pytest.mark.asyncio
async def test_find_existing_file_id_escapes_single_quotes() -> None:
    """Filenames containing a single quote are escaped in the Drive query."""
    mock_service = _service_with_no_existing_file()
    export = _build_export(mock_service)

    await export.upload("o'brien.csv", b"data", "text/csv")

    list_kwargs = mock_service.files.return_value.list.call_args.kwargs
    assert "o\\'brien.csv" in list_kwargs["q"]
