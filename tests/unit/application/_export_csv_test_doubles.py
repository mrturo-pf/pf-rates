"""Shared test doubles for CSV-export use case tests.

ExportExchangeRatesCsv and ExportCombinedFinancialDataCsv tests need
almost identical setups (currency stub, reference-data repository stub,
FX-provider stub that never has data, CSV-parsing helper) --
centralized here instead of copy-pasted per test module, which is what
triggered jscpd's duplicate-code gate.
"""

import csv
import io
from datetime import date
from decimal import Decimal

from rates.application.dto import (
    CurrencyDTO,
    RefreshRatesCommandDTO,
    RefreshRatesResultDTO,
)
from rates.application.ports.file_export_port import FileExportPort
from rates.application.ports.market_data_repository import MarketDataRepository
from rates.application.use_cases.export_exchange_rates_csv import (
    ExportExchangeRatesCsv,
)
from rates.application.use_cases.get_exchange_rate_value import GetExchangeRateValue


def build_currency(code: str) -> CurrencyDTO:
    """Build a minimal CurrencyDTO for the given code."""
    return CurrencyDTO(code=code, name=code, is_fiat=True, unit_kind="currency")


class StubReferenceDataRepository:
    """Minimal ReferenceDataRepository test double."""

    def __init__(self, currencies: list[CurrencyDTO]) -> None:
        self._currencies = currencies

    async def list_currencies(self) -> list[CurrencyDTO]:
        """Return the preconfigured currency list."""
        return self._currencies


class StubFxRateProvider:
    """FxRateProvider test double that never has data."""

    async def fetch_rate_entry(self, currency_code: str, on: date) -> None:
        """Return None unconditionally."""
        return None


class StubMarketDataRepositoryBase:
    """DB-value-only MarketDataRepository test double.

    Covers exactly the ports both exporters resolve exchange rates
    through. ExportCombinedFinancialDataCsv's test double additionally
    needs `list_economic_indices`, so it subclasses this rather than
    duplicating these four methods.
    """

    def __init__(self, db_values: dict[date, Decimal]) -> None:
        self._db_values = db_values

    async def get_exchange_rate_value(
        self, currency_code: str, rate_date: date
    ) -> Decimal | None:
        """Return a preconfigured DB value, ignoring currency_code."""
        return self._db_values.get(rate_date)

    async def get_latest_exchange_rate_value_before(
        self, code: str, before: date, on_or_after: date | None = None
    ) -> Decimal | None:
        """Return None -- fallback is out of scope for these tests."""
        return None

    async def list_exchange_rate_values(
        self, code: str, start: date, end: date
    ) -> dict[date, Decimal]:
        """Return the preconfigured DB values that fall within [start, end]."""
        return {
            rate_date: value
            for rate_date, value in self._db_values.items()
            if start <= rate_date <= end
        }

    async def refresh_rates(
        self, command: RefreshRatesCommandDTO
    ) -> RefreshRatesResultDTO:
        """Record nothing; never expected to be called in these tests."""
        return RefreshRatesResultDTO(
            upserted_exchange_rates=len(command.exchange_rates),
            upserted_economic_indices=0,
        )


def read_csv_rows(content: bytes) -> list[list[str]]:
    """Parse uploaded CSV bytes into a list of rows (including the header)."""
    text = content.decode("utf-8")
    return list(csv.reader(io.StringIO(text)))


def build_exchange_rates_csv_use_case(
    currencies: list[CurrencyDTO],
    market_data_repository: MarketDataRepository,
    file_export: FileExportPort,
) -> ExportExchangeRatesCsv:
    """Wire an ExportExchangeRatesCsv from an already-built market-data stub.

    Shared by both export_exchange_rates_csv and
    export_combined_financial_data_csv use-case tests: the combined
    exporter's test double for ExportExchangeRatesCsv must be wired
    identically to the base exporter's own tests -- only the concrete
    market_data_repository stub passed in differs (the combined one
    additionally exposes economic indices).
    """
    reference_data_repository = StubReferenceDataRepository(currencies)
    get_exchange_rate_value = GetExchangeRateValue(
        market_data_repository, StubFxRateProvider()
    )
    return ExportExchangeRatesCsv(
        reference_data_repository,
        market_data_repository,
        get_exchange_rate_value,
        file_export,
    )
