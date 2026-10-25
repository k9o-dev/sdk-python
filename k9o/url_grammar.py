"""
URL grammar helpers (Python parallel of
@k9o/core/url-grammar.ts; identical semantics).
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from .errors import KError

_SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{1,62}$")


def validate_base_url(base_url: str) -> str:
    """Validate + normalise a baseUrl.

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
            recommendation="Strip the path segment — pass host only. URLs composed by the SDK.",
        )
    if parsed.query or parsed.fragment:
        raise KError(
            code="K9O_INVALID_BASE_URL",
            message=f'base_url "{base_url}" must not contain query or fragment',
            context={"base_url": base_url},
            recommendation="Pass host only.",
        )
    return f"{parsed.scheme}://{parsed.netloc}"


K9O_ORG_DERIVABLE_APEXES = {"api.k9o.io", "api-staging.k9o.io"}
"""Bare platform apex hosts org-subdomain derivation applies to — production
and staging share the `<orgSlug>.<apex>` wire-routing scheme (confirmed
live). A third apex needs the same confirmation before joining this set."""


def resolve_base_url(base_url: str | None, org_slug: str | None = None) -> str:
    """Resolve the effective baseUrl.

    `base_url` is OPTIONAL — it defaults to the platform apex
    'https://api.k9o.io'. When the (validated) host is a bare apex in
    K9O_ORG_DERIVABLE_APEXES and `org_slug` is supplied, the SDK composes the
    canonical org-subdomain wire root 'https://<orgSlug>.<apex>'.
    An explicit '<orgSlug>' subdomain, a self-hosted / Sovereign host, or a
    dev host (anything not in that set) passes through unchanged — org_slug
    is intentionally NOT composed onto a non-apex host.

    Fixed 2026-08-30 (SDK-2): this used to silently ignore org_slug for
    'api-staging.k9o.io' too, not just genuine self-hosted/custom hosts,
    since only the literal production apex string was checked.

    Keeps the existing baseUrl validation (raises K9O_INVALID_BASE_URL).
    """
    validated = validate_base_url(base_url if base_url is not None else "https://api.k9o.io")
    parsed = urlparse(validated)
    if parsed.hostname in K9O_ORG_DERIVABLE_APEXES and org_slug:
        validate_slug(org_slug, "org")
        return f"{parsed.scheme}://{org_slug}.{parsed.hostname}"
    return validated


def validate_slug(slug: str, kind: str) -> None:
    """Validate org/project slug + feedback_slug_addressing_v2_5_68."""
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
    """Platform-plane path: /<resource> (against api.k9o.io)."""
    return "/" + resource.lstrip("/")
