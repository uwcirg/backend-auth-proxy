import logging

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

import fhir_backend_auth.extensions as ext
from fhir_backend_auth.api import fhir as fhir_api
from fhir_backend_auth.app import create_app
from fhir_backend_auth.auth.oauth_client import create_oauth_client


@pytest.fixture
async def app_client(tmp_key_dir, monkeypatch):
    monkeypatch.setenv("OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("JWK_KEY_DIR", tmp_key_dir)

    fake_redis = __import__("fakeredis.aioredis").aioredis.FakeRedis(
        decode_responses=True
    )

    async def fake_init_redis(_url):
        ext.redis_client = fake_redis
        return fake_redis

    monkeypatch.setattr("fhir_backend_auth.app.init_redis", fake_init_redis)

    app = create_app(testing=True)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            yield client, app, fake_redis

    ext.redis_client = None
    await fake_redis.aclose()


@pytest.mark.asyncio
async def test_jwks_endpoint(app_client):
    client, app, _ = app_client
    response = await client.get("/.well-known/jwks.json")
    assert response.status_code == 200
    body = response.json()
    assert "keys" in body
    assert len(body["keys"]) == 1


@pytest.mark.asyncio
async def test_fhir_proxy_forwards_request(app_client):
    client, app, fake_redis = app_client
    settings = app.state.settings

    await fake_redis.set(
        settings.token_cache_key,
        '{"access_token": "proxy-token", "expires_at": 9999999999}',
    )

    captured = {}

    async def upstream_handler(request):
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(
            200,
            json={"resourceType": "CapabilityStatement"},
            headers={"Content-Type": "application/fhir+json"},
        )

    mock_transport = httpx.MockTransport(upstream_handler)
    mock_http_client = httpx.AsyncClient(transport=mock_transport)
    app.state.http_client = mock_http_client

    response = await client.get("/fhir/metadata")
    assert response.status_code == 200
    assert captured["url"] == "https://epic.example.com/api/FHIR/R4/metadata"
    assert captured["auth"] == "Bearer proxy-token"

    await mock_http_client.aclose()


@pytest.mark.asyncio
async def test_fhir_proxy_logs_upstream_request_and_response_headers(
    app_client, caplog
):
    client, app, fake_redis = app_client
    settings = app.state.settings

    await fake_redis.set(
        settings.token_cache_key,
        '{"access_token": "proxy-token", "expires_at": 9999999999}',
    )

    async def upstream_handler(request):
        return httpx.Response(
            200,
            json={"resourceType": "CapabilityStatement"},
            headers={"Content-Type": "application/fhir+json"},
        )

    mock_transport = httpx.MockTransport(upstream_handler)
    mock_http_client = httpx.AsyncClient(transport=mock_transport)
    app.state.http_client = mock_http_client

    upstream_url = f"{settings.upstream_fhir_url.rstrip('/')}/metadata"
    with caplog.at_level(logging.INFO, logger=fhir_api.logger.name):
        response = await client.get("/fhir/metadata")

    assert response.status_code == 200
    log_text = caplog.text
    assert "Upstream request: GET" in log_text
    assert upstream_url in log_text
    assert "'authorization': 'Bearer proxy-token'" in log_text
    assert "Upstream response: 200" in log_text
    assert "'content-type': 'application/fhir+json'" in log_text

    await mock_http_client.aclose()


@pytest.mark.asyncio
async def test_fhir_proxy_retries_on_401(app_client):
    client, app, fake_redis = app_client
    settings = app.state.settings

    await fake_redis.set(
        settings.token_cache_key,
        '{"access_token": "stale-token", "expires_at": 9999999999}',
    )

    calls = {"count": 0}

    async def token_handler(request):
        return httpx.Response(
            200,
            json={"access_token": "fresh-token", "expires_in": 3600},
        )

    async def fhir_handler(request):
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(401, json={"error": "invalid_token"})
        return httpx.Response(200, json={"resourceType": "Patient"})

    class FhirTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            return await fhir_handler(request)

    mock_http_client = httpx.AsyncClient(transport=FhirTransport())
    app.state.http_client = mock_http_client

    token_transport = httpx.MockTransport(
        lambda request: token_handler(request)
    )
    app.state.token_client._oauth_client = create_oauth_client(
        settings,
        app.state.jwk_manager.get_private_key_pem(),
        settings.upstream_token_url,
        app.state.jwk_manager.get_kid(),
        transport=token_transport,
    )
    app.state.token_client._owns_client = True

    response = await client.get("/fhir/Patient/123")
    assert response.status_code == 200
    assert calls["count"] == 2

    await mock_http_client.aclose()
