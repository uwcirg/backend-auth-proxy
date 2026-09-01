"""Shared HTTP request/response logging helpers."""

import logging

import httpx

logger = logging.getLogger(__name__)


def headers_for_log(headers: httpx.Headers | dict[str, str]) -> dict[str, str]:
    return {name.lower(): value for name, value in headers.items()}


def body_for_log(body: bytes | str | None, limit: int = 2000) -> str:
    if body is None:
        return ""
    if isinstance(body, bytes):
        text = body.decode(errors="replace")
    else:
        text = body
    if len(text) > limit:
        return f"{text[:limit]}... (truncated)"
    return text


def log_http_request(
    label: str,
    method: str,
    url: str,
    headers: httpx.Headers | dict[str, str],
    body: bytes | str | None = None,
) -> None:
    logger.info(
        "%s request: %s %s headers=%s body=%s",
        label,
        method,
        url,
        headers_for_log(headers),
        body_for_log(body),
    )


def log_http_response(
    label: str,
    response: httpx.Response,
    body: bytes | None = None,
) -> None:
    logger.info(
        "%s response: %s headers=%s body=%s",
        label,
        response.status_code,
        headers_for_log(response.headers),
        body_for_log(body),
    )


class LoggingTransport(httpx.AsyncBaseTransport):
    """Log HTTP exchanges, then delegate to an inner transport."""

    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        label: str = "HTTP",
    ):
        self._transport = transport or httpx.AsyncHTTPTransport()
        self._label = label

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        log_http_request(
            self._label,
            request.method,
            str(request.url),
            request.headers,
            request.content,
        )
        response = await self._transport.handle_async_request(request)
        body = await response.aread()
        log_http_response(
            self._label,
            response,
            body,
        )
        return httpx.Response(
            status_code=response.status_code,
            headers=response.headers,
            content=body,
            request=request,
        )
