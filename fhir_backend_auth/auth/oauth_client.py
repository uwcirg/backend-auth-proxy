"""Authlib OAuth2 client factory for Backend Services authentication."""

from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.oauth2.rfc7523.assertion import private_key_jwt_sign
from authlib.oauth2.rfc7523.auth import PrivateKeyJWT as AuthlibPrivateKeyJWT
from httpx import AsyncBaseTransport
from joserfc.jwk import ECKey, OKPKey, RSAKey

from fhir_backend_auth.auth.jwk_manager import JWT_ALGORITHM
from fhir_backend_auth.config import Settings
from fhir_backend_auth.http_logging import LoggingTransport


class PrivateKeyJWT(AuthlibPrivateKeyJWT):
    """PrivateKeyJWT client auth with configurable client assertion lifetime."""

    def __init__(
        self,
        token_endpoint=None,
        expires_in: int = 300,
        claims=None,
        headers=None,
        alg=None,
    ):
        super().__init__(
            token_endpoint,
            claims=claims,
            headers=headers,
            alg=alg,
        )
        self._expires_in = expires_in

    def sign(self, auth, token_endpoint):
        if isinstance(auth.client_secret, (RSAKey, ECKey, OKPKey)):
            key = auth.client_secret
        else:
            key = RSAKey.import_key(auth.client_secret)
        return private_key_jwt_sign(
            key,
            client_id=auth.client_id,
            token_endpoint=token_endpoint,
            claims=self.claims,
            header=self.headers,
            alg=self.alg,
            expires_in=self._expires_in,
        )


def create_oauth_client(
    settings: Settings,
    private_key_pem: str,
    token_endpoint: str,
    kid: str,
    transport: AsyncBaseTransport | None = None,
) -> AsyncOAuth2Client:
    """Create an AsyncOAuth2Client for private_key_jwt Backend Services auth.

    Registers a logging transport and includes the JWKS key ID in client assertions.
    """
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
            expires_in=settings.client_assertion_expires_seconds,
        )
    )
    return client
