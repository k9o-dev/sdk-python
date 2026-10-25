"""
Org lifecycle namespace (collection-style) — `client.orgs.*`.

Distinct from `client.org` (singular bound-org namespace). Org-plane /
platform-plane routes. Python idiomatic.
"""

from __future__ import annotations

from urllib.parse import quote

from .envelope import Envelope
from .http import HttpClientConfig, request
from .url_grammar import org_path


class OrgsNamespace:
    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def list(self) -> Envelope:
        """List orgs accessible to the caller."""
        return request(self._config, method="GET", path=org_path("orgs"))

    def get(self, org_slug: str) -> Envelope:
        """Get a single org by slug."""
        return request(self._config, method="GET", path=org_path(f"orgs/{quote(org_slug)}"))

    def restore(self, org_id: str) -> Envelope:
        """Restore a soft-deleted org."""
        return request(self._config, method="POST", path=org_path(f"orgs/{quote(org_id)}/restore"))

    def current(self) -> Envelope:
        """Get the org bound to the caller's current session context."""
        return request(self._config, method="GET", path=org_path("org"))
