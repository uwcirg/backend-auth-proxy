"""FHIR proxy routes."""

import logging
from urllib.parse import urljoin

import httpx
from fastapi import APIRouter, Request, Response

from fhir_backend_auth.auth.token_client import TokenClient
from fhir_backend_auth.config import Settings

logger = logging.getLogger(__name__)

router = APIRouter()

SUPPORTED_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH"]
FORWARD_REQUEST_HEADERS = {"content-type", "accept", "prefer"}
FORWARD_RESPONSE_HEADERS = {
    "content-type",
    "location",
    "etag",
    "last-modified",
}


def _headers_for_log(headers: httpx.Headers | dict[str, str]) -> dict[str, str]:
    return {name.lower(): value for name, value in headers.items()}


def _build_upstream_request_url(upstream_url: str, params: httpx.QueryParams) -> str:
    return str(httpx.URL(upstream_url).copy_merge_params(params=params))


def _log_upstream_request(
    method: str,
    url: str,
    headers: dict[str, str],
) -> None:
    logger.info(
        "Upstream request: %s %s headers=%s",
        method,
        url,
        _headers_for_log(headers),
    )


def _log_upstream_response(response: httpx.Response) -> None:
    logger.info(
        "Upstream response: %s headers=%s",
        response.status_code,
        _headers_for_log(response.headers),
    )


@router.api_route(
    "/",
    methods=SUPPORTED_METHODS,
)
@router.api_route(
    "/{path:path}",
    methods=SUPPORTED_METHODS,
)
async def proxy_fhir(request: Request, path: str = "") -> Response:
    """Forward FHIR requests to Epic with a cached Backend Services token."""
    settings: Settings = request.app.state.settings
    token_client: TokenClient = request.app.state.token_client
    http_client: httpx.AsyncClient = request.app.state.http_client

    upstream_path = path.strip("/")
    base = settings.upstream_fhir_url.rstrip("/") + "/"
    upstream_url = urljoin(base, upstream_path) if upstream_path else base.rstrip("/")

    body = await request.body()
    headers = {}
    for name, value in request.headers.items():
        if name.lower() in FORWARD_REQUEST_HEADERS:
            headers[name] = value

    async def forward(access_token: str) -> httpx.Response:
        headers["Authorization"] = f"Bearer {access_token}"
        request_url = _build_upstream_request_url(
            upstream_url,
            request.query_params,
        )
        _log_upstream_request(request.method, request_url, headers)
        response = await http_client.request(
            method=request.method,
            url=upstream_url,
            params=request.query_params,
            content=body if body else None,
            headers=headers,
        )
        _log_upstream_response(response)
        return response

    access_token = await token_client.get_access_token()
    upstream_response = await forward(access_token)

    if upstream_response.status_code == 401:
        logger.info("Upstream 401; invalidating cached token and retrying once")
        await token_client.invalidate_token()
        access_token = await token_client.get_access_token()
        upstream_response = await forward(access_token)

    response_headers = {}
    for name, value in upstream_response.headers.items():
        if name.lower() in FORWARD_RESPONSE_HEADERS:
            response_headers[name] = value

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=response_headers,
        media_type=upstream_response.headers.get("content-type"),
    )
