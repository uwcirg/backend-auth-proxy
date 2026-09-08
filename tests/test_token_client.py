"""Tests for OAuth token acquisition, caching, and client assertion behavior."""

import json
import logging
import time
from urllib.parse import parse_qs

import fakeredis.aioredis
import httpx
import pytest
from authlib.jose import jwt
from cryptography.hazmat.primitives import serialization

from fhir_backend_auth.auth.jwk_manager import JWT_ALGORITHM, JWKManager
from fhir_backend_auth.auth.oauth_client import create_oauth_client
from fhir_backend_auth.auth.token_client import TokenClient
from fhir_backend_auth.config import Settings
from fhir_backend_auth.http_logging import logger as http_logging_logger

TOKEN_ENDPOINT = "https://epic.example.com/oauth2/token"


@pytest.fixture
def settings(tmp_key_dir):
    return Settings(
        oauth_client_id="test-client-id",
        upstream_token_url=TOKEN_ENDPOINT,
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


def _make_token_client(settings, jwk_manager, fake_redis, transport=None):
    kid = jwk_manager.get_kid()
    oauth_client = create_oauth_client(
        settings,
        jwk_manager.get_private_key_pem(),
        TOKEN_ENDPOINT,
        kid,
        transport=transport,
    )
    return TokenClient(
        settings,
        jwk_manager,
        fake_redis,
        token_endpoint=TOKEN_ENDPOINT,
        oauth_client=oauth_client,
    )


@pytest.mark.asyncio
async def test_token_request_uses_rs384_private_key_jwt(
    settings, jwk_manager, fake_redis
):
    captured = {}

    async def handler(request):
        captured["body"] = request.content.decode()
        return httpx.Response(
            200,
            json={"access_token": "fresh-token", "expires_in": 3600},
        )

    transport = httpx.MockTransport(handler)
    client = _make_token_client(settings, jwk_manager, fake_redis, transport)

    token = await client.get_access_token()
    assert token == "fresh-token"

    form = parse_qs(captured["body"])
    assert form["grant_type"] == ["client_credentials"]
    assert form["client_assertion_type"] == [
        "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
    ]
    assertion = form["client_assertion"][0]
    public_pem = jwk_manager.get_public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    decoded = jwt.decode(assertion, public_pem)
    header = decoded.header

    assert header["alg"] == JWT_ALGORITHM
    assert header["kid"] == jwk_manager.get_kid()
    assert decoded["iss"] == settings.oauth_client_id
    assert decoded["sub"] == settings.oauth_client_id
    assert decoded["aud"] == TOKEN_ENDPOINT
    assert decoded["exp"] - decoded["iat"] == settings.client_assertion_expires_seconds
    assert "jti" in decoded

    await client.close()


@pytest.mark.asyncio
async def test_token_request_does_not_log_on_success(
    settings, jwk_manager, fake_redis, caplog
):
    async def handler(request):
        return httpx.Response(
            200,
            json={"access_token": "fresh-token", "expires_in": 3600},
        )

    transport = httpx.MockTransport(handler)
    client = _make_token_client(settings, jwk_manager, fake_redis, transport)

    with caplog.at_level(logging.INFO, logger=http_logging_logger.name):
        token = await client.get_access_token()

    assert token == "fresh-token"
    assert "Token request:" not in caplog.text
    assert "Token response:" not in caplog.text

    await client.close()


@pytest.mark.asyncio
async def test_token_request_logs_request_and_response_on_error(
    settings, jwk_manager, fake_redis, caplog
):
    async def handler(request):
        return httpx.Response(
            400,
            json={"error": "invalid_client", "error_description": "bad jwt"},
            headers={"Content-Type": "application/json"},
        )

    transport = httpx.MockTransport(handler)
    client = _make_token_client(settings, jwk_manager, fake_redis, transport)

    with caplog.at_level(logging.INFO, logger=http_logging_logger.name):
        with pytest.raises(Exception):
            await client.get_access_token()

    log_text = caplog.text
    assert "Token request: POST" in log_text
    assert TOKEN_ENDPOINT in log_text
    assert "grant_type=client_credentials" in log_text
    assert "Token response: 400" in log_text
    assert "invalid_client" in log_text

    await client.close()


@pytest.mark.asyncio
async def test_cache_hit_skips_token_request(settings, jwk_manager, fake_redis):
    expires_at = int(time.time()) + 3600
    await fake_redis.set(
        settings.token_cache_key,
        json.dumps({"access_token": "cached-token", "expires_at": expires_at}),
    )

    transport = httpx.MockTransport(
        lambda request: pytest.fail("token endpoint should not be called")
    )
    client = _make_token_client(settings, jwk_manager, fake_redis, transport)

    token = await client.get_access_token()
    assert token == "cached-token"

    await client.close()


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
    client = _make_token_client(settings, jwk_manager, fake_redis, transport)

    token = await client.get_access_token()
    assert token == "fresh-token"

    cached = await fake_redis.get(settings.token_cache_key)
    payload = json.loads(cached)
    assert payload["access_token"] == "fresh-token"
    assert payload["expires_at"] > int(time.time())

    await client.close()


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
    client = _make_token_client(settings, jwk_manager, fake_redis, transport)

    token = await client.get_access_token()
    assert token == "new-token"

    await client.close()
