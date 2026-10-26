"""
Org lifecycle namespace (collection-style) — `client.orgs.*`.

Distinct from `client.org` (singular bound-org namespace). Org-plane / platform-plane routes.
"""

from __future__ import annotations

from urllib.parse import quote

from .envelope import Envelope
from .http import HttpClientConfig, request
from .url_grammar import org_path, validate_slug


class OrgsNamespace:
    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def list(self) -> Envelope:
        """List orgs accessible to the caller."""
        return request(self._config, method="GET", path=org_path("orgs"))

    def get(self, org_slug: str) -> Envelope:
        """Get a single org by slug."""
        validate_slug(org_slug, "org")
        return request(self._config, method="GET", path=org_path(f"orgs/{quote(org_slug, safe='')}"))

    def restore(self, org_id: str) -> Envelope:
        """Restore a soft-deleted org (keyed by org id: a deleted org's slug is tombstoned)."""
        return request(self._config, method="POST", path=org_path(f"orgs/{quote(org_id, safe='')}/restore"))

    def current(self) -> Envelope:
        """Get the org bound to the caller's current session context."""
        return request(self._config, method="GET", path=org_path("org"))
