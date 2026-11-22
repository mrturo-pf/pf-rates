"""Request correlation middleware and UUIDv4 contract."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID, uuid4

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

_REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_MAX_LENGTH = 64
_CANONICAL_UUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
logger = structlog.get_logger(__name__)


def generate_request_id() -> str:
    """Generate a canonical lowercase UUIDv4 request identifier."""
    return str(uuid4())


def validate_request_id(value: str) -> tuple[str | None, str | None]:
    """Validate and normalize a supplied request identifier.

    Returns:
        A canonical lowercase UUIDv4 and no reason on success, or no value and
        a stable reason code on failure.
    """
    if len(value) > _REQUEST_ID_MAX_LENGTH:
        return None, "request_id_too_long"
    if not _CANONICAL_UUID_PATTERN.fullmatch(value):
        return None, "request_id_malformed"
    parsed = UUID(value)
    if parsed.version != 4:
        return None, "request_id_malformed"
    return str(parsed), None


def _header_values(request: Request) -> list[str]:
    """Return every value supplied for the correlation header."""
    return request.headers.getlist(_REQUEST_ID_HEADER.lower())


def install_request_correlation_middleware(app: FastAPI) -> None:
    """Install request correlation middleware on the FastAPI application."""

    @app.middleware("http")
    async def request_correlation_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Bind one request ID before authentication and clear it afterward."""
        structlog.contextvars.clear_contextvars()
        values = _header_values(request)
        supplied = values[0] if len(values) == 1 else None
        reason: str | None = None
        if supplied is None:
            reason = "request_id_malformed" if values else None
        elif "," in supplied:
            reason = "request_id_malformed"
        else:
            supplied, reason = validate_request_id(supplied)

        request_id = supplied or generate_request_id()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        logger.info("request_started", method=request.method, path=request.url.path)
        try:
            response: Response
            if reason is not None:
                logger.warning("request_id_rejected", reason_code=reason)
                response = JSONResponse(
                    status_code=400,
                    content={
                        "detail": "Invalid X-Request-ID.",
                        "code": reason,
                    },
                    headers={_REQUEST_ID_HEADER: request_id},
                )
            else:
                response = await call_next(request)
                response.headers[_REQUEST_ID_HEADER] = request_id
            logger.info(
                "request_completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
            )
            return response
        except Exception:
            logger.exception(
                "request_failed",
                method=request.method,
                path=request.url.path,
                status_code=500,
            )
            response = JSONResponse(
                status_code=500,
                content={
                    "detail": "Unexpected server error.",
                    "path": request.url.path,
                },
                headers={_REQUEST_ID_HEADER: request_id},
            )
            logger.info(
                "request_completed",
                method=request.method,
                path=request.url.path,
                status_code=500,
            )
            return response
        finally:
            structlog.contextvars.clear_contextvars()


def install_request_correlation_openapi(app: FastAPI) -> None:
    """Document the optional header and correlation validation response."""

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
            tags=app.openapi_tags,
        )
        error_schema = {
            "type": "object",
            "properties": {
                "detail": {"type": "string"},
                "code": {
                    "type": "string",
                    "enum": ["request_id_malformed", "request_id_too_long"],
                },
            },
        }
        for path_item in schema.get("paths", {}).values():
            for operation in path_item.values():
                if not isinstance(operation, dict):
                    continue
                parameters = operation.setdefault("parameters", [])
                if not any(
                    parameter.get("name") == _REQUEST_ID_HEADER
                    and parameter.get("in") == "header"
                    for parameter in parameters
                ):
                    parameters.append(
                        {
                            "name": _REQUEST_ID_HEADER,
                            "in": "header",
                            "required": False,
                            "schema": {
                                "type": "string",
                                "format": "uuid",
                                "maxLength": _REQUEST_ID_MAX_LENGTH,
                            },
                        }
                    )
                operation.setdefault(
                    "responses",
                    {},
                ).setdefault(
                    "400",
                    {
                        "description": "Invalid X-Request-ID.",
                        "content": {"application/json": {"schema": error_schema}},
                    },
                )
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]


__all__ = [
    "generate_request_id",
    "install_request_correlation_middleware",
    "install_request_correlation_openapi",
    "validate_request_id",
]
