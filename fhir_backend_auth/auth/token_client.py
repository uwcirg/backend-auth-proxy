"""Epic Backend Services OAuth token client with Redis caching."""

import asyncio
import json
import logging
import time
import uuid
from typing import Any

import httpx
from jose import jwt
from redis.asyncio import Redis

from fhir_backend_auth.auth.jwk_manager import JWT_ALGORITHM, JWKManager
from fhir_backend_auth.config import Settings

logger = logging.getLogger(__name__)

REFRESH_LOCK_KEY_SUFFIX = ":refresh_lock"
REFRESH_LOCK_TTL_SECONDS = 30


class TokenClient:
    """Acquire and cache Epic Backend Services access tokens."""

    def __init__(
        self,
        settings: Settings,
        jwk_manager: JWKManager,
        redis: Redis,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.settings = settings
        self.jwk_manager = jwk_manager
        self.redis = redis
        self._http_client = http_client
        self._owns_client = http_client is None

    async def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        return self._http_client

    async def close(self) -> None:
        if self._owns_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    def _build_client_assertion(self) -> str:
        now = int(time.time())
        claims = {
            "iss": self.settings.oauth_client_id,
            "sub": self.settings.oauth_client_id,
            "aud": self.settings.upstream_token_url,
            "jti": str(uuid.uuid4()),
            "exp": now + 240,
            "nbf": now,
            "iat": now,
        }
        private_key_pem = self.jwk_manager.get_private_key_pem()
        return jwt.encode(
            claims,
            private_key_pem,
            algorithm=JWT_ALGORITHM,
        )

    async def _read_cached_token(self) -> str | None:
        cached = await self.redis.get(self.settings.token_cache_key)
        if not cached:
            return None

        try:
            payload = json.loads(cached)
        except json.JSONDecodeError:
            await self.redis.delete(self.settings.token_cache_key)
            return None

        expires_at = payload.get("expires_at", 0)
        buffer = self.settings.token_cache_buffer_seconds
        if time.time() >= expires_at - buffer:
            return None

        access_token = payload.get("access_token")
        if not access_token:
            return None

        return access_token

    async def _cache_token(self, token_response: dict[str, Any]) -> str:
        access_token = token_response["access_token"]
        expires_in = int(token_response.get("expires_in", 3600))
        buffer = self.settings.token_cache_buffer_seconds
        ttl = max(expires_in - buffer, 1)
        expires_at = int(time.time()) + expires_in

        payload = json.dumps({
            "access_token": access_token,
            "expires_at": expires_at,
        })
        await self.redis.set(
            self.settings.token_cache_key,
            payload,
            ex=ttl,
        )
        return access_token

    async def invalidate_token(self) -> None:
        await self.redis.delete(self.settings.token_cache_key)

    async def _fetch_token(self) -> str:
        client = await self._get_http_client()
        assertion = self._build_client_assertion()
        response = await client.post(
            self.settings.upstream_token_url,
            data={
                "grant_type": "client_credentials",
                "client_assertion_type": (
                    "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
                ),
                "client_assertion": assertion,
                "scope": self.settings.oauth_scopes,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        return await self._cache_token(response.json())

    async def get_access_token(self) -> str:
        cached = await self._read_cached_token()
        if cached:
            return cached

        lock_key = f"{self.settings.token_cache_key}{REFRESH_LOCK_KEY_SUFFIX}"
        acquired = await self.redis.set(
            lock_key,
            "1",
            nx=True,
            ex=REFRESH_LOCK_TTL_SECONDS,
        )

        if not acquired:
            for _ in range(20):
                await asyncio.sleep(0.25)
                cached = await self._read_cached_token()
                if cached:
                    return cached
            logger.warning("Timed out waiting for token refresh lock")

        try:
            cached = await self._read_cached_token()
            if cached:
                return cached
            return await self._fetch_token()
        finally:
            await self.redis.delete(lock_key)
