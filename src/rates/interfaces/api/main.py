"""FastAPI application entrypoint."""

import asyncio
import os
import time
from contextlib import asynccontextmanager, suppress
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from rates.application.errors import FinancialDataError
from rates.application.ports.reference_data_repository import (
    ReferenceDataRepository,
)
from rates.config import settings
from rates.infrastructure.db.session import SessionLocal
from rates.infrastructure.logging.logger import logger
from rates.interfaces.api.dependencies import (
    build_sync_use_case,
    get_reference_data_repository,
)
from rates.interfaces.api.errors import to_http_exception
from rates.interfaces.api.routes.exchange_rates import (
    router as exchange_rates_router,
)
from rates.interfaces.api.routes.export_jobs import (
    router as export_jobs_router,
)
from rates.interfaces.api.routes.economic_indices import (
    router as economic_indices_router,
)
from rates.interfaces.api.routes.income_tax_brackets import (
    router as income_tax_brackets_router,
)
from rates.interfaces.api.routes.sync import router as sync_router
from rates.interfaces.api.security import verify_api_key

_root_router = APIRouter()

# Captured once, at process start (module import time), to compute uptime.
_START_TIME = time.monotonic()


class CurrencyRead(BaseModel):
    """Represent Currency Read."""

    code: str
    name: str
    is_fiat: bool
    unit_kind: str


class HealthRead(BaseModel):
    """Represent Health Read."""

    status: str
    service: str
    uptime_seconds: float


@_root_router.get("/health", tags=["health"], response_model=HealthRead)
async def health() -> HealthRead:
    """Return service health status, including process uptime."""
    return HealthRead(
        status="ok",
        service="pf-rates",
        uptime_seconds=round(time.monotonic() - _START_TIME, 3),
    )


@_root_router.get(
    "/currencies",
    tags=["currencies"],
    response_model=list[CurrencyRead],
    dependencies=[Depends(verify_api_key)],
)
async def list_currencies(
    repository: ReferenceDataRepository = Depends(get_reference_data_repository),
) -> list[CurrencyRead]:
    """List all supported currencies."""
    return [
        CurrencyRead(
            code=item.code,
            name=item.name,
            is_fiat=item.is_fiat,
            unit_kind=item.unit_kind,
        )
        for item in await repository.list_currencies()
    ]


async def _run_startup_sync() -> None:
    """Run a rolling market-data sync at startup (skipped during tests)."""
    if "PYTEST_CURRENT_TEST" in os.environ:
        return

    logger.info("startup_market_data_sync_started")
    try:
        async with SessionLocal() as session:
            result = await build_sync_use_case(session).execute()
    except asyncio.CancelledError:
        logger.info("startup_market_data_sync_cancelled")
        raise
    except Exception as exc:  # noqa: BLE001 - gracefully skip startup sync on any error
        logger.warning("startup_market_data_sync_skipped", reason=str(exc))
        return

    logger.info(
        "startup_market_data_sync_completed",
        upserted_exchange_rates=result.upserted_exchange_rates,
        upserted_economic_indices=result.upserted_economic_indices,
        upserted_brackets=result.upserted_brackets,
    )


@asynccontextmanager
async def lifespan(application: FastAPI):  # type: ignore[type-arg]
    """Run application lifespan hooks."""
    _parsed = urlparse(settings.database_url)
    logger.info(
        "startup_database_target",
        host=_parsed.hostname,
        port=_parsed.port,
        database=_parsed.path.lstrip("/"),
    )
    sync_task = asyncio.create_task(_run_startup_sync())
    application.state.market_data_sync_task = sync_task
    try:
        yield
    finally:
        if not sync_task.done():
            sync_task.cancel()
            with suppress(asyncio.CancelledError):
                await sync_task


_DESCRIPTION = """
Chilean financial reference data microservice.

Provides exchange rates (USD, EUR), economic indices (UF, UTM, IPC),
and income tax brackets sourced from Mindicador and Banco Central de Chile.

## Authentication

All endpoints except `GET /health` require an `X-API-Key` header.
Use the **Authorize** button above to set your key for this session.
"""

_OPENAPI_TAGS = [
    {"name": "health", "description": "Service liveness check."},
    {"name": "currencies", "description": "Supported currency catalogue."},
    {
        "name": "exchange-rates",
        "description": "CLP exchange rates — list, lookup, refresh, and CSV export.",
    },
    {
        "name": "economic-indices",
        "description": "UF / UTM / IPC indices — list, lookup, and refresh.",
    },
    {
        "name": "income-tax-brackets",
        "description": "Chilean income tax brackets — lookup, list, and refresh.",
    },
    {
        "name": "sync",
        "description": "Trigger a rolling 365-day sync of all missing market data.",
    },
]

app = FastAPI(
    title="pf-rates",
    version="0.1.0",
    description=_DESCRIPTION,
    openapi_tags=_OPENAPI_TAGS,
    lifespan=lifespan,
)
app.include_router(_root_router)
app.include_router(exchange_rates_router, dependencies=[Depends(verify_api_key)])
app.include_router(export_jobs_router, dependencies=[Depends(verify_api_key)])
app.include_router(economic_indices_router, dependencies=[Depends(verify_api_key)])
app.include_router(income_tax_brackets_router, dependencies=[Depends(verify_api_key)])
app.include_router(sync_router, dependencies=[Depends(verify_api_key)])


@app.exception_handler(FinancialDataError)
async def _handle_financial_data_error(
    request: Request, exc: FinancialDataError
) -> JSONResponse:
    """Convert any FinancialDataError into its mapped HTTP response.

    Most routes already catch FinancialDataError locally and call
    to_http_exception() themselves. This handler is a safety net for the
    cases that can't be caught by a route's own try/except -- most notably
    a FastAPI dependency (Depends) that raises while being resolved, which
    happens before the route body ever runs (e.g. a use-case dependency
    calling get_file_export_port() when Google Drive isn't configured).
    Without this, such errors would surface as a bare 500 instead of the
    correct 503/400/404/502.
    """
    http_exc = to_http_exception(exc)
    return JSONResponse(
        status_code=http_exc.status_code, content={"detail": http_exc.detail}
    )
