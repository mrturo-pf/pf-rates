"""Google Drive adapter for the FileExportPort.

Authenticates via Application Default Credentials (ADC): Cloud Run's
attached service account (`pf-rates@<PROJECT>.iam.gserviceaccount.com`) in
production, or whatever `gcloud auth application-default login` configured
locally. No token is stored, refreshed, or managed by this service at all
-- ADC resolution is entirely `google-auth`'s job.

Trade-off accepted deliberately -- full write-up in
docs/google-drive-credentials-setup.md: a Google service account has no
storage quota of its own in a personal (non-Workspace) Drive, so it cannot
`create()` a brand-new file, only `update()` a pre-existing one that has
been shared with it as Editor. This adapter already prefers `update()`
whenever a file with the target name exists (see `_find_existing_file_id`),
which is every normal run once the destination file exists once. Creating
that file the very first time (or recreating it if someone deletes it) is a
rare, manual, one-off step using a real Google account's OAuth credentials
-- see `scripts/gdrive_oauth_setup.py`.

The `googleapiclient`/`google-auth` libraries are synchronous; every call
is wrapped in `asyncio.to_thread` to avoid blocking the event loop, matching
the pattern already used for the HTTP-based rate providers.
"""

from __future__ import annotations

import asyncio
import io

import structlog
from google.auth import default as google_auth_default
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

from rates.application.errors import FinancialDataDependencyError

# Full Drive access, not the narrower "drive.file" scope: this adapter must
# be able to find a pre-existing file across the whole configured folder
# (in case it was created by hand or by a prior, differently-scoped run),
# not just files this exact identity already touched.
_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]
_DRIVE_API_NAME = "drive"
_DRIVE_API_VERSION = "v3"

_log = structlog.get_logger(__name__)


class GoogleDriveFileExport:
    """Upload files into a single Google Drive folder, creating it if needed.

    A file with the same *filename* is updated in place on repeated
    exports rather than duplicated, so the folder always converges on one
    current CSV per distinct filename. `update()` needs no storage quota
    of its own, so this works fine under a bare service account identity
    even though `create()` (first-run only) would not -- see the module
    docstring for the accepted trade-off and the manual recovery path.
    """

    def __init__(self, folder_id: str) -> None:
        """Build the Drive client using Application Default Credentials."""
        credentials, _project_id = google_auth_default(scopes=_DRIVE_SCOPES)
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
