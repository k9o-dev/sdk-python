"""
URL grammar helpers (Python parallel of
@k9o/core url-grammar; identical semantics).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from .errors import KError

_SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{1,62}$")


def validate_base_url(base_url: str) -> str:
    """Validate + normalise a base URL.

    Returns normalised form (trailing slash stripped) on success;
    raises KError(K9O_INVALID_BASE_URL) on violation.
    """
    try:
        parsed = urlparse(base_url)
    except ValueError as e:
        raise KError(
            code="K9O_INVALID_BASE_URL",
            message=f'base_url "{base_url}" is not a valid URL: {e}',
            context={"base_url": base_url},
            recommendation="Pass scheme + host like 'https://api.k9o.io' or 'https://<orgSlug>.api.k9o.io'.",
        ) from e

    if parsed.scheme not in ("http", "https"):
        raise KError(
            code="K9O_INVALID_BASE_URL",
            message=f'base_url "{base_url}" uses unsupported scheme "{parsed.scheme}"; expected http or https',
            context={"base_url": base_url, "scheme": parsed.scheme},
            recommendation="Use http:// or https://. WebSocket subscriptions are wired internally over SSE.",
        )
    if not parsed.netloc:
        raise KError(
            code="K9O_INVALID_BASE_URL",
            message=f'base_url "{base_url}" missing host',
            context={"base_url": base_url},
            recommendation="Pass scheme + host.",
        )
    if parsed.path and parsed.path != "/":
        raise KError(
            code="K9O_INVALID_BASE_URL",
            message=f'base_url "{base_url}" must not contain a path segment; got "{parsed.path}"',
            context={"base_url": base_url, "path": parsed.path},
            recommendation="Strip the path segment — pass host only. URL paths are composed by the SDK.",
        )
    if parsed.query or parsed.fragment:
        raise KError(
            code="K9O_INVALID_BASE_URL",
            message=f'base_url "{base_url}" must not contain query or fragment',
            context={"base_url": base_url},
            recommendation="Pass host only.",
        )
    return f"{parsed.scheme}://{parsed.netloc}"


DEFAULT_BASE_URL = "https://api.k9o.io"
"""The convenience default when no base_url is passed (the public cloud). A default value only: it is never used to
parse a host."""


@dataclass(frozen=True)
class ApiHost:
    """The structure of a gateway API host, read from the host itself."""

    org_slug: str | None
    """First label of an org host (``acme`` in ``acme.api.corp.internal``); None for a platform host."""
    family: str
    """``api`` or ``api-staging``: the label that marks a gateway host."""
    region: str | None
    """4-character region code when the host is regional (``api-de01``), else None (region-free)."""
    apex: str
    """Everything after the gateway label (``corp.internal``, ``k9o.io``): never matched against a list."""


_API_LABEL = re.compile(r"^(api|api-staging)(?:-([a-z]{2}[0-9]{2}))?$")


def parse_api_host(host: str) -> ApiHost | None:
    """Read the org slug and region out of a gateway host without knowing its apex.

    The gateway label is ``api`` or ``api-staging``, optionally followed by ``-<rgn>``; the label before it is the
    org slug and whatever follows it is the apex. Returns None for any other shape (localhost, an IP, a single-label
    host, a host with no gateway label), which callers use exactly as given.
    """
    labels = host.lower().split(".")
    if any(label == "" for label in labels):
        return None

    def mk(gateway_label: str, org_slug: str | None, rest: list[str]) -> ApiHost | None:
        m = _API_LABEL.match(gateway_label)
        if m is None or not rest:
            return None
        return ApiHost(org_slug=org_slug, family=m.group(1), region=m.group(2), apex=".".join(rest))

    # Org host first: <org>.<api[-rgn]>.<apex>
    if (
        len(labels) >= 3
        and _SLUG_RE.match(labels[0])
        and not labels[0].endswith("-")
        and _API_LABEL.match(labels[1])
    ):
        return mk(labels[1], labels[0], labels[2:])
    # Platform host: api.<apex>
    if len(labels) >= 2 and _API_LABEL.match(labels[0]):
        return mk(labels[0], None, labels[1:])
    return None


def resolve_base_url(base_url: str | None, org_slug: str | None = None) -> str:
    """Resolve the effective base URL.

    ``base_url`` is OPTIONAL: omitted, it defaults to DEFAULT_BASE_URL (the public cloud, a convenience only). When
    the (validated) host is a platform host (``api.<apex>`` or ``api-staging.<apex>``, any apex) and ``org_slug`` is
    supplied, the canonical org host ``<org_slug>.<host>`` is composed. Any other host (an org host already, an
    internal or air-gapped host, localhost) passes through unchanged; ``org_slug`` is then only sent as a header.

    Keeps the base URL validation (raises K9O_INVALID_BASE_URL).
    """
    validated = validate_base_url(base_url if base_url is not None else DEFAULT_BASE_URL)
    parsed = urlparse(validated)
    host = parse_api_host(parsed.hostname or "")
    if host is not None and host.org_slug is None and host.region is None and org_slug:
        validate_slug(org_slug, "org")
        return f"{parsed.scheme}://{org_slug}.{parsed.netloc}"
    return validated


def validate_slug(slug: str, kind: str) -> None:
    """Validate an org/project slug."""
    if not _SLUG_RE.match(slug) or slug.endswith("-"):
        raise KError(
            code="K9O_INVALID_FIELD_VALUE",
            message=f'{kind}_slug "{slug}" does not match required format ^[a-z][a-z0-9-]{{1,62}}$ (must not end with hyphen)',
            context={"slug": slug, "kind": kind},
            recommendation="Lowercase letters/digits/hyphens; 2-63 chars; starts with a letter; does not end with hyphen.",
        )


def project_path(project_slug: str, sub_resource: str) -> str:
    """Member-plane path: /@<slug>/<sub-resource>."""
    validate_slug(project_slug, "project")
    cleaned = sub_resource.lstrip("/")
    return f"/@{project_slug}/{cleaned}"


def org_path(resource: str) -> str:
    """Org-plane path: /<resource>."""
    return "/" + resource.lstrip("/")


def platform_path(resource: str) -> str:
    """Platform-plane path: /<resource> (cross-org)."""
    return "/" + resource.lstrip("/")
