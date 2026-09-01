"""Authlib OAuth2 client factory for Backend Services authentication."""

import json
import time

from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.oauth2.rfc7523 import PrivateKeyJWT
from httpx import AsyncBaseTransport

from fhir_backend_auth.auth.jwk_manager import JWT_ALGORITHM
from fhir_backend_auth.config import Settings

DEBUG_LOG_PATH = "/tmp/debug-d7bbfe.log"


def _debug_log(location: str, message: str, data: dict, hypothesis_id: str) -> None:
    # region agent log
    try:
        with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as log_file:
            log_file.write(json.dumps({
                "sessionId": "d7bbfe",
                "runId": "post-fix",
                "hypothesisId": hypothesis_id,
                "location": location,
                "message": message,
                "data": data,
                "timestamp": int(time.time() * 1000),
            }) + "\n")
    except OSError:
        pass
    # endregion


def create_oauth_client(
    settings: Settings,
    private_key_pem: str,
    token_endpoint: str,
    kid: str,
    transport: AsyncBaseTransport | None = None,
) -> AsyncOAuth2Client:
    """Create an AsyncOAuth2Client configured for private_key_jwt."""
    client_kwargs = {}
    if transport is not None:
        client_kwargs["transport"] = transport

    _debug_log(
        "oauth_client.py:create_oauth_client",
        "Creating OAuth client with kid header",
        {"token_endpoint": token_endpoint, "kid": kid},
        "H1",
    )

    client = AsyncOAuth2Client(
        client_id=settings.oauth_client_id,
        client_secret=private_key_pem,
        token_endpoint_auth_method="private_key_jwt",
        **client_kwargs,
    )
    client.register_client_auth_method(
        PrivateKeyJWT(
            token_endpoint,
            alg=JWT_ALGORITHM,
            headers={"kid": kid},
        )
    )
    return client
