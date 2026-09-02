"""Tests for SMART and OpenID OAuth configuration discovery."""

import json

import fakeredis.aioredis
import httpx
import pytest

from fhir_backend_auth.auth.smart_configuration import (
    SmartConfiguration,
    fetch_well_known_configuration,
    resolve_smart_configuration,
)
from fhir_backend_auth.config import Settings

UPSTREAM_FHIR_URL = "https://epic.example.com/api/FHIR/R4"
TOKEN_ENDPOINT = "https://epic.example.com/oauth2/token"


@pytest.fixture
def settings(tmp_key_dir):
    return Settings(
        oauth_client_id="test-client-id",
        upstream_token_url=None,
        upstream_fhir_url=UPSTREAM_FHIR_URL,
        jwk_key_dir=tmp_key_dir,
        oauth_configuration_cache_key="test:oauth-configuration",
    )


@pytest.fixture
async def fake_redis():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


@pytest.mark.asyncio
async def test_fetch_from_smart_configuration():
    async def handler(request):
        assert request.url.path.endswith("/.well-known/smart-configuration")
        return httpx.Response(
            200,
            json={
                "token_endpoint": TOKEN_ENDPOINT,
                "issuer": "https://epic.example.com",
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    config = await fetch_well_known_configuration(UPSTREAM_FHIR_URL, client)
    await client.aclose()

    assert config.token_endpoint == TOKEN_ENDPOINT
    assert config.issuer == "https://epic.example.com"
    assert config.discovery_url.endswith("/.well-known/smart-configuration")


@pytest.mark.asyncio
async def test_fallback_to_openid_configuration_on_smart_404():
    calls = []

    async def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/.well-known/smart-configuration"):
            return httpx.Response(404)
        return httpx.Response(
            200,
            json={"token_endpoint": TOKEN_ENDPOINT},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    config = await fetch_well_known_configuration(UPSTREAM_FHIR_URL, client)
    await client.aclose()

    assert len(calls) == 2
    assert config.token_endpoint == TOKEN_ENDPOINT
    assert config.discovery_url.endswith("/.well-known/openid-configuration")


@pytest.mark.asyncio
async def test_fallback_when_smart_configuration_missing_token_endpoint():
    calls = []

    async def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/.well-known/smart-configuration"):
            return httpx.Response(200, json={"issuer": "https://epic.example.com"})
        return httpx.Response(
            200,
            json={"token_endpoint": TOKEN_ENDPOINT},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    config = await fetch_well_known_configuration(UPSTREAM_FHIR_URL, client)
    await client.aclose()

    assert len(calls) == 2
    assert config.discovery_url.endswith("/.well-known/openid-configuration")


@pytest.mark.asyncio
async def test_both_discovery_urls_failing_raises():
    async def handler(request):
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="Could not discover OAuth configuration"):
        await fetch_well_known_configuration(UPSTREAM_FHIR_URL, client)
    await client.aclose()


@pytest.mark.asyncio
async def test_upstream_token_url_override_skips_http(settings, fake_redis):
    settings = settings.model_copy(
        update={"upstream_token_url": TOKEN_ENDPOINT}
    )

    async def handler(request):
        pytest.fail("HTTP should not be called when override is set")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    config = await resolve_smart_configuration(settings, fake_redis, client)
    await client.aclose()

    assert config.token_endpoint == TOKEN_ENDPOINT
    assert config.discovery_url is None


@pytest.mark.asyncio
async def test_resolve_uses_redis_cache(settings, fake_redis):
    """Return cached OAuth configuration without calling well-known endpoints."""
    cached = SmartConfiguration(
        token_endpoint=TOKEN_ENDPOINT,
        discovery_url=f"{UPSTREAM_FHIR_URL}/.well-known/smart-configuration",
    )
    await fake_redis.set(
        settings.oauth_configuration_cache_key,
        json.dumps(cached.to_dict()),
    )

    async def handler(request):
        pytest.fail("HTTP should not be called on cache hit")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    config = await resolve_smart_configuration(settings, fake_redis, client)
    await client.aclose()

    assert config.token_endpoint == TOKEN_ENDPOINT


@pytest.mark.asyncio
async def test_resolve_fetches_and_caches_on_miss(settings, fake_redis):
    """Discover OAuth configuration over HTTP and persist it in Redis on cache miss."""
    async def handler(request):
        return httpx.Response(
            200,
            json={"token_endpoint": TOKEN_ENDPOINT},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    config = await resolve_smart_configuration(settings, fake_redis, client)
    await client.aclose()

    assert config.token_endpoint == TOKEN_ENDPOINT
    cached = await fake_redis.get(settings.oauth_configuration_cache_key)
    assert json.loads(cached)["token_endpoint"] == TOKEN_ENDPOINT
