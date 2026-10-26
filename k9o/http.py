"""
HTTP client for the k9o SDK — httpx-based; sync + async.

Python idiomatic shape: returns Envelope on 2xx;
raises KError on non-2xx + transport failures + malformed envelopes.
Field-name translation at the boundary: wire camelCase JSON ↔ Python
snake_case attributes on dataclasses (Meta accessor sugar).
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, TypeVar

import httpx

from .envelope import Envelope, meta_from_wire
from .errors import KError, kerror_from_wire
from .region import resolve_regional_origin, resolve_regional_origin_async

T = TypeVar("T")

# Retry — idempotent methods only, transient failures only.
_RETRYABLE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "DELETE"})
_RETRYABLE_STATUS = frozenset({502, 503, 504})


@dataclass
class RetryConfig:
    """Retry + backoff config. Applied to idempotent methods on
    transient failures only (transport error / 502 / 503 / 504 / 429)."""

    max_retries: int = 3
    backoff: str = "exponential"  # "exponential" | "linear" | "none"
    initial_delay_ms: int = 100
    max_delay_ms: int = 5000


@dataclass
class HttpClientConfig:
    """Per-instance HTTP config."""

    base_url: str
    api_key: str | None = None
    project_slug: str | None = None
    org_slug: str | None = None
    default_headers: dict[str, str] = field(default_factory=dict)
    # Custom httpx transport for tests; if None, uses default.
    transport: httpx.BaseTransport | None = None
    # Retry config; None ⇒ the defaults (3 retries, exponential).
    retry_config: RetryConfig | None = None
    # Learned regional origin cache (k9o/region.py); None until a definite probe answer.
    _resolved_origin: str | None = field(default=None, repr=False, compare=False)


def _is_retryable(error: BaseException, method: str) -> bool:
    """A failure is retryable only on idempotent methods + transient causes."""
    if method.upper() not in _RETRYABLE_METHODS:
        return False
    if not isinstance(error, KError):
        return False
    if error.code == "K9O_UPSTREAM_UNAVAILABLE":
        return True
    if error.status in _RETRYABLE_STATUS:
        return True
    if error.status == 429:  # rate-limit
        return True
    return False


def _compute_delay_ms(config: RetryConfig, attempt: int) -> int:
    """Backoff delay for a 0-based attempt index, capped + ±25% jittered."""
    if config.backoff == "none":
        return 0
    if config.backoff == "linear":
        base = config.initial_delay_ms * (attempt + 1)
    else:
        base = config.initial_delay_ms * (2 ** attempt)
    capped = min(base, config.max_delay_ms)
    jitter = capped * 0.25 * (random.random() * 2 - 1)
    return max(0, int(capped + jitter))


def _build_headers(
    config: HttpClientConfig,
    init_headers: dict[str, str] | None,
    bearer: str | None,
    authenticated: bool = True,
) -> dict[str, str]:
    headers: dict[str, str] = {"accept": "application/json"}
    headers.update(config.default_headers)
    if config.project_slug:
        headers["x-k9o-project-slug"] = config.project_slug
    if config.org_slug:
        headers["x-k9o-org-slug"] = config.org_slug
    if init_headers:
        headers.update(init_headers)
    if not authenticated:
        # Credential-free call: no Authorization / cookie from any source.
        for k in [k for k in headers if k.lower() in ("authorization", "cookie")]:
            del headers[k]
        return headers
    token = bearer or config.api_key
    if token:
        headers["authorization"] = f"Bearer {token}"
    return headers


def _handle_response(response: httpx.Response) -> Envelope[Any]:
    if response.status_code == 204:
        return Envelope(data=None, meta=meta_from_wire(None))

    try:
        parsed = response.json()
    except ValueError as e:
        raise KError(
            code="K9O_INTERNAL_ERROR",
            message=f"Failed to parse JSON response from {response.url}: {e}",
            context={"url": str(response.url), "status": response.status_code},
            status=response.status_code,
        ) from e

    if 200 <= response.status_code < 300:
        if not isinstance(parsed, dict) or "data" not in parsed or "meta" not in parsed:
            raise KError(
                code="K9O_INTERNAL_ERROR",
                message=f"Malformed envelope from {response.url}: expected {{data, meta}}",
                context={"url": str(response.url), "status": response.status_code},
                status=response.status_code,
            )
        return Envelope(data=parsed["data"], meta=meta_from_wire(parsed.get("meta")))

    if isinstance(parsed, dict) and "code" in parsed and "message" in parsed:
        raise kerror_from_wire(parsed, response.status_code)
    raise KError(
        code="K9O_INTERNAL_ERROR",
        message=f"Upstream returned {response.status_code} with non-KError body",
        context={"url": str(response.url), "status": response.status_code, "body": parsed},
        status=response.status_code,
    )


def request(
    config: HttpClientConfig,
    *,
    method: str,
    path: str,
    body: Any = None,
    bearer: str | None = None,
    headers: dict[str, str] | None = None,
    query: dict[str, Any] | None = None,
    authenticated: bool = True,
    multipart: dict[str, Any] | None = None,
) -> Envelope[Any]:
    """Issue a request against the gateway, with retry on transient failures.

    Returns Envelope on 2xx; raises KError on non-2xx, transport failure,
    or malformed response. Idempotent methods are retried with backoff per
    `config.retry_config`; non-idempotent / semantic failures
    raise immediately.
    """
    cfg = config.retry_config or RetryConfig()
    last_error: BaseException | None = None
    for attempt in range(cfg.max_retries + 1):
        try:
            return _request_once(
                config, method=method, path=path, body=body,
                bearer=bearer, headers=headers, query=query,
                authenticated=authenticated, multipart=multipart,
            )
        except KError as e:
            last_error = e
            if attempt == cfg.max_retries or not _is_retryable(e, method):
                raise
            delay_ms = _compute_delay_ms(cfg, attempt)
            if delay_ms > 0:
                time.sleep(delay_ms / 1000)
    assert last_error is not None  # loop always sets or returns
    raise last_error


def _request_once(
    config: HttpClientConfig,
    *,
    method: str,
    path: str,
    body: Any = None,
    bearer: str | None = None,
    headers: dict[str, str] | None = None,
    query: dict[str, Any] | None = None,
    authenticated: bool = True,
    multipart: dict[str, Any] | None = None,
) -> Envelope[Any]:
    """Single-attempt request. `request` wraps this in retry-with-backoff."""
    headers_built = _build_headers(config, headers, bearer, authenticated)
    # A multipart body carries its own content-type (with the boundary, set by httpx).
    if body is not None and multipart is None:
        headers_built["content-type"] = "application/json"

    url = f"{resolve_regional_origin(config)}{path}"
    try:
        with httpx.Client(transport=config.transport) as client:
            response = client.request(
                method=method,
                url=url,
                json=body if body is not None and multipart is None else None,
                **(multipart or {}),
                headers=headers_built,
                params=query,
            )
    except (httpx.TransportError, httpx.NetworkError, httpx.TimeoutException) as e:
        raise KError(
            code="K9O_UPSTREAM_UNAVAILABLE",
            message=f"Network error reaching {url}: {e}",
            context={"url": url},
            recommendation="Check connectivity to the gateway; retry with backoff if transient.",
        ) from e

    return _handle_response(response)


async def stream_sse_async(
    config: HttpClientConfig,
    *,
    method: str,
    path: str,
    body: Any = None,
    bearer: str | None = None,
    headers: dict[str, str] | None = None,
    query: dict[str, Any] | None = None,
    authenticated: bool = True,
) -> AsyncIterator[Any]:
    """Open an SSE stream and yield JSON-decoded `data:` payloads.

    Used by streaming surfaces — `client.compute.llms.invoke_stream()`
    and `client.realtime.subscribe()` SSE transport. Multi-line `data:` fields concatenate with newline; the
    `[DONE]` sentinel terminates the stream. Raises KError on non-2xx.
    The consumer writes `async for chunk in ...`.
    """
    headers_built = _build_headers(config, headers, bearer, authenticated)
    headers_built["accept"] = "text/event-stream"
    if body is not None:
        headers_built["content-type"] = "application/json"

    url = f"{await resolve_regional_origin_async(config)}{path}"
    try:
        async with httpx.AsyncClient(transport=config.transport) as client:
            async with client.stream(
                method,
                url,
                json=body if body is not None else None,
                headers=headers_built,
                params=query,
            ) as response:
                if not (200 <= response.status_code < 300):
                    raw = await response.aread()
                    parsed: Any = None
                    try:
                        parsed = json.loads(raw)
                    except ValueError:
                        parsed = None
                    if isinstance(parsed, dict) and "code" in parsed and "message" in parsed:
                        raise kerror_from_wire(parsed, response.status_code)
                    raise KError(
                        code="K9O_INTERNAL_ERROR",
                        message=f"Upstream returned {response.status_code} opening stream",
                        context={"url": url, "status": response.status_code},
                        status=response.status_code,
                    )
                data_lines: list[str] = []
                async for line in response.aiter_lines():
                    if line == "" or line == "\r":
                        if data_lines:
                            payload = "\n".join(data_lines)
                            data_lines = []
                            if payload == "[DONE]":
                                return
                            try:
                                yield json.loads(payload)
                            except ValueError:
                                yield payload
                        continue
                    if line.startswith(":"):
                        continue
                    if line.startswith("data:"):
                        data_lines.append(line[5:].lstrip(" ").rstrip("\r"))
                if data_lines:
                    payload = "\n".join(data_lines)
                    if payload != "[DONE]":
                        try:
                            yield json.loads(payload)
                        except ValueError:
                            yield payload
    except (httpx.TransportError, httpx.NetworkError, httpx.TimeoutException) as e:
        raise KError(
            code="K9O_UPSTREAM_UNAVAILABLE",
            message=f"Network error reaching {url}: {e}",
            context={"url": url},
            recommendation="Check connectivity to the gateway; retry with backoff if transient.",
        ) from e


async def request_async(
    config: HttpClientConfig,
    *,
    method: str,
    path: str,
    body: Any = None,
    bearer: str | None = None,
    headers: dict[str, str] | None = None,
    query: dict[str, Any] | None = None,
    authenticated: bool = True,
    multipart: dict[str, Any] | None = None,
) -> Envelope[Any]:
    """Async variant of request() — same retry semantics; httpx.AsyncClient."""
    cfg = config.retry_config or RetryConfig()
    last_error: BaseException | None = None
    for attempt in range(cfg.max_retries + 1):
        try:
            return await _request_once_async(
                config, method=method, path=path, body=body,
                bearer=bearer, headers=headers, query=query,
                authenticated=authenticated, multipart=multipart,
            )
        except KError as e:
            last_error = e
            if attempt == cfg.max_retries or not _is_retryable(e, method):
                raise
            delay_ms = _compute_delay_ms(cfg, attempt)
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000)
    assert last_error is not None
    raise last_error


async def _request_once_async(
    config: HttpClientConfig,
    *,
    method: str,
    path: str,
    body: Any = None,
    bearer: str | None = None,
    headers: dict[str, str] | None = None,
    query: dict[str, Any] | None = None,
    authenticated: bool = True,
    multipart: dict[str, Any] | None = None,
) -> Envelope[Any]:
    """Single-attempt async request. `request_async` wraps this in retry."""
    headers_built = _build_headers(config, headers, bearer, authenticated)
    # A multipart body carries its own content-type (with the boundary, set by httpx).
    if body is not None and multipart is None:
        headers_built["content-type"] = "application/json"

    url = f"{await resolve_regional_origin_async(config)}{path}"
    try:
        async with httpx.AsyncClient(transport=config.transport) as client:
            response = await client.request(
                method=method,
                url=url,
                json=body if body is not None and multipart is None else None,
                **(multipart or {}),
                headers=headers_built,
                params=query,
            )
    except (httpx.TransportError, httpx.NetworkError, httpx.TimeoutException) as e:
        raise KError(
            code="K9O_UPSTREAM_UNAVAILABLE",
            message=f"Network error reaching {url}: {e}",
            context={"url": url},
            recommendation="Check connectivity to the gateway; retry with backoff if transient.",
        ) from e

    return _handle_response(response)
