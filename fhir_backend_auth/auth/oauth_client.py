"""Authlib OAuth2 client factory for Backend Services authentication."""

from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.oauth2.rfc7523 import PrivateKeyJWT
from httpx import AsyncBaseTransport

from fhir_backend_auth.auth.jwk_manager import JWT_ALGORITHM
from fhir_backend_auth.config import Settings
from fhir_backend_auth.http_logging import LoggingTransport


def create_oauth_client(
    settings: Settings,
    private_key_pem: str,
    token_endpoint: str,
    kid: str,
    transport: AsyncBaseTransport | None = None,
) -> AsyncOAuth2Client:
    """Create an AsyncOAuth2Client configured for private_key_jwt."""
    client_kwargs = {
        "transport": LoggingTransport(transport, label="Token"),
    }

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
