"""Environment-based application configuration."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

DISCOVERY_PATHS = (
    "/.well-known/smart-configuration",
    "/.well-known/openid-configuration",
)


class Settings(BaseSettings):
    """Environment-driven configuration for the FHIR backend auth proxy."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    server_name: str = "localhost:8000"
    preferred_url_scheme: str = "http"

    oauth_client_id: str
    upstream_token_url: str | None = None
    upstream_fhir_url: str = (
        "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4"
    )
    oauth_scopes: str = "system/Patient.read system/Observation.read"

    jwk_key_dir: str = "/data/jwks"

    redis_url: str = "redis://127.0.0.1:6379/0"
    token_cache_key: str = "upstream:access_token"
    token_cache_buffer_seconds: int = 60
    oauth_configuration_cache_key: str = "upstream:oauth-configuration"
    oauth_configuration_cache_ttl_seconds: int = 86400

    log_level: str = "INFO"
    testing: bool = False

    @property
    def jwks_url(self) -> str:
        return (
            f"{self.preferred_url_scheme}://{self.server_name}"
            "/.well-known/jwks.json"
        )

    @property
    def discovery_urls(self) -> list[str]:
        base = self.upstream_fhir_url.rstrip("/")
        return [f"{base}{path}" for path in DISCOVERY_PATHS]


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance loaded from the environment."""
    return Settings()
