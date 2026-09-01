# Epic FHIR Backend Auth Proxy

FastAPI service that proxies `/fhir/` requests to Epic using Backend Services OAuth (`client_credentials` + `private_key_jwt`), exposes `/.well-known/jwks.json` for Epic registration, and caches access tokens in Redis.

## Setup

1. Copy the example environment file and configure Epic credentials:

```bash
cp fhir_backend_auth.env.default .env
```

2. Register the JWKS URL with Epic App Orchard:

```
{PREFERRED_URL_SCHEME}://{SERVER_NAME}/.well-known/jwks.json
```

3. Start with Docker Compose:

```bash
docker compose up --build
```

Or run locally:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.dev.txt
pip install -e .
uvicorn fhir_backend_auth.app:create_app --factory --reload
```

## Configuration

| Variable | Description |
|----------|-------------|
| `SERVER_NAME` | External hostname for JWKS URL |
| `PREFERRED_URL_SCHEME` | `http` or `https` |
| `OAUTH_CLIENT_ID` | OAuth client ID (from Epic App Orchard) |
| `UPSTREAM_TOKEN_URL` | Upstream token endpoint |
| `UPSTREAM_FHIR_URL` | Upstream FHIR base URL |
| `OAUTH_SCOPES` | Space-separated system scopes |
| `JWK_KEY_DIR` | Directory for RSA keypair storage |
| `REDIS_URL` | Redis connection URL |
| `TOKEN_CACHE_KEY` | Redis key for cached access token |
| `TOKEN_CACHE_BUFFER_SECONDS` | Refresh token before expiry |

## Usage

```bash
curl http://localhost:8000/fhir/metadata
curl http://localhost:8000/.well-known/jwks.json
curl http://localhost:8000/health
```

## Tests

```bash
pytest
```

## Notes

- Epic Backend Services JWT assertions use **RS384**.
- RSA keys are generated on first startup if not present in `JWK_KEY_DIR`.
- `/fhir/` is intended for trusted internal callers; the service owns Epic authentication.
