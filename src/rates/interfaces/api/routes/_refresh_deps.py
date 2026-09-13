"""Shared FastAPI dependencies for market-data refresh routes.

Both the exchange-rate and economic-index routes depend on the same
port, use-case, dependency functions, and response schema. This module
centralises those imports so each route file can reference a single
source instead of duplicating the same import block.
"""

from rates.application.ports.market_data_repository import MarketDataRepository
from rates.application.use_cases.refresh_rates import RefreshRates
from rates.interfaces.api.dependencies import (
    get_market_data_repository,
    get_refresh_rates_use_case,
)
from rates.interfaces.api.errors import to_http_exception
from rates.interfaces.api.schemas import RefreshRatesResponse

__all__ = [
    "MarketDataRepository",
    "RefreshRates",
    "get_market_data_repository",
    "get_refresh_rates_use_case",
    "to_http_exception",
    "RefreshRatesResponse",
]
