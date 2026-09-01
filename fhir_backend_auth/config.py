"""Environment-based application configuration."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    server_name: str = "localhost:8000"
    preferred_url_scheme: str = "http"

    oauth_client_id: str
    upstream_token_url: str = (
        "https://fhir.epic.com/interconnect-fhir-oauth/oauth2/token"
    )
    upstream_fhir_url: str = (
        "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4"
    )
    oauth_scopes: str = "system/Patient.read system/Observation.read"

    jwk_key_dir: str = "/data/jwks"

    redis_url: str = "redis://127.0.0.1:6379/0"
    token_cache_key: str = "upstream:access_token"
    token_cache_buffer_seconds: int = 60

    log_level: str = "INFO"
    testing: bool = False

    @property
    def jwks_url(self) -> str:
        return (
            f"{self.preferred_url_scheme}://{self.server_name}"
            "/.well-known/jwks.json"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
