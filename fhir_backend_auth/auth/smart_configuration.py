"""OAuth server metadata discovery from SMART / OpenID well-known endpoints."""

import json
import logging
from dataclasses import asdict, dataclass

import httpx
from redis.asyncio import Redis

from fhir_backend_auth.config import DISCOVERY_PATHS, Settings

logger = logging.getLogger(__name__)


@dataclass
class SmartConfiguration:
    token_endpoint: str
    issuer: str | None = None
    authorization_endpoint: str | None = None
    discovery_url: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "SmartConfiguration":
        return cls(
            token_endpoint=data["token_endpoint"],
            issuer=data.get("issuer"),
            authorization_endpoint=data.get("authorization_endpoint"),
            discovery_url=data.get("discovery_url"),
        )

    def to_dict(self) -> dict:
        return asdict(self)


async def fetch_well_known_configuration(
    upstream_fhir_url: str,
    http_client: httpx.AsyncClient,
) -> SmartConfiguration:
    """Fetch OAuth configuration, trying SMART then OpenID well-known URLs."""
    base = upstream_fhir_url.rstrip("/")
    last_error: Exception | None = None

    for path in DISCOVERY_PATHS:
        url = f"{base}{path}"
        try:
            response = await http_client.get(
                url,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            data = response.json()
            token_endpoint = data.get("token_endpoint")
            if not token_endpoint:
                raise ValueError(f"token_endpoint missing from {url}")
            logger.info("Discovered OAuth configuration from %s", url)
            return SmartConfiguration(
                token_endpoint=token_endpoint,
                issuer=data.get("issuer"),
                authorization_endpoint=data.get("authorization_endpoint"),
                discovery_url=url,
            )
        except (httpx.HTTPStatusError, ValueError) as exc:
            logger.debug("Discovery failed for %s: %s", url, exc)
            last_error = exc
            continue

    raise RuntimeError(
        f"Could not discover OAuth configuration from {base}"
    ) from last_error


async def resolve_smart_configuration(
    settings: Settings,
    redis: Redis,
    http_client: httpx.AsyncClient,
) -> SmartConfiguration:
    """Resolve OAuth configuration from override, cache, or discovery."""
    if settings.upstream_token_url:
        return SmartConfiguration(
            token_endpoint=settings.upstream_token_url,
            discovery_url=None,
        )

    cached = await redis.get(settings.oauth_configuration_cache_key)
    if cached:
        try:
            return SmartConfiguration.from_dict(json.loads(cached))
        except (json.JSONDecodeError, KeyError):
            await redis.delete(settings.oauth_configuration_cache_key)

    config = await fetch_well_known_configuration(
        settings.upstream_fhir_url,
        http_client,
    )
    await redis.set(
        settings.oauth_configuration_cache_key,
        json.dumps(config.to_dict()),
        ex=settings.oauth_configuration_cache_ttl_seconds,
    )
    return config
