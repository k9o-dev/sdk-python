"""
Regional host resolution.

The region-free org host ``<org>.api[-staging].k9o.io`` redirects GET/HEAD only and refuses a request that carries a
body, an ``Authorization`` header or a cookie. The SDK learns the region with ONE unauthenticated
``HEAD https://<org>.api[-staging].k9o.io/`` (redirects NOT followed), takes the 308 ``Location``, caches the regional
origin on the client config and sends every request there.

Properties held here:
  - only a region-free org host is ever probed; any other base URL is used exactly as given;
  - the probe carries no credential, no cookie and none of the configured default headers;
  - the Location is trusted only if https, no userinfo, no port, and host exactly
    ``<same org>.<same apex family>-<rgn>.k9o.io`` with ``<rgn>`` matching ``[a-z]{2}[0-9]{2}``;
  - a definite answer (including "no redirect") is cached for the life of the config; a network failure is not.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlsplit

import httpx

if TYPE_CHECKING:  # pragma: no cover
    from .http import HttpClientConfig

_REGION_FREE_ORG_HOST = re.compile(r"([a-z][a-z0-9-]{1,62})\.(api|api-staging)\.k9o\.io")
_REGION_CODE = re.compile(r"[a-z]{2}[0-9]{2}")


def regional_origin_from_location(host: str, location: str, base: str) -> str | None:
    """The regional origin ``location`` may name for region-free ``host``, or None if it is not exactly that."""
    m = _REGION_FREE_ORG_HOST.fullmatch(host)
    if m is None:
        return None
    org, apex = m.group(1), m.group(2)
    try:
        u = urlsplit(urljoin(base.rstrip("/") + "/", location))
        port = u.port
    except ValueError:
        return None
    if u.scheme != "https" or port is not None:
        return None
    if u.username is not None or u.password is not None or "@" in u.netloc or ":" in u.netloc:
        return None
    hostname = u.hostname
    if hostname is None:
        return None
    r = re.fullmatch(rf"{re.escape(org)}\.{re.escape(apex)}-([a-z0-9]+)\.k9o\.io", hostname)
    if r is None or _REGION_CODE.fullmatch(r.group(1)) is None:
        return None
    return f"https://{hostname}"


def _probe_target(config: "HttpClientConfig") -> tuple[str, str] | None:
    """(configured base without trailing slash, host) when the base URL is a region-free org host, else None."""
    try:
        host = urlsplit(config.base_url).hostname
    except ValueError:
        return None
    if host is None or _REGION_FREE_ORG_HOST.fullmatch(host) is None:
        return None
    return config.base_url.rstrip("/"), host


def _answer(host: str, configured: str, res: httpx.Response) -> str:
    if res.status_code == 308:
        loc = res.headers.get("location")
        if loc is not None:
            origin = regional_origin_from_location(host, loc, configured)
            if origin is not None:
                return origin
    return configured


def resolve_regional_origin(config: "HttpClientConfig") -> str:
    """Origin requests go to: cached regional origin once learned, else the configured base URL (sync)."""
    if config._resolved_origin is not None:
        return config._resolved_origin
    target = _probe_target(config)
    if target is None:
        config._resolved_origin = config.base_url.rstrip("/")
        return config._resolved_origin
    configured, host = target
    try:
        with httpx.Client(transport=config.transport, follow_redirects=False) as client:
            res = client.request("HEAD", f"{configured}/", headers={"accept": "*/*"})
    except httpx.HTTPError:
        return configured  # network failure: not cached
    config._resolved_origin = _answer(host, configured, res)
    return config._resolved_origin


async def resolve_regional_origin_async(config: "HttpClientConfig") -> str:
    """Async variant of :func:`resolve_regional_origin`."""
    if config._resolved_origin is not None:
        return config._resolved_origin
    target = _probe_target(config)
    if target is None:
        config._resolved_origin = config.base_url.rstrip("/")
        return config._resolved_origin
    configured, host = target
    try:
        async with httpx.AsyncClient(transport=config.transport, follow_redirects=False) as client:
            res = await client.request("HEAD", f"{configured}/", headers={"accept": "*/*"})
    except httpx.HTTPError:
        return configured
    config._resolved_origin = _answer(host, configured, res)
    return config._resolved_origin
