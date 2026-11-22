"""structlog logger factory."""

import structlog

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        *structlog.get_config()["processors"],
    ]
)

logger = structlog.get_logger(__name__)
