"""FastAPI application factory."""

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from fhir_backend_auth.api.fhir import router as fhir_router
from fhir_backend_auth.auth.jwk_manager import JWKManager
from fhir_backend_auth.auth.routes import router as auth_router
from fhir_backend_auth.auth.token_client import TokenClient
from fhir_backend_auth.config import Settings, get_settings
from fhir_backend_auth.extensions import close_redis, get_redis, init_redis

logger = logging.getLogger(__name__)


def _configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    jwk_manager: JWKManager = app.state.jwk_manager

    jwk_manager.get_or_create_keys()
    await init_redis(settings.redis_url)

    http_client = httpx.AsyncClient(timeout=60.0)
    token_client = TokenClient(
        settings=settings,
        jwk_manager=jwk_manager,
        redis=get_redis(),
        http_client=http_client,
    )

    app.state.http_client = http_client
    app.state.token_client = token_client

    logger.info("Application startup complete; JWKS URL: %s", settings.jwks_url)
    yield

    await token_client.close()
    await http_client.aclose()
    await close_redis()
    logger.info("Application shutdown complete")


def create_app(testing: bool = False) -> FastAPI:
    """Application factory."""
    get_settings.cache_clear()
    settings = Settings(testing=testing)
    _configure_logging(settings)

    jwk_manager = JWKManager(key_dir=settings.jwk_key_dir)

    app = FastAPI(
        title="Epic FHIR Backend Auth Proxy",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.jwk_manager = jwk_manager

    app.include_router(auth_router)
    app.include_router(fhir_router, prefix="/fhir")

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def health_ready() -> dict:
        from fhir_backend_auth.extensions import redis_client

        if redis_client is None:
            return {"status": "not_ready"}
        await redis_client.ping()
        return {"status": "ready"}

    return app
