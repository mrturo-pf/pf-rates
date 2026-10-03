"""Use case for resolving multiple exchange-rate values."""

from datetime import date
from decimal import Decimal

from rates.application.dto import ExchangeRateValueLookupDTO
from rates.application.ports.market_data_repository import MarketDataRepository
from rates.application.use_cases._bulk_rate_resolution_shared import (
    resolve_exchange_rate_pairs,
)
from rates.application.use_cases.get_exchange_rate_value import GetExchangeRateValue


class GetExchangeRateValues:
    """Resolve multiple currency/date pairs while preserving request order."""

    def __init__(
        self,
        repository: MarketDataRepository,
        singular_use_case: GetExchangeRateValue,
    ) -> None:
        """Initialize the batch use case dependencies."""
        self._repository = repository
        self._singular_use_case = singular_use_case

    async def execute(
        self, pairs: list[tuple[str, date]], today: date
    ) -> list[ExchangeRateValueLookupDTO]:
        """Resolve all pairs and return one result for each input pair."""
        values: dict[tuple[str, date], Decimal | None] = {}
        if pairs:
            values = await resolve_exchange_rate_pairs(
                pairs, self._repository, self._singular_use_case, today
            )
        return [
            ExchangeRateValueLookupDTO(
                currency_code=currency_code,
                rate_date=rate_date,
                value_clp=values.get((currency_code, rate_date)),
            )
            for currency_code, rate_date in pairs
        ]
