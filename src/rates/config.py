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

    # Exactly one of the two below should be set. In production, Secret
    # Manager injects the raw JSON content directly into
    # gdrive_oauth_token_json. Locally, gdrive_oauth_token_json_path points
    # at the token file produced by scripts/gdrive_oauth_setup.py (see
    # ../secrets/pf-rates/ at the repo root). This is an OAuth authorized-
    # user token (refresh_token + client_id/secret), NOT a service account
    # key -- see docs/google-drive-credentials-setup.md for why.
    gdrive_oauth_token_json: str | None = Field(
        default=None, validation_alias="pf_rates_gdrive_oauth_token_json"
    )
    gdrive_oauth_token_json_path: str | None = Field(
        default=None, validation_alias="pf_rates_gdrive_oauth_token_json_path"
    )
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
