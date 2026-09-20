"""Application settings."""

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Represent Settings."""

    api_key: str = Field(validation_alias="pf_rates_api_key")
    database_url: str = Field(
        default="postgresql+asyncpg://pf_db:pf_db@localhost:5432/pf_db",
        validation_alias="pf_database_url",
    )
    rate_provider_timeout_seconds: int = 10
    http_proxy: str | None = None

    @field_validator("http_proxy", mode="before")
    @classmethod
    def _empty_str_to_none(_cls: type, v: object) -> object:
        """Treat empty-string proxy as absent (no proxy)."""
        return None if v == "" else v

    mindicador_base_url: str = "https://mindicador.cl/api"
    sii_base_url: str = "https://www.sii.cl"
    bcch_api_base_url: str = "https://si3.bcentral.cl/SieteRestWS/SieteRestWS.ashx"
    bcch_api_user: str | None = None
    bcch_api_password: str | None = None
    bcch_series_uf: str | None = None
    bcch_series_usd: str | None = None
    bcch_series_eur: str | None = None
    bcch_series_utm: str | None = None
    bcch_series_ipc_cl: str | None = None

    # Authentication for the Google Drive export uses Application Default
    # Credentials (ADC), not a stored token here: Cloud Run's attached
    # service account in production, or `gcloud auth application-default
    # login` locally. This is the only remaining setting -- see
    # docs/google-drive-credentials-setup.md for the full picture,
    # including the accepted trade-off (a service account can update an
    # existing Drive file but not create a brand-new one).
    gdrive_export_folder_id: str | None = Field(
        default=None, validation_alias="pf_rates_gdrive_export_folder_id"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="FINANCIAL_DATA_",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()  # type: ignore[call-arg]
