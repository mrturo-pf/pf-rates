"""Use case for resolving multiple economic-index values."""

from decimal import Decimal

from rates.application.dto import EconomicIndexValueLookupDTO
from rates.application.ports.market_data_repository import MarketDataRepository
from rates.application.use_cases._bulk_rate_resolution_shared import (
    resolve_economic_index_pairs,
)


class GetEconomicIndexValues:
    """Resolve multiple economic-index period pairs in one use case call."""

    def __init__(self, repository: MarketDataRepository) -> None:
        """Initialize the repository dependency."""
        self._repository = repository

    async def execute(
        self, pairs: list[tuple[str, int, int]]
    ) -> list[EconomicIndexValueLookupDTO]:
        """Resolve all pairs and return one result for each input pair."""
        values: dict[tuple[str, int, int], Decimal | None] = {}
        if pairs:
            values = await resolve_economic_index_pairs(pairs, self._repository)
        return [
            EconomicIndexValueLookupDTO(
                code=code,
                period_year=year,
                period_month=month,
                index_value=values.get((code, year, month)),
            )
            for code, year, month in pairs
        ]
