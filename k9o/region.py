"""
Regional host resolution.

A region-free org host ``<org>.api.<rest>`` (or ``<org>.api-staging.<rest>``) redirects GET/HEAD only and refuses a
request that carries a body, an ``Authorization`` header or a cookie. The SDK learns the region with ONE
unauthenticated ``HEAD`` to the configured host (redirects NOT followed), takes the 308 ``Location``, caches the
regional origin on the client config and sends every request there.

Nothing here knows an apex: the host comes from the configured base URL and ``<rest>`` is whatever follows the
gateway label, so public-cloud, internal-apex, air-gapped and localhost deployments all work. Properties held here:
  - only a region-free org host is ever probed; any other base URL is used exactly as given;
  - the probe carries no credential, no cookie and none of the configured default headers;
  - the Location is trusted only if https, no userinfo, no port, and its host is exactly the SAME org, the SAME
    gateway family and the SAME remainder with a 4-character region code appended to the gateway label;
  - a definite answer (including "no redirect") is cached for the life of the config; a network failure is not.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlsplit

import httpx

from .url_grammar import parse_api_host

if TYPE_CHECKING:  # pragma: no cover
    from .http import HttpClientConfig

def _is_region_free_org_host(host: str) -> bool:
    parsed = parse_api_host(host)
    return parsed is not None and parsed.org_slug is not None and parsed.region is None


def regional_origin_from_location(host: str, location: str, base: str) -> str | None:
    """The regional origin ``location`` may name for region-free ``host``, or None if it is not exactly that."""
    frm = parse_api_host(host)
    if frm is None or frm.org_slug is None or frm.region is not None:
        return None
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
    to = parse_api_host(hostname)
    if to is None or to.region is None:
        return None
    if to.org_slug != frm.org_slug or to.family != frm.family or to.apex != frm.apex:
        return None
    return f"https://{hostname}"


def _probe_target(config: "HttpClientConfig") -> tuple[str, str] | None:
    """(configured base without trailing slash, host) when the base URL is a region-free org host, else None."""
    try:
        host = urlsplit(config.base_url).hostname
    except ValueError:
        return None
    if host is None or not _is_region_free_org_host(host):
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
