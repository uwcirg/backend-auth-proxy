import json
import time

import pytest

from fhir_backend_auth.auth.jwk_manager import JWT_ALGORITHM, JWKManager


def test_generate_and_load_keys(tmp_key_dir):
    manager = JWKManager(tmp_key_dir)
    manager.generate_keys()

    reloaded = JWKManager(tmp_key_dir)
    reloaded.load_keys()

    assert reloaded.get_private_key_pem()
    assert reloaded.get_public_key()


def test_get_or_create_keys_generates_when_missing(tmp_key_dir):
    manager = JWKManager(tmp_key_dir)
    manager.get_or_create_keys()
    assert manager.get_private_key_pem()


def test_jwks_shape_and_stable_kid(tmp_key_dir):
    manager = JWKManager(tmp_key_dir)
    manager.generate_keys()

    jwks1 = manager.get_jwks()
    jwks2 = manager.get_jwks()

    assert "keys" in jwks1
    assert len(jwks1["keys"]) == 1

    key = jwks1["keys"][0]
    assert key["alg"] == JWT_ALGORITHM
    assert key["use"] == "sig"
    assert "kid" in key
    assert jwks1["keys"][0]["kid"] == jwks2["keys"][0]["kid"]
