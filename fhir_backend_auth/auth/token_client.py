"""Epic Backend Services OAuth token client with Redis caching."""

import asyncio
import json
import logging
import time
from typing import Any

from authlib.integrations.httpx_client import AsyncOAuth2Client
from redis.asyncio import Redis

from fhir_backend_auth.auth.jwk_manager import JWKManager
from fhir_backend_auth.auth.oauth_client import create_oauth_client
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
        token_endpoint: str,
        oauth_client: AsyncOAuth2Client | None = None,
    ):
        self.settings = settings
        self.jwk_manager = jwk_manager
        self.redis = redis
        self._token_endpoint = token_endpoint
        self._oauth_client = oauth_client or create_oauth_client(
            settings,
            jwk_manager.get_private_key_pem(),
            token_endpoint,
        )
        self._owns_client = oauth_client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._oauth_client.aclose()

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
        token = await self._oauth_client.fetch_token(
            self._token_endpoint,
            grant_type="client_credentials",
            scope=self.settings.oauth_scopes,
        )
        return await self._cache_token(token)

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
