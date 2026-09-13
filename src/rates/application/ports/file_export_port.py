"""Port definition for exporting generated files to external storage."""

from typing import Protocol


class FileExportPort(Protocol):
    """Outbound port for persisting a generated file outside this service.

    Implementations own the concrete destination (Google Drive, S3, a local
    filesystem, ...) and the identity of what "already exists" means there.
    The application layer only cares that a file goes somewhere and gets an
    identifier back.
    """

    async def upload(self, filename: str, content: bytes, mime_type: str) -> str:
        """Upload *content* as *filename* and return a storage identifier.

        Implementations should overwrite an existing file with the same
        *filename* in the configured destination rather than creating
        duplicates, so repeated exports converge on a single file.
        """
        ...
