"""Shared HTTP-client test scaffolding for interfaces/api route unit tests.

Not a test module itself (no ``test_`` prefix, so pytest won't collect it) --
just the bits every route test module needs to spin up an authenticated
ASGI test client against the real app, without triggering the real
background market-data sync on startup.
"""

from typing import Any

from httpx import ASGITransport

from rates.interfaces.api.main import app

AUTHED: dict[str, Any] = {
    "transport": ASGITransport(app=app),
    "base_url": "http://test",
    "headers": {"X-API-Key": "test-key"},
}


class StubSyncUseCase:
    """No-op stub so app startup/route wiring never triggers a real sync."""

    async def execute(self, **_: object) -> None:
        """Do nothing."""
        return None
