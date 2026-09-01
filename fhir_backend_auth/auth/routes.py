"""Authentication-related routes."""

from fastapi import APIRouter, Request

from fhir_backend_auth.auth.jwk_manager import JWKManager

router = APIRouter()


@router.get("/.well-known/jwks.json")
async def jwks(request: Request) -> dict:
    """JWK Set endpoint for advertising public keys to Epic."""
    jwk_manager: JWKManager = request.app.state.jwk_manager
    return jwk_manager.get_jwks()
