"""
Policy bundle lifecycle namespace — `client.policies.*`.

Member-plane routes. Python idiomatic.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .envelope import Envelope
from .http import HttpClientConfig, request
from .url_grammar import project_path


def _require_project_slug(config: HttpClientConfig) -> str:
    if not config.project_slug:
        raise ValueError("policies operations require project_slug bound on the client")
    return config.project_slug


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


class PoliciesNamespace:
    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def current(self) -> Envelope:
        """Read the currently-active policy bundle (data is None when none active)."""
        slug = _require_project_slug(self._config)
        return request(self._config, method="GET", path=project_path(slug, "policy"))

    def list(self, *, status: str | None = None, limit: int | None = None, cursor: str | None = None) -> Envelope:
        slug = _require_project_slug(self._config)
        return request(self._config, method="GET", path=project_path(slug, "policies"),
                       query=_clean({"status": status, "limit": limit, "cursor": cursor}))

    def create(self, *, name: str, rules: dict[str, Any]) -> Envelope:
        slug = _require_project_slug(self._config)
        return request(self._config, method="POST", path=project_path(slug, "policies"),
                       body={"name": name, "rules": rules})

    def validate(self, rules: dict[str, Any]) -> Envelope:
        """Validate a rules bundle without persisting it."""
        slug = _require_project_slug(self._config)
        return request(self._config, method="POST", path=project_path(slug, "policies/validate"),
                       body={"rules": rules})

    def get(self, bundle_id: str) -> Envelope:
        slug = _require_project_slug(self._config)
        return request(self._config, method="GET", path=project_path(slug, f"policies/{quote(bundle_id)}"))

    def update(self, bundle_id: str, *, name: str | None = None, rules: dict[str, Any] | None = None) -> Envelope:
        slug = _require_project_slug(self._config)
        return request(self._config, method="PATCH",
                       path=project_path(slug, f"policies/{quote(bundle_id)}"),
                       body=_clean({"name": name, "rules": rules}))

    def delete(self, bundle_id: str) -> Envelope:
        slug = _require_project_slug(self._config)
        return request(self._config, method="DELETE", path=project_path(slug, f"policies/{quote(bundle_id)}"))

    def publish(self, bundle_id: str) -> Envelope:
        """Publish a draft bundle (makes it the active policy)."""
        slug = _require_project_slug(self._config)
        return request(self._config, method="POST",
                       path=project_path(slug, f"policies/{quote(bundle_id)}/publish"))
