# embedhw-environments integration

This document describes how to add `fhirbackendauth` as a service in
[embedhw-environments](https://github.com/uwcirg/embedhw-environments).

## Image

Published to GitHub Container Registry on push:

```
ghcr.io/uwcirg/fhir-backend-auth:${FHIRBACKENDAUTH_IMAGE_TAG:-latest}
```

## base/docker-compose.yaml

Add the following service definition:

```yaml
  fhirbackendauth:
    image: ghcr.io/uwcirg/fhir-backend-auth:${FHIRBACKENDAUTH_IMAGE_TAG:-latest}
    environment:
      SERVER_NAME: fhir-backend-auth.${BASE_DOMAIN}
      PREFERRED_URL_SCHEME: https
      REDIS_URL: redis://redis:6379/2
      JWK_KEY_DIR: /data/jwks
      PYTHONUNBUFFERED: "1"
    labels:
      - traefik.enable=true
      - traefik.http.routers.fhirbackendauth-${COMPOSE_PROJECT_NAME}.rule=Host(`fhir-backend-auth.${BASE_DOMAIN}`)
      - traefik.http.routers.fhirbackendauth-${COMPOSE_PROJECT_NAME}.entrypoints=websecure
      - traefik.http.routers.fhirbackendauth-${COMPOSE_PROJECT_NAME}.tls.certresolver=letsencrypt
    networks:
      - ingress
      - internal
    depends_on:
      - redis
    volumes:
      - jwk-keys:/data/jwks
```

Add the volume to the `volumes:` block:

```yaml
  jwk-keys: {}
```

Redis DB `/2` avoids collision with confidentialbackend (`/0` sessions, `/1` request cache).

## dev/docker-compose.yaml and prod/docker-compose.yaml

Extend the base service and attach secrets:

```yaml
  fhirbackendauth:
    extends:
      file: ../base/docker-compose.yaml
      service: fhirbackendauth
    env_file:
      - fhirbackendauth.env
```

## dev/fhirbackendauth.env.default and prod/fhirbackendauth.env.default

Container-only secrets (copy to `fhirbackendauth.env`):

```bash
# Example docker-compose environment file
# Copy to fhirbackendauth.env and modify as necessary

OAUTH_CLIENT_ID=
UPSTREAM_TOKEN_URL=https://fhir.epic.com/interconnect-fhir-oauth/oauth2/token
UPSTREAM_FHIR_URL=https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4
OAUTH_SCOPES=system/Patient.read system/Observation.read
TOKEN_CACHE_KEY=upstream:access_token
TOKEN_CACHE_BUFFER_SECONDS=60
LOG_LEVEL=INFO
```

Non-secret values (`SERVER_NAME`, `PREFERRED_URL_SCHEME`, `REDIS_URL`, `JWK_KEY_DIR`)
belong in the compose `environment:` block, not the env file.

## default.env entries

Add to `dev/default.env` and `prod/default.env`:

```bash
FHIRBACKENDAUTH_IMAGE_TAG=latest
# optional, for local dev override:
# FHIRBACKENDAUTH_CHECKOUT_DIR=/path/to/fhir-backend-auth
```

## dev/docker-compose.dev.fhirbackendauth.yaml (optional)

For local development with a checkout mount:

```yaml
# docker-compose development override for fhirbackendauth
services:
  fhirbackendauth:
    command: >
      uvicorn fhir_backend_auth.app:create_app
      --factory --host 0.0.0.0 --port $${PORT:-8000} --reload
    volumes:
      - ${FHIRBACKENDAUTH_CHECKOUT_DIR}/:/opt/app
```

Enable via `COMPOSE_FILE` in `.env`:

```bash
COMPOSE_FILE=docker-compose.yaml:docker-compose.dev.fhirbackendauth.yaml
```

## Epic App Orchard

Register the JWKS URL (must be reachable at server root):

```
https://fhir-backend-auth.${BASE_DOMAIN}/.well-known/jwks.json
```

## Internal callers

Other services on the `internal` network can reach the proxy at:

```
http://fhirbackendauth:8000/fhir/
```

## Optional prod basicauth

To require a password on the public route (similar to `fishmouth-auth`), add
Traefik middleware labels and a password hash in `.env`:

```yaml
      - traefik.http.routers.fhirbackendauth-${COMPOSE_PROJECT_NAME}.middlewares=fhirbackendauth-auth-${COMPOSE_PROJECT_NAME}
      - traefik.http.middlewares.fhirbackendauth-auth-${COMPOSE_PROJECT_NAME}.basicauth.users=admin:${FHIRBACKENDAUTH_PASSWORD_HASH}
```

Generate the hash:

```bash
htpasswd -nbB admin "$PASSWORD" | cut -d ':' -f2
```

## Deploy

From `dev/` or `prod/`:

```bash
docker compose pull
docker compose up --detach
```
