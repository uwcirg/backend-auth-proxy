import json
import time
from unittest.mock import AsyncMock

import fakeredis.aioredis
import httpx
import pytest
from jose import jwt

from fhir_backend_auth.auth.jwk_manager import JWT_ALGORITHM, JWKManager
from fhir_backend_auth.auth.token_client import TokenClient
from fhir_backend_auth.config import Settings


@pytest.fixture
def settings(tmp_key_dir):
    return Settings(
        oauth_client_id="test-client-id",
        upstream_token_url="https://epic.example.com/oauth2/token",
        oauth_scopes="system/Patient.read",
        jwk_key_dir=tmp_key_dir,
        redis_url="redis://localhost:6379/0",
        token_cache_key="test:access_token",
        token_cache_buffer_seconds=60,
    )


@pytest.fixture
def jwk_manager(tmp_key_dir):
    manager = JWKManager(tmp_key_dir)
    manager.generate_keys()
    return manager


@pytest.fixture
async def fake_redis():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


def test_client_assertion_uses_rs384(settings, jwk_manager):
    client = TokenClient(settings, jwk_manager, redis=AsyncMock())
    assertion = client._build_client_assertion()
    header = jwt.get_unverified_header(assertion)
    claims = jwt.get_unverified_claims(assertion)

    assert header["alg"] == JWT_ALGORITHM
    assert claims["iss"] == settings.oauth_client_id
    assert claims["sub"] == settings.oauth_client_id
    assert claims["aud"] == settings.upstream_token_url
    assert "jti" in claims


@pytest.mark.asyncio
async def test_cache_hit_skips_token_request(settings, jwk_manager, fake_redis):
    expires_at = int(time.time()) + 3600
    await fake_redis.set(
        settings.token_cache_key,
        json.dumps({"access_token": "cached-token", "expires_at": expires_at}),
    )

    http_client = AsyncMock()
    client = TokenClient(
        settings, jwk_manager, fake_redis, http_client=http_client
    )

    token = await client.get_access_token()
    assert token == "cached-token"
    http_client.post.assert_not_called()


@pytest.mark.asyncio
async def test_cache_miss_fetches_and_stores_token(
    settings, jwk_manager, fake_redis
):
    token_response = httpx.Response(
        200,
        json={"access_token": "fresh-token", "expires_in": 3600},
    )

    async def handler(request):
        return token_response

    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)

    client = TokenClient(
        settings, jwk_manager, fake_redis, http_client=http_client
    )

    token = await client.get_access_token()
    assert token == "fresh-token"

    cached = await fake_redis.get(settings.token_cache_key)
    payload = json.loads(cached)
    assert payload["access_token"] == "fresh-token"
    assert payload["expires_at"] > int(time.time())

    await http_client.aclose()


@pytest.mark.asyncio
async def test_expired_cache_refreshes_token(settings, jwk_manager, fake_redis):
    expires_at = int(time.time()) - 10
    await fake_redis.set(
        settings.token_cache_key,
        json.dumps({"access_token": "stale-token", "expires_at": expires_at}),
    )

    token_response = httpx.Response(
        200,
        json={"access_token": "new-token", "expires_in": 3600},
    )

    async def handler(request):
        return token_response

    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    client = TokenClient(
        settings, jwk_manager, fake_redis, http_client=http_client
    )

    token = await client.get_access_token()
    assert token == "new-token"
    await http_client.aclose()
