# Epic FHIR Backend Auth Proxy

FastAPI service that proxies `/fhir/` requests to Epic using Backend Services OAuth (`client_credentials` + `private_key_jwt`), exposes `/.well-known/jwks.json` for Epic registration, and caches access tokens in Redis.

## Setup

1. Copy the example environment file and configure Epic credentials:

```bash
cp fhirbackendauth.env.default fhirbackendauth.env
```

2. Register the JWKS URL with Epic App Orchard:

```
{PREFERRED_URL_SCHEME}://{SERVER_NAME}/.well-known/jwks.json
```

3. Start with Docker Compose:

```bash
docker compose up --build
```

For local development with a checkout mount and auto-reload:

```bash
COMPOSE_FILE=docker-compose.yaml:docker-compose.dev.yaml docker compose up --build
```

Or run locally without Docker:

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
| `UPSTREAM_FHIR_URL` | Upstream FHIR base URL (used for OAuth discovery) |
| `UPSTREAM_TOKEN_URL` | Optional override for token endpoint (skips discovery) |
| `OAUTH_SCOPES` | Space-separated system scopes |
| `CLIENT_ASSERTION_EXPIRES_SECONDS` | Client assertion JWT lifetime (default 300; Epic max 5 min) |
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

## embedhw-environments

This service is designed to deploy as a Traefik-routed service in
[embedhw-environments](https://github.com/uwcirg/embedhw-environments).
See [docs/embedhw-environments.md](docs/embedhw-environments.md) for compose
snippets, env file templates, and deployment notes.

Image: `ghcr.io/uwcirg/fhir-backend-auth`

## Notes

- OAuth token acquisition uses [authlib](https://docs.authlib.org/) (`private_key_jwt` / RFC7523).
- Token endpoint is discovered from `{UPSTREAM_FHIR_URL}/.well-known/smart-configuration`, falling back to `openid-configuration`.
- Epic Backend Services JWT assertions use **RS384**.
- RSA keys are generated on first startup if not present in `JWK_KEY_DIR`.
- `/fhir/` is intended for trusted internal callers; the service owns Epic authentication.
