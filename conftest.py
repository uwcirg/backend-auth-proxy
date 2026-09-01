import os

import pytest


@pytest.fixture(autouse=True)
def test_env(tmp_key_dir, monkeypatch):
    monkeypatch.setenv("OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("JWK_KEY_DIR", tmp_key_dir)
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/15")
    monkeypatch.setenv("SERVER_NAME", "localhost:8000")
    monkeypatch.setenv("UPSTREAM_TOKEN_URL", "https://epic.example.com/oauth2/token")
    monkeypatch.setenv(
        "UPSTREAM_FHIR_URL",
        "https://epic.example.com/api/FHIR/R4",
    )


@pytest.fixture
def tmp_key_dir(tmp_path):
    return str(tmp_path / "jwks")
