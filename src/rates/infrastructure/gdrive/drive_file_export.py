"""Google Drive adapter for the FileExportPort.

Authenticates as the Drive account's actual human owner via OAuth (not a
service account) using a long-lived refresh token obtained once through
`scripts/gdrive_oauth_setup.py` -- see
`docs/google-drive-credentials-setup.md` for the full one-time setup.

This deliberately does NOT use a service account: Google service accounts
have no storage quota of their own in a personal (non-Workspace) Drive, so
they cannot create files, only update pre-existing ones. Authenticating as
the real account owner uses that account's own quota, so this adapter can
freely create the destination file on first run and self-heal if someone
deletes it later -- no manual "seed file" step required.

The `googleapiclient`/`google-auth` libraries are synchronous; every call
is wrapped in `asyncio.to_thread` to avoid blocking the event loop, matching
the pattern already used for the HTTP-based rate providers.
"""

from __future__ import annotations

import asyncio
import io
import json

import structlog
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

from rates.application.errors import FinancialDataDependencyError

# Full Drive access, not the narrower "drive.file" scope: this adapter must
# be able to find a pre-existing file across the whole configured folder
# (in case it was created by hand or by a prior, differently-scoped run),
# not just files this exact OAuth client already touched.
_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]
_DRIVE_API_NAME = "drive"
_DRIVE_API_VERSION = "v3"

_log = structlog.get_logger(__name__)


class GoogleDriveFileExport:
    """Upload files into a single Google Drive folder, creating it if needed.

    A file with the same *filename* is updated in place on repeated
    exports rather than duplicated, so the folder always converges on one
    current CSV per distinct filename. Because this authenticates as the
    real account owner (see module docstring), the very first run may
    legitimately *create* the file -- there is no dependency on a
    manually pre-created placeholder.
    """

    def __init__(self, oauth_token_json: str, folder_id: str) -> None:
        """Build the Drive client from a saved OAuth authorized-user JSON."""
        credentials = Credentials.from_authorized_user_info(
            json.loads(oauth_token_json), scopes=_DRIVE_SCOPES
        )
        self._service = build(
            _DRIVE_API_NAME, _DRIVE_API_VERSION, credentials=credentials
        )
        self._folder_id = folder_id

    async def upload(self, filename: str, content: bytes, mime_type: str) -> str:
        """Create or update *filename* in the configured folder; return its id."""
        return await asyncio.to_thread(self._upload_sync, filename, content, mime_type)

    def _upload_sync(self, filename: str, content: bytes, mime_type: str) -> str:
        """Handle upload sync."""
        media = MediaIoBaseUpload(
            io.BytesIO(content), mimetype=mime_type, resumable=False
        )
        try:
            existing_file_id = self._find_existing_file_id(filename)
            if existing_file_id is not None:
                updated = (
                    self._service.files()
                    .update(fileId=existing_file_id, media_body=media)
                    .execute()
                )
                _log.info(
                    "gdrive_file_updated", filename=filename, file_id=updated["id"]
                )
                return str(updated["id"])

            created = (
                self._service.files()
                .create(
                    body={"name": filename, "parents": [self._folder_id]},
                    media_body=media,
                    fields="id",
                )
                .execute()
            )
            _log.info("gdrive_file_created", filename=filename, file_id=created["id"])
            return str(created["id"])
        except HttpError as exc:
            raise FinancialDataDependencyError(
                f"Google Drive upload failed for '{filename}': {exc}"
            ) from exc

    def _find_existing_file_id(self, filename: str) -> str | None:
        """Return the id of *filename* inside the configured folder, if any."""
        escaped_filename = filename.replace("'", "\\'")
        query = (
            f"name = '{escaped_filename}' "
            f"and '{self._folder_id}' in parents "
            "and trashed = false"
        )
        response = self._service.files().list(q=query, fields="files(id)").execute()
        files = response.get("files", [])
        return str(files[0]["id"]) if files else None
