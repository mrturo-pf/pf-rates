"""Shared session-lifecycle mixin for SQLAlchemy repositories.

Every SqlAlchemy*Repository in this package holds exactly one
AsyncSession and needs to be able to swap it out mid-flight (see
ExportJobSessionSwapper in interfaces/api/dependencies.py). Extracted
here so the three repositories don't each carry an identical
copy-pasted __init__/rebind pair.
"""

from sqlalchemy.ext.asyncio import AsyncSession


class SessionBoundRepositoryMixin:
    """Own an AsyncSession and allow it to be swapped out later."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the instance."""
        self._session = session

    def rebind(self, session: AsyncSession) -> None:
        """Swap the underlying session used for every subsequent call.

        Lets a long-running background job (the async export loop, which
        can run for many minutes) periodically replace a DB connection
        before it goes stale server-side, without needing to reconstruct
        this repository -- callers that already hold a reference to it
        keep using the same instance.
        """
        self._session = session
