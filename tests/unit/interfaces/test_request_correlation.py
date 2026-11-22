"""Tests for the request-correlation HTTP contract."""

import asyncio
from uuid import UUID

import httpx
import pytest
import structlog
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse

from rates.interfaces.api.request_correlation import (
    install_request_correlation_middleware,
    install_request_correlation_openapi,
    validate_request_id,
)

_VALID_ID = "550e8400-e29b-41d4-a716-446655440000"


def _app() -> FastAPI:
    app = FastAPI()
    install_request_correlation_middleware(app)
    install_request_correlation_openapi(app)

    def require_key() -> None:
        """Reject requests without the synthetic API key."""
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="Invalid or missing API key.")

    @app.get("/open")
    async def open_route() -> PlainTextResponse:
        return PlainTextResponse("ok")

    @app.exception_handler(Exception)
    async def unexpected_error_handler(_request, _exc) -> JSONResponse:
        """Return a synthetic unhandled-error response for middleware testing."""
        return JSONResponse(status_code=500, content={"detail": "Unexpected."})

    @app.get("/cancel")
    async def cancel() -> PlainTextResponse:
        """Raise cancellation to exercise middleware cleanup."""
        raise asyncio.CancelledError

    @app.get("/boom")
    async def boom() -> PlainTextResponse:
        """Raise an exception handled as a synthetic 500."""
        raise RuntimeError("boom")

    @app.get("/protected", dependencies=[Depends(require_key)])
    async def protected_route() -> PlainTextResponse:
        return PlainTextResponse("ok")

    return app


@pytest.mark.asyncio
async def test_request_start_and_completion_share_request_id() -> None:
    """Request lifecycle events use one bound correlation ID."""
    with structlog.testing.capture_logs(
        processors=[structlog.contextvars.merge_contextvars]
    ) as logs:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_app()), base_url="http://test"
        ) as client:
            response = await client.get("/open", headers={"X-Request-ID": _VALID_ID})

    events = {
        entry["event"]: entry["request_id"]
        for entry in logs
        if entry.get("event") in {"request_started", "request_completed"}
    }
    assert response.status_code == 200
    assert events == {
        "request_started": _VALID_ID,
        "request_completed": _VALID_ID,
    }


def test_openapi_documents_request_correlation_contract() -> None:
    """OpenAPI exposes the optional header and validation response."""
    app = _app()
    schema = app.openapi()
    cached = app.openapi()
    operation = schema["paths"]["/open"]["get"]
    parameters = operation["parameters"]

    assert schema is cached
    assert any(parameter["name"] == "X-Request-ID" for parameter in parameters)
    assert "400" in operation["responses"]


def test_validate_request_id_normalizes_uppercase_uuid() -> None:
    """Canonical UUIDv4 input is returned in lowercase."""
    value, reason = validate_request_id(_VALID_ID.upper())

    assert value == _VALID_ID
    assert reason is None


@pytest.mark.parametrize(
    "value",
    [
        "550e8400e29b41d4a716446655440000",
        "{550e8400-e29b-41d4-a716-446655440000}",
        "urn:uuid:550e8400-e29b-41d4-a716-446655440000",
        "550e8400-e29b-11d4-a716-446655440000",
    ],
)
def test_validate_request_id_rejects_noncanonical_or_non_v4(value: str) -> None:
    """Only canonical UUIDv4 values are accepted."""
    normalized, reason = validate_request_id(value)

    assert normalized is None
    assert reason == "request_id_malformed"


@pytest.mark.asyncio
async def test_missing_header_generates_and_returns_request_id() -> None:
    """An omitted header gets one valid response ID."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://test"
    ) as client:
        response = await client.get("/open")

    request_id = response.headers["X-Request-ID"]
    assert response.status_code == 200
    assert UUID(request_id).version == 4
    assert "request_id" not in structlog.contextvars.get_contextvars()


@pytest.mark.asyncio
async def test_invalid_header_returns_new_id_and_reason_code() -> None:
    """Malformed input is rejected without echoing the invalid value."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://test"
    ) as client:
        response = await client.get("/open", headers={"X-Request-ID": "not-an-id"})

    assert response.status_code == 400
    assert response.json()["code"] == "request_id_malformed"
    assert response.headers["X-Request-ID"] != "not-an-id"
    assert UUID(response.headers["X-Request-ID"]).version == 4


@pytest.mark.asyncio
async def test_too_long_header_returns_specific_reason() -> None:
    """Oversized correlation values expose the stable length reason code."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://test"
    ) as client:
        response = await client.get("/open", headers={"X-Request-ID": "x" * 65})

    assert response.status_code == 400
    assert response.json()["code"] == "request_id_too_long"


@pytest.mark.asyncio
async def test_comma_separated_header_returns_400() -> None:
    """Comma-separated correlation values are rejected."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://test"
    ) as client:
        response = await client.get(
            "/open", headers={"X-Request-ID": f"{_VALID_ID},{_VALID_ID}"}
        )

    assert response.status_code == 400
    assert response.json()["code"] == "request_id_malformed"


@pytest.mark.asyncio
async def test_duplicate_header_returns_400() -> None:
    """Duplicate correlation values are rejected."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://test"
    ) as client:
        response = await client.get(
            "/open",
            headers=[("X-Request-ID", _VALID_ID), ("X-Request-ID", _VALID_ID)],
        )

    assert response.status_code == 400
    assert response.json()["code"] == "request_id_malformed"


@pytest.mark.asyncio
async def test_invalid_header_takes_precedence_over_invalid_api_key() -> None:
    """Correlation validation runs before authentication dependencies."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://test"
    ) as client:
        response = await client.get("/protected", headers={"X-Request-ID": "invalid"})

    assert response.status_code == 400
    assert response.json()["code"] == "request_id_malformed"
    assert "X-Request-ID" in response.headers


@pytest.mark.asyncio
async def test_cancellation_clears_request_context() -> None:
    """Cancellation clears the bound request ID before propagating."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://test"
    ) as client:
        response = await client.get("/cancel", headers={"X-Request-ID": _VALID_ID})

    assert response.status_code == 500
    assert "request_id" not in structlog.contextvars.get_contextvars()


@pytest.mark.asyncio
async def test_unhandled_500_response_keeps_request_id() -> None:
    """Unhandled errors retain the correlation response header."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(), raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.get("/boom", headers={"X-Request-ID": _VALID_ID})

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == _VALID_ID


@pytest.mark.asyncio
async def test_valid_request_id_is_returned_on_forbidden_response() -> None:
    """Authentication failures remain correlated."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://test"
    ) as client:
        response = await client.get("/protected", headers={"X-Request-ID": _VALID_ID})

    assert response.status_code == 403
    assert response.headers["X-Request-ID"] == _VALID_ID
