"""JWK Set management for OAuth client authentication.

Handles generation, storage, and retrieval of RSA keys for
private_key_jwt client authentication (RFC7523).
"""

import hashlib
import json
import os
from pathlib import Path

from authlib.jose import JsonWebKey
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

JWT_ALGORITHM = "RS384"


class JWKManager:
    """Manages RSA keys for OAuth client authentication."""

    def __init__(self, key_dir: str):
        self.key_dir = key_dir
        self._ensure_key_dir()
        self._private_key = None
        self._public_key = None
        self._jwk_dict = None

    def _ensure_key_dir(self) -> None:
        Path(self.key_dir).mkdir(parents=True, exist_ok=True)

    def _get_key_paths(self) -> dict[str, str]:
        return {
            "private": os.path.join(self.key_dir, "private_key.pem"),
            "public": os.path.join(self.key_dir, "public_key.pem"),
        }

    def generate_keys(self, key_size: int = 2048) -> None:
        """Generate a new RSA keypair and persist it to disk."""
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=key_size,
        )
        key_paths = self._get_key_paths()

        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        with open(key_paths["private"], "wb") as f:
            f.write(private_pem)

        public_key = private_key.public_key()
        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        with open(key_paths["public"], "wb") as f:
            f.write(public_pem)

        self._private_key = private_key
        self._public_key = public_key
        self._jwk_dict = None

    def load_keys(self) -> None:
        """Load an existing RSA keypair from disk."""
        key_paths = self._get_key_paths()
        if not os.path.exists(key_paths["private"]):
            raise FileNotFoundError(
                f"Private key not found at {key_paths['private']}"
            )

        with open(key_paths["private"], "rb") as f:
            self._private_key = serialization.load_pem_private_key(
                f.read(),
                password=None,
            )

        if os.path.exists(key_paths["public"]):
            with open(key_paths["public"], "rb") as f:
                self._public_key = serialization.load_pem_public_key(f.read())
        else:
            self._public_key = self._private_key.public_key()

        self._jwk_dict = None

    def get_or_create_keys(self) -> None:
        """Load keys from disk, generating a new keypair if none exists."""
        key_paths = self._get_key_paths()
        if os.path.exists(key_paths["private"]):
            self.load_keys()
        else:
            self.generate_keys()

    def get_private_key(self):
        if self._private_key is None:
            self.get_or_create_keys()
        return self._private_key

    def get_private_key_pem(self) -> str:
        private_key = self.get_private_key()
        return private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")

    def get_public_key(self):
        if self._public_key is None:
            self.get_or_create_keys()
        return self._public_key

    def get_jwk_dict(self) -> dict:
        if self._jwk_dict is None:
            public_key = self.get_public_key()
            public_pem = public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            key = JsonWebKey.import_key(
                public_pem,
                {"kty": "RSA", "alg": JWT_ALGORITHM, "use": "sig"},
            )
            self._jwk_dict = key.as_dict(is_private=False)
        return self._jwk_dict

    def get_kid(self) -> str:
        """Return a stable key ID derived from the public JWK."""
        jwk_dict = self.get_jwk_dict()
        if "kid" not in jwk_dict:
            key_str = json.dumps(jwk_dict, sort_keys=True)
            jwk_dict["kid"] = hashlib.sha256(
                key_str.encode()
            ).hexdigest()[:16]
        return jwk_dict["kid"]

    def get_jwks(self) -> dict:
        """Return the public key set for the /.well-known/jwks.json endpoint."""
        jwk_dict = dict(self.get_jwk_dict())
        jwk_dict["kid"] = self.get_kid()
        jwk_dict["alg"] = JWT_ALGORITHM
        jwk_dict["use"] = "sig"
        return {"keys": [jwk_dict]}
