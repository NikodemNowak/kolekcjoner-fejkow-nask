"""Application settings, read once from environment variables (prefix ``APP_``)."""

from __future__ import annotations

from functools import cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration."""

    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", extra="ignore")

    data_dir: Path = Path("./data")
    log_level: str = "INFO"
    max_artifact_mb: int = 2048  # larger files are skipped with a warning
    feature_cache: Path = Field(
        default=Path.home() / ".cache" / "fakecollector" / "features",
        validation_alias=AliasChoices("FEATURE_CACHE", "APP_FEATURE_CACHE"),
    )
    # Passive enrichment (DNS over HTTPS, RDAP, crt.sh, CERT Polska list) is opt-in:
    # a run never needs the network. `ALLOW_ENRICH` is the name used in the plan and docs.
    allow_enrich: bool = Field(
        default=False, validation_alias=AliasChoices("ALLOW_ENRICH", "APP_ALLOW_ENRICH")
    )
    enrich_cache_dir: Path = Path.home() / ".cache" / "fakecollector" / "enrich"
    enrich_timeout_s: float = 5.0
    # Run directory the Streamlit app opens when `fakecollector app` gets no argument.
    run_dir: Path | None = None


@cache
def get_settings() -> Settings:
    """Return the cached settings instance."""
    return Settings()
